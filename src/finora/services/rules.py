"""Regras automáticas de categoria: "descrição contém UBER -> Transporte".

Valem ao digitar a descrição de um lançamento novo, na conciliação do extrato (OFX) e na importação de planilha.
A busca ignora acentos e maiúsculas. Se mais de uma regra servir, ganha a de texto mais longo (mais específica).
"""
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.models import Category, CategoryRule, Contact, CostCenter, Entry
from finora.services import scope

KINDS = {"": "Receitas e despesas", "expense": "Só despesas", "income": "Só receitas"}


def norm(text: str) -> str:
    """'Café UBER*Trip' -> 'cafe uber*trip'."""
    text = unicodedata.normalize("NFKD", text or "")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).lower().split())


@dataclass(frozen=True)
class RuleView:
    id: int
    text: str
    kind: str
    category_id: int | None
    category: str | None
    contact_id: int | None
    contact: str | None
    cost_center_id: int | None
    cost_center: str | None
    description: str
    is_active: bool

    @property
    def summary(self) -> str:
        parts = [x for x in (self.category, self.contact, self.cost_center) if x]
        if self.description:
            parts.insert(0, f"“{self.description}”")
        return " · ".join(parts) or "—"


def _query(entity_id: int):
    return (select(CategoryRule, Category.name, Contact.name, CostCenter.name)
            .outerjoin(Category, Category.id == CategoryRule.category_id)
            .outerjoin(Contact, Contact.id == CategoryRule.contact_id)
            .outerjoin(CostCenter, CostCenter.id == CategoryRule.cost_center_id)
            .where(CategoryRule.entity_id == entity_id))


def _view(r: CategoryRule, cat, contact, cc) -> RuleView:
    return RuleView(r.id, r.text, r.kind or "", r.category_id, cat, r.contact_id, contact, r.cost_center_id, cc,
                    r.description or "", r.is_active)


def list_rules(s: Session, entity_id: int) -> list[RuleView]:
    rows = s.execute(_query(entity_id).order_by(func.lower(CategoryRule.text))).all()
    return [_view(*row) for row in rows]


def get(s: Session, rule_id: int) -> RuleView:
    r = s.get(CategoryRule, rule_id)
    if r is None:
        raise ValueError("Regra não encontrada.")
    row = s.execute(_query(r.entity_id).where(CategoryRule.id == rule_id)).one()
    return _view(*row)


def _check(s: Session, entity_id: int, text: str, kind: str, category_id, contact_id, cost_center_id,
           exclude_id: int | None = None) -> str:
    text = " ".join((text or "").split())
    if len(norm(text)) < 2:
        raise ValueError("Digite o texto a procurar (pelo menos 2 letras).")
    if len(text) > 80:
        raise ValueError("Texto longo demais (até 80 letras).")
    if kind not in KINDS:
        raise ValueError("Tipo inválido.")
    if not (category_id or contact_id or cost_center_id):
        raise ValueError("Escolha pelo menos a categoria, o contato ou o centro de custo.")
    if category_id:
        cat = s.get(Category, category_id)
        if not scope.category_visible(s, cat, entity_id):
            raise ValueError("Categoria inválida.")
        if kind and cat.kind != kind:
            raise ValueError("A categoria é de outro tipo (receita/despesa).")
    if contact_id and not scope.visible(s.get(Contact, contact_id), entity_id):
        raise ValueError("Contato inválido.")
    if cost_center_id and not scope.visible(s.get(CostCenter, cost_center_id), entity_id):
        raise ValueError("Centro de custo inválido.")
    for r in s.scalars(select(CategoryRule).where(CategoryRule.entity_id == entity_id)):
        if r.id != exclude_id and norm(r.text) == norm(text) and (r.kind or "") == kind:
            raise ValueError(f"Já existe uma regra para “{r.text}”.")
    return text


def create(s: Session, entity_id: int, *, text: str, kind: str = "", category_id: int | None = None,
           contact_id: int | None = None, cost_center_id: int | None = None, description: str = "") -> int:
    text = _check(s, entity_id, text, kind, category_id, contact_id, cost_center_id)
    r = CategoryRule(entity_id=entity_id, text=text, kind=kind, category_id=category_id, contact_id=contact_id,
                     cost_center_id=cost_center_id, description=(description or "").strip()[:200] or None,
                     is_active=True)
    s.add(r)
    s.commit()
    return r.id


def update(s: Session, rule_id: int, *, text: str, kind: str = "", category_id: int | None = None,
           contact_id: int | None = None, cost_center_id: int | None = None, description: str = "",
           is_active: bool = True) -> None:
    r = s.get(CategoryRule, rule_id)
    text = _check(s, r.entity_id, text, kind, category_id, contact_id, cost_center_id, exclude_id=rule_id)
    r.text, r.kind, r.category_id, r.contact_id, r.cost_center_id = text, kind, category_id, contact_id, cost_center_id
    r.description = (description or "").strip()[:200] or None
    r.is_active = is_active
    s.commit()


def delete(s: Session, rule_id: int) -> None:
    s.delete(s.get(CategoryRule, rule_id))
    s.commit()


def match(s: Session, entity_id: int, text: str, kind: str) -> RuleView | None:
    """A regra que serve para esse texto (descrição ou linha do extrato) e tipo; a mais específica ganha."""
    key = norm(text)
    if not key:
        return None
    rows = s.execute(_query(entity_id).where(CategoryRule.is_active.is_(True))).all()
    found = [_view(*row) for row in rows if norm(row[0].text) in key and (row[0].kind or "") in ("", kind)]
    if not found:
        return None
    best = max(found, key=lambda r: (len(norm(r.text)), bool(r.kind)))
    if best.category_id:                      # categoria de outro tipo não serve (regra para "as duas")
        cat = s.get(Category, best.category_id)
        if cat is not None and cat.kind != kind:
            best = RuleView(best.id, best.text, best.kind, None, None, best.contact_id, best.contact,
                            best.cost_center_id, best.cost_center, best.description, best.is_active)
    return best


def apply_to_existing(s: Session, entity_id: int) -> int:
    """Aplica as regras aos lançamentos SEM categoria (receitas e despesas). Não mexe em período fechado nem no
    que já tem categoria. Retorna quantos mudaram."""
    from finora.services import period_lock
    lock = period_lock.locked_through(s, entity_id)
    n = 0
    q = select(Entry).where(Entry.entity_id == entity_id, Entry.kind.in_(("income", "expense")),
                            Entry.category_id.is_(None))
    for e in s.scalars(q):
        if lock and e.competence_date <= lock:
            continue
        r = match(s, entity_id, e.description or "", e.kind)
        if r is None or not (r.category_id or r.contact_id or r.cost_center_id):
            continue
        e.category_id = r.category_id or e.category_id
        e.contact_id = e.contact_id or r.contact_id
        e.cost_center_id = e.cost_center_id or r.cost_center_id
        n += 1
    s.commit()
    return n
