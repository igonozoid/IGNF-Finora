"""O que cada entidade enxerga: o que é dela + o que foi marcado como compartilhado com todas.

Contatos e centros de custo: compartilhados um a um. Categorias: compartilha-se o grupo (com as subcategorias),
porque o grupo é a linha da DRE. Lançamentos, contas e saldos nunca são compartilhados.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from finora.models import Category, Contact, CostCenter


def contacts(entity_id: int):
    return or_(Contact.entity_id == entity_id, Contact.shared.is_(True))


def cost_centers(entity_id: int):
    return or_(CostCenter.entity_id == entity_id, CostCenter.shared.is_(True))


def categories(entity_id: int):
    """Da entidade, ou grupo compartilhado, ou subcategoria de um grupo compartilhado."""
    parent = aliased(Category)
    shared_groups = select(parent.id).where(parent.shared.is_(True), parent.parent_id.is_(None))
    return or_(Category.entity_id == entity_id, Category.shared.is_(True), Category.parent_id.in_(shared_groups))


def category_visible(s: Session, cat: Category | None, entity_id: int) -> bool:
    if cat is None:
        return False
    if cat.entity_id == entity_id or cat.shared:
        return True
    parent = s.get(Category, cat.parent_id) if cat.parent_id else None
    return bool(parent and parent.shared)


def visible(obj, entity_id: int) -> bool:
    """Contato ou centro de custo pode ser usado nesta entidade?"""
    return obj is not None and (obj.entity_id == entity_id or bool(obj.shared))
