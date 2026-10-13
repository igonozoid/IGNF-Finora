"""Módulos opcionais, ligados por entidade em Configurações › Módulos (escritório não vê vendas; fazenda vê rural).

Um módulo pode depender de outro (vendas usa o estoque): ligar puxa as dependências; desligar desliga quem
depende dele. Desligar não apaga nada: os dados ficam guardados e voltam ao ligar de novo.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finora.models import EntityModule


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    icon: str
    description: str
    requires: tuple[str, ...] = ()
    ready: bool = False              # já construído (os outros aparecem como "em breve")


CATALOG = {m.key: m for m in (
    Module("stock", "Produtos e estoque", "fa6s.boxes-stacked",
           "Produtos, insumos e materiais de uso interno: entradas, saídas, perdas, inventário, estoque mínimo e "
           "custo médio. Serve também só para o material do escritório.", ready=True),
    Module("sales", "Vendas", "fa6s.cart-shopping",
           "Pedidos de venda: cliente, itens, desconto e parcelas. Geram as contas a receber e baixam o estoque.",
           ("stock",), ready=True),
    Module("production", "Produção", "fa6s.industry",
           "Lotes de produção que transformam insumos em produtos (ex.: azeitona em azeite, mel em potes), com "
           "rendimento e custo por unidade.", ("stock",), ready=True),
    Module("rural", "Rural: agricultura", "fa6s.seedling",
           "Propriedades e áreas (talhões, piquetes, apiários), atividades como poda, adubação e colheita, consumo "
           "de insumos e custo por área.", ("stock",), ready=True),
    Module("livestock", "Rural: pecuária", "fa6s.cow",
           "Rebanho por lote: nascimentos, compras, vendas, mortes, troca de piquete, vacinas e pesagens.",
           ("rural",), ready=True),
)}


def enabled(s: Session, entity_id: int) -> set[str]:
    return set(s.scalars(select(EntityModule.module).where(EntityModule.entity_id == entity_id)))


def is_on(s: Session, entity_id: int, key: str) -> bool:
    return key in enabled(s, entity_id)


def _with_requirements(keys: set[str]) -> set[str]:
    out = set(keys)
    changed = True
    while changed:
        changed = False
        for k in list(out):
            for r in CATALOG[k].requires:
                if r not in out:
                    out.add(r)
                    changed = True
    return out


def _dependents(key: str) -> set[str]:
    out = {key}
    changed = True
    while changed:
        changed = False
        for m in CATALOG.values():
            if m.key not in out and any(r in out for r in m.requires):
                out.add(m.key)
                changed = True
    return out


def set_enabled(s: Session, entity_id: int, key: str, on: bool) -> set[str]:
    """Liga ou desliga (com dependências). Devolve o conjunto final de módulos ligados."""
    if key not in CATALOG:
        raise ValueError("Módulo desconhecido.")
    current = enabled(s, entity_id)
    target = _with_requirements(current | {key}) if on else current - _dependents(key)
    for k in target - current:
        s.add(EntityModule(entity_id=entity_id, module=k))
    for k in current - target:
        s.delete(s.get(EntityModule, (entity_id, k)))
    s.commit()
    return target
