"""Reclassificar categorias na DRE em lote (Fase 2.14).

Os itens do MCC chegam como subcategorias de "Despesas do MCC" / "Receitas do MCC". Aqui se escolhe, para várias
de uma vez, o grupo certo (a linha da DRE vem do grupo). O Finora sugere o destino:
1. pelas regras automáticas (a regra que serve para o nome do item aponta a categoria);
2. por uma subcategoria de mesmo nome em outro grupo ("Combustível" já existe em Transporte);
3. por palavras do nome ("adubo" -> Custos; "tarifa" -> Despesas financeiras).
Se o grupo de destino já tem uma subcategoria com o mesmo nome, as duas viram uma só (lançamentos, regras,
itens de estoque, vendas e orçamento passam para a que já existia).
"""
import re
from dataclasses import dataclass

from sqlalchemy import func, select, update as sql_update
from sqlalchemy.orm import Session

from finora.models import Budget, Category, CategoryRule, Entry, ImportMap, Item, Sale
from finora.services import rules, scope

# linha da DRE -> pedaços de palavra (sem acento, minúsculas) que indicam essa linha
KEYWORDS = {
    # empresa
    "receita_bruta": ["venda", "servico", "prestacao", "faturamento"],
    "deducoes": ["simples nacional", "iss", "icms", "pis", "cofins", "funrural", "devolucao"],
    "custos": ["adubo", "fertiliz", "semente", "insumo", "racao", "defensivo", "mercadoria", "materia prima",
               "embalagem", "muda", "vacina"],
    "pessoal": ["salario", "folha", "inss", "fgts", "ferias", "13o", "rescis", "diarista", "vale transporte"],
    "administrativas": ["energia", "luz", "agua", "telefone", "internet", "aluguel", "contab", "contador",
                        "escritorio", "manutencao", "combustivel", "seguro", "limpeza"],
    "comerciais": ["frete", "propaganda", "marketing", "comissao", "publicidade"],
    "receitas_fin": ["rendimento", "juros recebidos", "aplicacao financeira"],
    "despesas_fin": ["tarifa", "juros", "iof", "multa", "encargo"],
    "impostos_lucro": ["irpj", "csll"],
    "retiradas": ["pro labore", "pro-labore", "retirada", "distribuicao de lucro"],
    "imobilizado": ["trator", "veiculo novo", "maquina nova", "equipamento", "imovel", "benfeitoria"],
    # pessoal
    "receitas": ["salario", "renda", "rendimento", "reembolso"],
    "moradia": ["aluguel", "condominio", "luz", "energia", "agua", "gas", "internet", "telefone", "iptu"],
    "alimentacao": ["supermercado", "mercado", "padaria", "feira", "restaurante", "lanche", "acougue"],
    "transporte": ["combustivel", "gasolina", "etanol", "uber", "onibus", "estacionamento", "ipva", "oficina",
                   "pedagio"],
    "saude": ["farmacia", "medic", "plano de saude", "dentista", "exame", "hospital", "academia"],
    "educacao": ["escola", "faculdade", "curso", "livro", "material escolar", "mensalidade"],
    "lazer": ["viagem", "cinema", "streaming", "netflix", "passeio", "hotel"],
    "outras": ["roupa", "presente", "tarifa", "imposto", "taxa", "cabeleireiro"],
    "investimentos": ["aplicacao", "poupanca", "previdencia", "investimento", "reserva"],
}


@dataclass(frozen=True)
class Suggestion:
    category_id: int
    name: str
    kind: str
    group_id: int                    # grupo atual
    entries: int                     # lançamentos (fora da lixeira)
    target: int | str | None         # grupo sugerido, ou a linha da DRE (grupo novo); None = sem sugestão
    reason: str                      # por que (regra, nome igual, palavra)


@dataclass(frozen=True)
class Outcome:
    moved: int                       # subcategorias que mudaram de grupo
    merged: int                      # juntadas a uma de mesmo nome no destino
    entries: int                     # lançamentos que mudaram de categoria (só nas juntadas)


def _has(key: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word), key) is not None


def _groups(s: Session, entity_id: int) -> list[Category]:
    return list(s.scalars(select(Category).where(scope.categories(entity_id), Category.parent_id.is_(None),
                                                 Category.is_active).order_by(Category.code)))


def suggest(s: Session, entity_id: int, group_id: int) -> list[Suggestion]:
    """Sugestão de destino para cada subcategoria do grupo."""
    from finora.services import categories
    groups = _groups(s, entity_id)
    current = s.get(Category, group_id)
    by_line: dict[tuple[str, str], int | str] = {(line, categories.kind_for(line)): line
                                                 for line in categories.model_groups(s, entity_id)}
    for g in groups:                                       # grupo que já existe na linha ganha da linha "nova"
        if g.id != group_id and not isinstance(by_line.get((g.dre_group or "", g.kind), 0), int):
            by_line[(g.dre_group or "", g.kind)] = g.id
    others = {(rules.norm(c.name), c.kind): c.parent_id
              for c in s.scalars(select(Category).where(scope.categories(entity_id), Category.parent_id.is_not(None),
                                                        Category.parent_id != group_id, Category.is_active))}
    names = {g.id: g.name for g in groups}
    counts = dict(s.execute(select(Entry.category_id, func.count(Entry.id)).where(Entry.entity_id == entity_id)
                            .group_by(Entry.category_id)).all())
    out = []
    for c in s.scalars(select(Category).where(Category.parent_id == group_id).order_by(Category.name)):
        key = rules.norm(c.name)
        target, reason = None, ""
        rule = rules.match(s, entity_id, c.name, c.kind)
        if rule and rule.category_id:
            cat = s.get(Category, rule.category_id)
            parent = cat.parent_id or cat.id
            if parent != group_id:
                target, reason = parent, f"regra automática \"{rule.text}\""
        if target is None and (key, c.kind) in others:
            target = others[(key, c.kind)]
            reason = f"já existe \"{c.name}\" em {names.get(target, 'outro grupo')}"
        if target is None:
            for line, words in KEYWORDS.items():
                word = next((w for w in words if _has(key, w)), None)
                if word and (line, c.kind) in by_line:
                    if line != current.dre_group:          # já está nessa linha da DRE: nada a mudar
                        target, reason = by_line[(line, c.kind)], f"palavra \"{word}\""
                    break
        out.append(Suggestion(c.id, c.name, c.kind, group_id, counts.get(c.id, 0), target, reason))
    return out


def _closed(s: Session, entity_id: int, category_id: int) -> bool:
    from finora.services import period_lock
    lock = period_lock.locked_through(s, entity_id)
    if lock is None:
        return False
    q = (select(Entry.id).where(Entry.category_id == category_id, Entry.competence_date <= lock)
         .execution_options(include_deleted=True).limit(1))
    return s.scalar(q) is not None


def _line_group(s: Session, entity_id: int, line: str) -> Category | str:
    """O grupo desta entidade na linha da DRE, ou a própria linha (o grupo é criado ao aplicar)."""
    from finora.services import categories
    if line not in categories.model_groups(s, entity_id):
        raise ValueError("Linha da DRE inválida para esta entidade.")
    g = s.scalar(select(Category).where(Category.entity_id == entity_id, Category.parent_id.is_(None),
                                        Category.dre_group == line).order_by(Category.code))
    return g if g is not None else line


def reclassify(s: Session, entity_id: int, moves: dict[int, int | str]) -> Outcome:
    """`moves`: subcategoria -> grupo de destino (id) ou linha da DRE (usa o grupo dessa linha, ou cria um com o
    nome da linha). Confere todas antes de mudar alguma; se uma não puder, nenhuma muda."""
    from finora.services import audit, categories
    from finora.services.dre import GROUPS
    plan = []
    for cid, dest in moves.items():
        c = s.get(Category, cid)
        g = _line_group(s, entity_id, dest) if isinstance(dest, str) else s.get(Category, dest)
        if c is None or g is None or c.parent_id is None or (not isinstance(g, str) and g.parent_id is not None):
            raise ValueError("Escolha uma subcategoria e um grupo principal.")
        if c.entity_id != entity_id:
            raise ValueError(f"\"{c.name}\" é compartilhada por outra entidade: reclassifique lá.")
        g_name, g_kind = (GROUPS[g], categories.kind_for(g)) if isinstance(g, str) else (g.name, g.kind)
        if not isinstance(g, str) and c.parent_id == g.id:
            continue
        if c.kind != g_kind:
            raise ValueError(f"\"{c.name}\" é de {'receita' if c.kind == 'income' else 'despesa'}: o grupo "
                             f"\"{g_name}\" é do outro tipo.")
        if _closed(s, entity_id, cid):
            raise ValueError(f"\"{c.name}\" tem lançamentos num período fechado: reabra o período em "
                             "Configurações para reclassificar (a DRE do passado mudaria).")
        twin = None if isinstance(g, str) else s.scalar(
            select(Category).where(Category.parent_id == g.id, Category.id != cid,
                                   func.lower(Category.name) == c.name.lower()))
        if twin is not None and _closed(s, entity_id, twin.id):
            raise ValueError(f"\"{twin.name}\" em \"{g_name}\" tem lançamentos num período fechado.")
        plan.append((c, g, twin))
    moved = merged = n_entries = 0
    lines = []
    created: dict[str, Category] = {}
    for c, g, twin in plan:
        if isinstance(g, str):                             # linha sem grupo ainda: cria uma vez só
            if g not in created:
                created[g] = Category(entity_id=entity_id, parent_id=None, code=categories._next_code(s, entity_id, None),
                                      name=GROUPS[g], kind=categories.kind_for(g), dre_group=g, is_active=True)
                s.add(created[g])
                s.flush()
            g = created[g]
        if twin is None:
            c.parent_id, c.code = g.id, categories._next_code(s, entity_id, g)
            c.dre_group, c.kind = g.dre_group, g.kind
            c.needs_review = False                         # reclassificar = conferir
            s.flush()
            moved += 1
            lines.append(f"\"{c.name}\" -> {g.name}")
            continue
        n_entries += s.execute(sql_update(Entry).where(Entry.category_id == c.id).values(category_id=twin.id)
                               .execution_options(synchronize_session=False)).rowcount
        for model in (CategoryRule, Item, Sale):
            s.execute(sql_update(model).where(model.category_id == c.id).values(category_id=twin.id)
                      .execution_options(synchronize_session=False))
        mine = s.scalar(select(Budget).where(Budget.category_id == c.id))
        if mine is not None:
            theirs = s.scalar(select(Budget).where(Budget.category_id == twin.id))
            if theirs is None:
                mine.category_id = twin.id
            else:                                          # os dois tinham orçamento: soma
                theirs.amount += mine.amount
                s.delete(mine)
        for m in s.scalars(select(ImportMap).where(ImportMap.kind == "itens", ImportMap.target == str(c.id))):
            m.target = str(twin.id)                        # reimportar o MCC continua achando o item
        s.flush()
        s.delete(c)
        s.flush()
        merged += 1
        lines.append(f"\"{c.name}\" juntada a {g.name} › {twin.name}")
    s.commit()
    if lines:
        audit.note(s, entity_id, "Reclassificou na DRE: " + "; ".join(lines))
    return Outcome(moved, merged, n_entries)
