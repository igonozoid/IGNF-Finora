"""Categorias em árvore (grupo > subcategoria), ligadas às linhas da DRE pessoal."""
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.models import Category
from finora.services import scope
from finora.services.dre import GROUPS


@dataclass
class CategoryView:
    id: int
    parent_id: int | None
    code: str
    name: str
    kind: str
    dre_group: str | None
    is_active: bool
    children: list["CategoryView"] = field(default_factory=list)
    shared: bool = False             # grupo compartilhado com todas as entidades
    own: bool = True                 # criada nesta entidade (False = veio compartilhada de outra)

    @property
    def dre_label(self) -> str:
        return GROUPS.get(self.dre_group, "—")


def kind_for(dre_group: str) -> str:
    from finora.services.dre import INCOME_GROUPS
    return "income" if dre_group in INCOME_GROUPS else "expense"


def _code_key(code: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in code.split("."))


def model_groups(s: Session, entity_id: int) -> dict[str, str]:
    """Linhas da DRE do modelo da entidade (pessoal ou empresa)."""
    from finora.models import Entity
    from finora.services import dre
    e = s.get(Entity, entity_id)
    return dre.groups_for(getattr(e, "dre_model", None))


def tree(s: Session, entity_id: int, include_inactive: bool = False) -> list[CategoryView]:
    """Grupos na ordem das linhas da DRE; dentro de cada grupo, pelo código."""
    q = select(Category).where(scope.categories(entity_id))
    if not include_inactive:
        q = q.where(Category.is_active)
    rows = [CategoryView(c.id, c.parent_id, c.code, c.name, c.kind, c.dre_group, c.is_active, shared=bool(c.shared),
                         own=c.entity_id == entity_id) for c in s.scalars(q)]
    by_id = {r.id: r for r in rows}
    roots = []
    for r in rows:
        if r.parent_id is None:
            roots.append(r)
        elif r.parent_id in by_id:  # subcategoria de grupo filtrado (inativo) não aparece
            by_id[r.parent_id].children.append(r)
    order = list(model_groups(s, entity_id)) + [g for g in GROUPS if g not in model_groups(s, entity_id)]
    roots.sort(key=lambda r: (order.index(r.dre_group) if r.dre_group in order else len(order), _code_key(r.code)))
    for r in roots:
        r.children.sort(key=lambda c: _code_key(c.code))
    return roots


def choices(s: Session, entity_id: int, kind: str) -> list[tuple[int, str]]:
    """Categorias que podem ir num lançamento do tipo `kind`: subcategorias ativas, ou o próprio
    grupo quando ele não tem subcategorias. Rótulo no formato "Grupo › Subcategoria"."""
    out = []
    for g in tree(s, entity_id):
        if g.kind != kind:
            continue
        if g.children:
            out += [(c.id, f"{g.name} › {c.name}") for c in g.children]
        else:
            out.append((g.id, g.name))
    return out


def groups(s: Session, entity_id: int) -> list[CategoryView]:
    """Categorias principais ativas (possíveis 'pais')."""
    return [r for r in tree(s, entity_id) if r.parent_id is None]


def _next_code(s: Session, entity_id: int, parent: Category | None) -> str:
    if parent:                       # dentro de um grupo (inclusive compartilhado): numera entre os irmãos
        q = select(Category.code).where(Category.parent_id == parent.id)
    else:
        q = select(Category.code).where(Category.entity_id == entity_id, Category.parent_id.is_(None))
    last = max((_code_key(c)[-1] for c in s.scalars(q)), default=0)
    return f"{parent.code}.{last + 1}" if parent else str(last + 1)


def _check_name(s: Session, entity_id: int, name: str, parent_id: int | None, exclude_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Dê um nome para a categoria.")
    q = select(Category.id).where(scope.categories(entity_id), func.lower(Category.name) == name.lower())
    q = q.where(Category.parent_id == parent_id) if parent_id else q.where(Category.parent_id.is_(None))
    if exclude_id is not None:
        q = q.where(Category.id != exclude_id)
    if s.scalar(q) is not None:
        raise ValueError(f"Já existe \"{name}\" neste grupo.")
    return name


def convert_model(s: Session, entity_id: int, model: str) -> int:
    """Troca o modelo da DRE da entidade: cada grupo desta entidade vai para a linha equivalente do outro modelo
    (ex.: Moradia -> Despesas administrativas). Sem commit. Devolve quantos grupos mudaram de linha."""
    from finora.services import dre
    if model not in dre.MODELS:
        raise ValueError("Modelo de DRE inválido.")
    mapping = dre.TO_BUSINESS if model == "business" else dre.TO_PERSONAL
    n = 0
    for c in s.scalars(select(Category).where(Category.entity_id == entity_id)):
        new = mapping.get(c.dre_group or "")
        if new and new != c.dre_group:
            c.dre_group, c.kind = new, kind_for(new)
            n += 1 if c.parent_id is None else 0
    return n


def create(s: Session, entity_id: int, *, name: str, parent_id: int | None = None,
           dre_group: str | None = None, shared: bool = False) -> int:
    """Subcategoria herda tipo e linha da DRE do grupo; grupo novo precisa de `dre_group`."""
    parent = s.get(Category, parent_id) if parent_id else None
    if parent is not None and parent.parent_id is not None:
        raise ValueError("Só dá para criar subcategorias dentro de um grupo principal.")
    name = _check_name(s, entity_id, name, parent_id)
    if parent is not None:
        dre_group, kind = parent.dre_group, parent.kind
    else:
        if dre_group not in model_groups(s, entity_id):
            raise ValueError("Escolha em qual linha da DRE esta categoria aparece.")
        kind = kind_for(dre_group)
    c = Category(entity_id=entity_id, parent_id=parent_id, code=_next_code(s, entity_id, parent), name=name,
                 kind=kind, dre_group=dre_group, is_active=True, shared=bool(shared) and parent is None)
    s.add(c)
    s.commit()
    return c.id


def update(s: Session, category_id: int, *, name: str, dre_group: str | None = None,
           shared: bool | None = None) -> None:
    """Renomeia. Num grupo principal, trocar a linha da DRE vale também para as subcategorias.
    `shared` (só grupos): compartilhar o grupo, com as subcategorias, com todas as entidades."""
    c = s.get(Category, category_id)
    c.name = _check_name(s, c.entity_id, name, c.parent_id, exclude_id=c.id)
    if shared is not None and c.parent_id is None:
        c.shared = shared
    if c.parent_id is None and dre_group and dre_group != c.dre_group:
        if dre_group not in GROUPS:
            raise ValueError("Linha da DRE inválida.")
        c.dre_group, c.kind = dre_group, kind_for(dre_group)
        for child in s.scalars(select(Category).where(Category.parent_id == c.id)):
            child.dre_group, child.kind = c.dre_group, c.kind
    s.commit()


def set_active(s: Session, category_id: int, active: bool) -> None:
    """Inativar um grupo inativa as subcategorias; ativar uma subcategoria reativa o grupo."""
    c = s.get(Category, category_id)
    c.is_active = active
    if not active:
        for child in s.scalars(select(Category).where(Category.parent_id == c.id)):
            child.is_active = False
    elif c.parent_id is not None:
        s.get(Category, c.parent_id).is_active = True
    s.commit()
