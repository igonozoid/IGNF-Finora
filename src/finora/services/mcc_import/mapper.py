"""Mapeamento MCC -> Finora (Fase 2.2; tabela em docs/ANALISE-MCC.md §3).

Cada empresa (conta controle) do MCC vira uma entidade nova no Finora:

- contas (B banco, C caixa interno; sem empresa = compartilhada), centros de custo (aplica a despesa/receita,
  orçamento, projeção), pessoas (C cliente / F fornecedor; sem empresa = compartilhada);
- itens de despesa/receita viram subcategorias de dois grupos, "Despesas do MCC" e "Receitas do MCC", até você
  reclassificar na DRE;
- lançamentos (D/R) com séries, parcela n/N, observação e lixeira; pessoa em texto livre vira o contato de mesmo
  nome (sem diferença de acento/maiúscula) ou um contato novo;
- movimentações bancárias: T transferência, D depósito, R retirada (ajustes de saldo);
- dados da empresa, logotipo, "usa centro de custo", preferências (FConfigConta) e o período bloqueado, que é
  aplicado por último (senão travaria a própria importação).

Decisão D6: lançamento pago sem data de pagamento entra pago com a data do vencimento; os ids vão em
`ImportResult.paid_without_date` para o relatório de conferência apontar a diferença de saldo.

Valores que o Finora não aceita (CNPJ inválido, UF, CEP, e-mail) não param a importação: o campo fica vazio e
vira um aviso em `ImportResult.warnings`. Ainda fora: usuários (2.6), reimportar sem duplicar (2.8) e as linhas de
OFX (o MCC só guarda o identificador, não dá para remontar o extrato).
"""
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from finora.core import settings
from finora.models import Account, Category, Contact, Entity, Entry
from finora.services import accounts, contacts, cost_centers, entity_admin, period_lock, scope
from finora.services.mcc_import import reader

CENT = Decimal("0.01")
# grupo da DRE dos itens importados, por modelo: (despesa, receita)
ITEM_GROUPS = {"personal": ("outras", "receitas"), "business": ("administrativas", "receita_bruta")}
FIRST_FIELD = {"conta": "account", "documento": "document", "data": "date", "descricao": "description"}
ADJUST = {"D": "deposit", "R": "withdrawal"}


@dataclass
class ImportResult:
    entities: dict[int, int] = field(default_factory=dict)       # empresa do MCC -> entidade do Finora
    accounts: dict[int, int] = field(default_factory=dict)
    cost_centers: dict[int, int] = field(default_factory=dict)
    contacts: dict[int, int] = field(default_factory=dict)       # pessoa do MCC -> contato
    categories: dict[tuple[int, str, str], int] = field(default_factory=dict)   # (empresa, D/R, item) -> categoria
    entries: dict[int, int] = field(default_factory=dict)        # lançamento do MCC -> lançamento
    movements: dict[int, int] = field(default_factory=dict)      # movimentação bancária do MCC -> lançamento
    contacts_created_from_text: int = 0
    paid_without_date: list[int] = field(default_factory=list)   # D6: lançamentos do MCC (ids)
    warnings: list[str] = field(default_factory=list)


def normalize(text: str | None) -> str:
    """Para casar nomes: sem acento, sem diferença de maiúscula e com espaços simples."""
    s = unicodedata.normalize("NFD", str(text or ""))
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").lower().split())


def money(v) -> Decimal:
    """REAL do MCC -> Decimal com 2 casas (pelo texto do número, sem resíduo de ponto flutuante)."""
    return Decimal(repr(float(v or 0))).quantize(CENT, rounding=ROUND_HALF_UP)


def _day(text: str | None) -> date | None:
    return date.fromisoformat(str(text)[:10]) if text else None


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    t = str(text).replace("T", " ")
    return datetime.fromisoformat(t[:19]) if len(t) >= 19 else datetime.fromisoformat(t[:10] + " 00:00:00")


class _Importer:
    def __init__(self, s: Session, con: sqlite3.Connection, companies: list[int] | None):
        self.s, self.con, self.r = s, con, ImportResult()
        self.companies = [e for e in reader.rows(con, "empresas") if companies is None or e["id"] in companies]
        if not self.companies:
            raise ValueError("Nenhuma empresa do MCC para importar.")
        self.first_entity: int | None = None
        self.groups: dict[tuple[int, str], int] = {}
        self.no_account: dict[int, int] = {}

    def warn(self, text: str):
        self.r.warnings.append(text)

    # ---------- empresas ----------
    def entity(self, e: dict) -> int:
        ptype = "PJ" if e["pessoa"] == "J" else "PF"
        name = e["nome"].strip()
        if self.s.scalar(select(Entity.id).where(Entity.name.ilike(name))):
            name = f"{name} (MCC)"
        model = "business" if ptype == "PJ" else "personal"
        try:
            eid = entity_admin.create(self.s, name=name, person_type=ptype, document=e.get("documento"),
                                      default_categories=False, dre_model=model)
        except ValueError as exc:
            if "inválido" not in str(exc):
                raise
            self.warn(f"{name}: {exc} O documento ficou em branco.")
            eid = entity_admin.create(self.s, name=name, person_type=ptype, default_categories=False,
                                      dre_model=model)
        for acc in self.s.scalars(select(Account).where(Account.entity_id == eid)):   # a conta que vem de brinde
            self.s.delete(acc)
        self.s.commit()
        details = {"document2": e.get("documento2"), "address": e.get("endereco"), "district": e.get("bairro"),
                   "city": e.get("cidade"), "state": e.get("uf"), "zip_code": e.get("cep"),
                   "phone": e.get("telefone"), "email": e.get("email"), "website": e.get("site")}
        for key, value in details.items():
            if value:
                try:
                    entity_admin.update_details(self.s, eid, **{key: str(value)})
                except ValueError as exc:
                    self.s.rollback()
                    self.warn(f"{name}: {key} \"{value}\" não foi aceito ({exc}).")
        entity_admin.set_uses_cost_centers(self.s, eid, bool(e.get("usa_centro_custo", 1)))
        logo = next((r["imagem"] for r in reader.rows(self.con, "empresa_logos", "empresa_id=?", (e["id"],))), None)
        if logo:
            entity_admin.set_logo(self.s, eid, bytes(logo))
        self.r.entities[e["id"]] = eid
        self.first_entity = self.first_entity or eid
        return eid

    def preferences(self, e: dict, eid: int):
        cfg = {r["chave"]: r["valor"] for r in reader.rows(self.con, "empresa_config", "empresa_id=?", (e["id"],))}
        if not cfg:
            return
        acc = self.r.accounts.get(int(cfg["conta_padrao"])) if (cfg.get("conta_padrao") or "").isdigit() else None
        settings.set_entry_prefs(eid, settings.EntryPrefs(
            acc, FIRST_FIELD.get(cfg.get("campo_inicial") or "", "description"), cfg.get("exibir_saldos", "1") == "1"))

    # ---------- cadastros ----------
    def _owner(self, empresa_id) -> tuple[int, bool]:
        """Entidade dona e se é compartilhado (sem empresa no MCC: vai para a 1ª entidade, compartilhado)."""
        if empresa_id is None:
            return self.first_entity, True
        return self.r.entities[empresa_id], False

    def account_rows(self):
        ids = list(self.r.entities)
        for c in reader.rows(self.con, "contas"):
            if c["empresa_id"] is not None and c["empresa_id"] not in ids:
                continue
            eid, shared = self._owner(c["empresa_id"])
            kind = "cash" if c["tipo"] == "C" else "bank"
            limit = money(c.get("limite")) if kind == "bank" and c.get("limite") else None
            name = c["descricao"].strip()
            for attempt in (name, f"{name} (MCC)"):
                try:
                    aid = accounts.create(self.s, eid, name=attempt, kind=kind, opening_balance=money(c["saldo_inicial"]),
                                          credit_limit=limit or None, shared=shared)
                    break
                except ValueError as exc:
                    if "Já existe" not in str(exc) or attempt != name:
                        raise
            if not c["ativa"]:
                accounts.set_active(self.s, aid, False)
            self.r.accounts[c["id"]] = aid

    def cost_center_rows(self):
        for c in reader.rows(self.con, "centros"):
            if c["empresa_id"] not in self.r.entities:
                continue
            exp, inc = bool(c["aplica_despesa"]), bool(c["aplica_receita"])
            if not (exp or inc):
                exp = inc = True
                self.warn(f"Centro \"{c['nome']}\" não valia para nada no MCC: ficou para despesas e receitas.")
            self.r.cost_centers[c["id"]] = cost_centers.create(
                self.s, self.r.entities[c["empresa_id"]], c["nome"], money(c["orcamento"]) or None,
                applies_expense=exp, applies_income=inc, projection=money(c["projecao"]) or None)

    def _details(self, p: dict, who: str) -> dict:
        raw = {"phone": p.get("telefone"), "email": p.get("email"), "document2": p.get("documento2"),
               "contact_person": p.get("contato"), "zip_code": p.get("cep"), "address": p.get("endereco"),
               "district": p.get("bairro"), "city": p.get("cidade"), "state": p.get("uf"),
               "bank_name": p.get("banco"), "bank_branch": p.get("agencia"), "bank_account": p.get("conta_bancaria"),
               "notes": p.get("observacao")}
        out = {}
        for key, value in raw.items():
            if not value:
                continue
            try:
                out.update(contacts.clean_details({key: str(value)}))
            except ValueError as exc:
                self.warn(f"{who}: {key} \"{value}\" não foi aceito ({exc}).")
        return out

    def contact_rows(self):
        by_name: dict[tuple[int, str], int] = {}
        for p in reader.rows(self.con, "pessoas"):
            if p["empresa_id"] is not None and p["empresa_id"] not in self.r.entities:
                continue
            eid, shared = self._owner(p["empresa_id"])
            role = "customer" if p["tipo"] == "C" else "supplier"
            key = (eid, normalize(p["nome"]))
            if key in by_name:                             # mesmo nome como cliente e fornecedor: um contato só
                c = self.s.get(Contact, by_name[key])
                setattr(c, contacts.ROLES[role][0], True)
                self.s.commit()
                self.r.contacts[p["id"]] = c.id
                continue
            ptype = "PJ" if p["pessoa"] == "J" else "PF"
            details = self._details(p, p["nome"])
            try:
                cid = contacts.create(self.s, eid, name=p["nome"], person_type=ptype, document=p.get("documento"),
                                      roles={role}, details=details, shared=shared)
            except ValueError as exc:
                if "inválido" not in str(exc) and "documento" not in str(exc):
                    raise
                self.warn(f"{p['nome']}: {exc} O documento \"{p.get('documento')}\" ficou nas observações.")
                details["notes"] = ((details.get("notes") or "") + f"\nDocumento no MCC: {p.get('documento')}").strip()
                cid = contacts.create(self.s, eid, name=p["nome"], person_type=ptype, roles={role},
                                      details=details, shared=shared)
            by_name[key] = cid
            self.r.contacts[p["id"]] = cid

    def _group(self, eid: int, tipo: str) -> int:
        if (eid, tipo) not in self.groups:
            model = self.s.get(Entity, eid).dre_model or "personal"
            expense, income = ITEM_GROUPS[model]
            from finora.services import categories
            self.groups[(eid, tipo)] = categories.create(
                self.s, eid, name="Despesas do MCC" if tipo == "D" else "Receitas do MCC",
                dre_group=expense if tipo == "D" else income)
        return self.groups[(eid, tipo)]

    def category(self, empresa_id: int, tipo: str, item: str) -> int:
        key = (empresa_id, tipo, normalize(item))
        if key not in self.r.categories:
            from finora.services import categories
            eid = self.r.entities[empresa_id]
            self.r.categories[key] = categories.create(self.s, eid, name=item.strip()[:80] or "Sem descrição",
                                                       parent_id=self._group(eid, tipo))
        return self.r.categories[key]

    def item_rows(self):
        for i in reader.rows(self.con, "itens"):
            if i["empresa_id"] in self.r.entities:
                self.category(i["empresa_id"], i["tipo"], i["descricao"])

    # ---------- lançamentos ----------
    def _contact_for(self, eid: int, name: str | None, kind: str) -> int | None:
        if not (name or "").strip():
            return None
        target = normalize(name)
        for c in self.s.scalars(select(Contact).where(scope.contacts(eid))):
            if normalize(c.name) == target:
                return c.id
        cid = contacts.create(self.s, eid, name=" ".join(name.split())[:150],
                              roles={"supplier" if kind == "expense" else "customer"})
        self.r.contacts_created_from_text += 1
        return cid

    def _account_for(self, eid: int, account_id: int | None) -> int:
        if account_id in self.r.accounts:
            return self.r.accounts[account_id]
        if eid not in self.no_account:
            self.no_account[eid] = accounts.create(self.s, eid, name="A definir (MCC)", kind="cash",
                                                   opening_balance=Decimal(0))
            self.warn(f"{self.s.get(Entity, eid).name}: lançamentos sem conta no MCC foram para a conta "
                      "\"A definir (MCC)\".")
        return self.no_account[eid]

    def entry_rows(self):
        series: dict[str, str] = {}
        for l in reader.rows(self.con, "lancamentos"):
            if l["empresa_id"] not in self.r.entities:
                continue
            eid = self.r.entities[l["empresa_id"]]
            kind = "income" if l["tipo"] == "R" else "expense"
            paid = l["situacao"] == "V"
            paid_day = _day(l["data_pagamento"])
            if paid and paid_day is None:                  # D6: pago sem data -> data do vencimento
                paid_day = _day(l["vencimento"])
                self.r.paid_without_date.append(l["id"])
            total = l.get("total_parcelas") or 0
            e = Entry(entity_id=eid, kind=kind, account_id=self._account_for(eid, l["conta_id"]),
                      category_id=self.category(l["empresa_id"], l["tipo"], l["descricao"]),
                      cost_center_id=self.r.cost_centers.get(l.get("centro_id")),
                      contact_id=self._contact_for(eid, l.get("pessoa"), kind),
                      amount=money(l["valor"]), description=(l["descricao"] or "").strip()[:200],
                      document_no=(l.get("documento") or "").strip()[:40] or None,
                      notes=(l.get("observacao") or "").strip() or None,
                      competence_date=_day(l["data_mov"]), due_date=_day(l["vencimento"]),
                      status="paid" if paid else "pending", paid_date=paid_day if paid else None,
                      installment=f"{l['parcela']}/{total}" if total and total > 1 and l.get("parcela") else None,
                      series_id=series.setdefault(l["grupo"], uuid.uuid4().hex) if l.get("grupo") else None,
                      deleted_at=_when(l.get("excluido_em")), deleted_by="MCC" if l.get("excluido_em") else None)
            self.s.add(e)
            self.s.flush()
            self.r.entries[l["id"]] = e.id
        self.s.commit()

    def movement_rows(self):
        labels = {"T": "Transferência", "D": "Depósito", "R": "Retirada"}
        for m in reader.rows(self.con, "movbancarias"):
            if m["empresa_id"] not in self.r.entities:
                continue
            eid = self.r.entities[m["empresa_id"]]
            if m["origem_id"] not in self.r.accounts or (m["tipo"] == "T" and m["destino_id"] not in self.r.accounts):
                self.warn(f"Movimentação bancária {m['id']} do MCC usa uma conta que não veio: ficou de fora.")
                continue
            day, paid = _day(m["data"]), m["situacao"] == "V"
            obs = (m.get("observacao") or "").strip()
            e = Entry(entity_id=eid, kind="transfer" if m["tipo"] == "T" else ADJUST[m["tipo"]],
                      account_id=self.r.accounts[m["origem_id"]],
                      dest_account_id=self.r.accounts[m["destino_id"]] if m["tipo"] == "T" else None,
                      amount=money(m["valor"]), description=(obs or labels[m["tipo"]])[:200],
                      notes=obs or None, competence_date=day, due_date=day,
                      status="paid" if paid else "pending", paid_date=day if paid else None,
                      deleted_at=_when(m.get("excluido_em")), deleted_by="MCC" if m.get("excluido_em") else None)
            self.s.add(e)
            self.s.flush()
            self.r.movements[m["id"]] = e.id
        self.s.commit()

    def run(self) -> ImportResult:
        for e in self.companies:
            self.entity(e)
        self.account_rows()
        self.cost_center_rows()
        self.contact_rows()
        self.item_rows()
        self.entry_rows()
        self.movement_rows()
        for e in self.companies:
            eid = self.r.entities[e["id"]]
            self.preferences(e, eid)
            if e.get("bloqueio_ate"):
                period_lock.set_lock(self.s, eid, _day(e["bloqueio_ate"]))
        n_ofx = len(reader.rows(self.con, "ofx_importados"))
        if n_ofx:
            self.warn(f"{n_ofx} marcas de extrato OFX já importado no MCC não vieram: na conciliação do Finora, "
                      "importe o extrato de novo (o que já tem lançamento é casado sozinho).")
        return self.r


def import_companies(s: Session, con: sqlite3.Connection, companies: list[int] | None = None) -> ImportResult:
    """Importa as empresas do MCC (todas, ou só as indicadas) como entidades novas. `con` vem de reader.open_copy."""
    return _Importer(s, con, companies).run()
