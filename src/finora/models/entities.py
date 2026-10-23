from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    # Fechamento de período: lançamentos com competência até esta data não mudam mais (None = aberto).
    locked_through: Mapped[date | None]
    person_type: Mapped[str] = mapped_column(String(2), default="PF")      # PF | PJ
    document: Mapped[str | None] = mapped_column(String(20))                # CPF/CNPJ (só dígitos)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Dados que aparecem no cabeçalho do recibo e dos relatórios (todos opcionais)
    document2: Mapped[str | None] = mapped_column(String(30))               # inscrição estadual/municipal
    address: Mapped[str | None] = mapped_column(String(200))
    address2: Mapped[str | None] = mapped_column(String(80))                # complemento
    district: Mapped[str | None] = mapped_column(String(80))                # bairro
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2))
    zip_code: Mapped[str | None] = mapped_column(String(9))
    country: Mapped[str | None] = mapped_column(String(60))                 # vazio = Brasil
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(120))
    logo: Mapped[bytes | None] = mapped_column(LargeBinary(length=2_000_000), deferred=True)   # PNG, até 512 px
    # Usa centro de custo (como no MCC, por conta controle): desligado, o campo some do lançamento.
    uses_cost_centers: Mapped[bool] = mapped_column(Boolean, default=True)
    # Modelo da DRE: personal (Moradia, Alimentação…) ou business (Receita bruta, Custos, Lucro…); ver services/dre
    dre_model: Mapped[str] = mapped_column(String(10), default="personal", server_default="personal")


class EntityModule(Base):
    """Módulo ligado numa entidade (estoque, vendas, produção, rural…; ver services/modules)."""
    __tablename__ = "entity_modules"
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    module: Mapped[str] = mapped_column(String(20), primary_key=True)

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), default="bank")  # cash|bank|card|investment
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Só para cartão de crédito (kind="card"): dia de fechamento e de vencimento da fatura, e limite.
    closing_day: Mapped[int | None] = mapped_column(Integer)
    due_day: Mapped[int | None] = mapped_column(Integer)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    # Compartilhada com todas as entidades (no MCC: conta sem conta controle). O saldo soma os lançamentos de todas.
    shared: Mapped[bool] = mapped_column(Boolean, default=False)

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))  # income|expense
    dre_group: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Compartilhada com todas as entidades (vale para o grupo e as subcategorias dele)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)

class CostCenter(Base):
    __tablename__ = "cost_centers"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    name: Mapped[str] = mapped_column(String(80))
    budget: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))         # orçamento mensal de despesa
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)      # aparece em todas as entidades
    # Para que tipo de lançamento ele vale (como no MCC: centro de custo / centro de lucro) e a projeção mensal
    # de receita (o "orçamento" das receitas).
    applies_expense: Mapped[bool] = mapped_column(Boolean, default=True)
    applies_income: Mapped[bool] = mapped_column(Boolean, default=True)
    projection: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))

class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    person_type: Mapped[str] = mapped_column(String(2))  # PF|PJ
    document: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_employee: Mapped[bool] = mapped_column(Boolean, default=False)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)      # aparece em todas as entidades
    # Criado sozinho (ex.: importação do MCC a partir de um nome solto): confira e salve para tirar a marca
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # Contato ampliado (todos opcionais)
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))
    zip_code: Mapped[str | None] = mapped_column(String(9))
    address: Mapped[str | None] = mapped_column(String(200))
    district: Mapped[str | None] = mapped_column(String(80))              # bairro
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2))
    document2: Mapped[str | None] = mapped_column(String(30))             # RG (PF) ou inscrição estadual (PJ)
    contact_person: Mapped[str | None] = mapped_column(String(80))        # com quem falar
    pix_key: Mapped[str | None] = mapped_column(String(120))
    bank_name: Mapped[str | None] = mapped_column(String(60))
    bank_branch: Mapped[str | None] = mapped_column(String(20))           # agência
    bank_account: Mapped[str | None] = mapped_column(String(30))
    bank_holder: Mapped[str | None] = mapped_column(String(120))          # titular da conta
    notes: Mapped[str | None] = mapped_column(String(1000))
    # Crédito (como no cadastro de clientes do IgnControl; edições pagas)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))     # quanto pode ficar devendo
    credit_checked_on: Mapped[date | None]                                  # última consulta (SPC, Serasa…)
    credit_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_pending_where: Mapped[str | None] = mapped_column(String(80))    # onde está a pendência
    mother_name: Mapped[str | None] = mapped_column(String(150))            # só pessoa física
    rating: Mapped[str | None] = mapped_column(String(10))                  # otimo | bom | regular | ruim
    purchase_frequency: Mapped[str | None] = mapped_column(String(10))      # semanal | quinzenal | mensal…

class Entry(Base):
    __tablename__ = "entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    kind: Mapped[str] = mapped_column(String(10))  # income|expense|transfer
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    dest_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    cost_center_id: Mapped[int | None] = mapped_column(ForeignKey("cost_centers.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))                  # na moeda da conta
    # Pago com valor diferente do previsto (juros, multa, desconto): o previsto fica aqui; `amount` é o pago.
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    # Valor na moeda principal, pela cotação da data (é o que os relatórios somam). Calculado sozinho ao gravar.
    base_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    # Transferência entre contas de moedas diferentes: quanto chega no destino (na moeda dele).
    dest_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    description: Mapped[str | None] = mapped_column(String(200))
    document_no: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)                         # observações (como no MCC)
    competence_date: Mapped[date]
    due_date: Mapped[date]
    paid_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|paid|canceled
    installment: Mapped[str | None] = mapped_column(String(10))  # ex.: 4/12
    # Liga lançamentos de uma mesma recorrência/parcelamento (para "editar este e os próximos").
    series_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # Lixeira (services/trash): excluído não sai do banco; some das telas e dá para restaurar.
    deleted_at: Mapped[datetime | None] = mapped_column(index=True)
    deleted_by: Mapped[str | None] = mapped_column(String(80))

class CategoryRule(Base):
    """Regra automática: descrição (ou texto do extrato) contém `text` -> categoria, contato e centro de custo."""
    __tablename__ = "category_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    text: Mapped[str] = mapped_column(String(80))                 # o que procurar (sem diferença de acento/maiúscula)
    kind: Mapped[str] = mapped_column(String(10), default="")     # income|expense|"" (as duas)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    cost_center_id: Mapped[int | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(String(200))  # descrição para o lançamento (vazio = mantém)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Item(Base):
    """Produto, insumo ou material (módulo Estoque). Saldo e custo médio saem dos movimentos (StockMove)."""
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    code: Mapped[str | None] = mapped_column(String(30))                  # código interno ou de barras
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="product")      # product|input|material|produced
    unit: Mapped[str] = mapped_column(String(10), default="un")
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(15, 3))     # aviso de estoque baixo
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class StockLocation(Base):
    """Onde o item fica: depósito, galpão, almoxarifado, apiário…"""
    __tablename__ = "stock_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class StockMove(Base):
    """Movimento de estoque. Quantidade com sinal (+ entrou, − saiu). Na entrada, unit_cost é o custo pago."""
    __tablename__ = "stock_moves"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("stock_locations.id"))
    day: Mapped[date]
    kind: Mapped[str] = mapped_column(String(12))        # in|out|loss|adjust|transfer|sale|prod_in|prod_out
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id", ondelete="SET NULL"))   # compra/venda
    transfer_id: Mapped[str | None] = mapped_column(String(32), index=True)   # liga a saída e a entrada
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    production_id: Mapped[int | None] = mapped_column(ForeignKey("productions.id", ondelete="CASCADE"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("farm_activities.id", ondelete="CASCADE"), index=True)
    herd_event_id: Mapped[int | None] = mapped_column(ForeignKey("herd_events.id", ondelete="CASCADE"), index=True)
    document_no: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(String(300))

class Sale(Base):
    """Pedido de venda (módulo Vendas). Confirmado: baixa o estoque e gera as contas a receber (parcelas)."""
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    number: Mapped[int]                                                    # nº do pedido na entidade
    day: Mapped[date]
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10), default="sale")         # sale|donation|bonus
    status: Mapped[str] = mapped_column(String(10), default="quote")      # quote|confirmed|canceled
    discount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    freight: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))   # frete cobrado do cliente
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    payment: Mapped[str | None] = mapped_column(String(20))               # Pix, boleto, cartão, dinheiro…
    installments: Mapped[int] = mapped_column(default=1)
    first_due: Mapped[date | None]
    paid_now: Mapped[bool] = mapped_column(Boolean, default=False)        # à vista, já recebido
    location_id: Mapped[int | None] = mapped_column(ForeignKey("stock_locations.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    series_id: Mapped[str | None] = mapped_column(String(32))             # parcelas a receber geradas
    notes: Mapped[str | None] = mapped_column(String(300))

class SaleItem(Base):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))     # custo médio na confirmação (margem)

class Production(Base):
    """Lote de produção (módulo Produção): insumos que saem do estoque viram produtos que entram, com custo.
    Em andamento não mexe no estoque; concluído grava os movimentos prod_out/prod_in."""
    __tablename__ = "productions"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    number: Mapped[int]                                                    # nº do lote na entidade
    name: Mapped[str] = mapped_column(String(80))                          # "Azeite safra 2026 – lote 3"
    day: Mapped[date]                                                      # data da produção (dos movimentos)
    status: Mapped[str] = mapped_column(String(10), default="open")       # open|done
    location_id: Mapped[int | None] = mapped_column(ForeignKey("stock_locations.id"))
    extra_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))   # mão de obra, energia…
    notes: Mapped[str | None] = mapped_column(String(300))

class ProductionLine(Base):
    """Insumo usado (role="in") ou produto obtido (role="out"). share = % do custo do lote para esse produto."""
    __tablename__ = "production_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    production_id: Mapped[int] = mapped_column(ForeignKey("productions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(3))                           # in|out
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    share: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))           # só nos produtos; vazio = rateio pela qtd.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))     # gravado ao concluir

class Farm(Base):
    """Propriedade rural (fazenda, sítio, chácara) do módulo Agricultura."""
    __tablename__ = "farms"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class FarmArea(Base):
    """Área da propriedade: talhão, pomar, pasto/piquete, apiário… com cultura e tamanho (hectares)."""
    __tablename__ = "farm_areas"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(12), default="field")       # field|orchard|pasture|apiary|other
    crop: Mapped[str | None] = mapped_column(String(80))                 # cultura: "Oliveira arbequina", "Tifton"
    hectares: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    units: Mapped[int | None]                                            # nº de plantas, colmeias…
    notes: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class FarmActivity(Base):
    """Atividade numa área (plantio, adubação, poda, colheita…) ou ocorrência (geada, praga). Os insumos usados
    saem do estoque (StockMove com activity_id); na colheita, o produto entra."""
    __tablename__ = "farm_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("farm_areas.id"), index=True)
    day: Mapped[date]
    kind: Mapped[str] = mapped_column(String(12))
    description: Mapped[str | None] = mapped_column(String(200))
    other_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))   # mão de obra, máquina…
    inputs_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))  # gravado: insumos usados
    harvest_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0")) # custo que foi p/ colheita
    location_id: Mapped[int | None] = mapped_column(ForeignKey("stock_locations.id"))
    notes: Mapped[str | None] = mapped_column(String(300))

class HerdLot(Base):
    """Lote de animais (módulo Pecuária): a contagem de cabeças sai dos registros (HerdEvent)."""
    __tablename__ = "herd_lots"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))                          # "Vacas de cria", "Recria 2026"
    species: Mapped[str] = mapped_column(String(12), default="cattle")    # cattle|sheep|goat|horse|pig|poultry|other
    category: Mapped[str | None] = mapped_column(String(40))               # vaca, novilha, bezerro, boi…
    area_id: Mapped[int | None] = mapped_column(ForeignKey("farm_areas.id", ondelete="SET NULL"))   # piquete atual
    notes: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class HerdEvent(Base):
    """Registro do lote: nascimento, compra, venda, morte, transferência entre lotes, troca de piquete,
    pesagem, sanidade (vacina/remédio), alimentação, ocorrência. `heads` tem sinal (+ entrou, − saiu)."""
    __tablename__ = "herd_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("herd_lots.id"), index=True)
    day: Mapped[date]
    kind: Mapped[str] = mapped_column(String(12))
    heads: Mapped[int] = mapped_column(default=0)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))         # peso médio por cabeça (kg)
    value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))        # compra/venda
    other_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))   # veterinário, frete…
    inputs_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))  # gravado: insumos usados
    area_id: Mapped[int | None] = mapped_column(ForeignKey("farm_areas.id", ondelete="SET NULL"))  # piquete destino
    other_lot_id: Mapped[int | None] = mapped_column(ForeignKey("herd_lots.id"))                     # transferência
    transfer_id: Mapped[str | None] = mapped_column(String(32), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id", ondelete="SET NULL"))     # a pagar/receber
    location_id: Mapped[int | None] = mapped_column(ForeignKey("stock_locations.id"))
    description: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(300))

class Currency(Base):
    """Moeda que não está na lista do Finora, cadastrada pela pessoa (vale para todas as entidades)."""
    __tablename__ = "currencies"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)   # código ISO 4217 (3 letras)
    symbol: Mapped[str] = mapped_column(String(6))
    name: Mapped[str] = mapped_column(String(60))

class Goal(Base):
    """Meta (reserva, viagem…): o progresso é o saldo de uma conta ou o valor guardado informado."""
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    target: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    due_date: Mapped[date | None]
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    saved: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class BankLine(Base):
    """Linha de extrato importada (OFX). Fica guardada para a conciliação e para não importar duas vezes."""
    __tablename__ = "bank_lines"
    __table_args__ = (UniqueConstraint("account_id", "fitid", name="uq_bank_line"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    fitid: Mapped[str] = mapped_column(String(80))          # identificador da transação dado pelo banco
    posted: Mapped[date]
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))  # + entrou, − saiu
    memo: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|matched|ignored
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id", ondelete="SET NULL"))

class Budget(Base):
    """Orçamento mensal de uma categoria (quanto você pretende gastar nela por mês)."""
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("entity_id", "category_id", name="uq_budget_category"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))

class Attachment(Base):
    """Comprovante anexado a um lançamento (foto, PDF…). O arquivo fica dentro do banco: vai junto no backup
    e, no futuro, no modo rede/nuvem."""
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    added: Mapped[date]
    data: Mapped[bytes] = mapped_column(LargeBinary(length=16_000_000), deferred=True)   # MySQL: MEDIUMBLOB

class ExchangeRate(Base):
    """Cotação: quanto vale 1 unidade de `currency` na moeda principal, a partir de `day`."""
    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("entity_id", "currency", "day", name="uq_rate_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    currency: Mapped[str] = mapped_column(String(3))
    day: Mapped[date]
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    source: Mapped[str] = mapped_column(String(20), default="manual")     # manual | bcb (PTAX)


class ImportMap(Base):
    """De onde veio cada registro importado (ex.: lançamento 123 do MCC -> lançamento 456 do Finora). É o que permite
    reimportar atualizando em vez de duplicar."""
    __tablename__ = "import_map"
    __table_args__ = (UniqueConstraint("source", "kind", "source_id", name="uq_import_map"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))           # "mcc"
    kind: Mapped[str] = mapped_column(String(20))             # empresas, contas, lancamentos, grupo…
    source_id: Mapped[str] = mapped_column(String(160))
    target: Mapped[str] = mapped_column(String(64))           # id no Finora (ou a série, no caso de "grupo")


class User(Base):
    """Quem usa o app. Sem senha e sendo o único usuário, o app abre direto (como na edição Free)."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(120), unique=True)      # login
    password_hash: Mapped[str | None] = mapped_column(String(200))           # None = sem senha
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[datetime] = mapped_column(DateTime)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class UserEntity(Base):
    """Quais entidades cada usuário pode abrir."""
    __tablename__ = "user_entities"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)


class Permission(Base):
    """Nível de acesso de um usuário a um módulo numa entidade: none | read | full."""
    __tablename__ = "permissions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    module: Mapped[str] = mapped_column(String(20), primary_key=True)
    level: Mapped[str] = mapped_column(String(10), default="full")


class AuditLog(Base):
    """Histórico de alterações: quem fez o quê, quando, com o antes e o depois."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    user_name: Mapped[str] = mapped_column(String(120), default="")
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    table_name: Mapped[str] = mapped_column(String(40))
    row_id: Mapped[int | None]
    action: Mapped[str] = mapped_column(String(10))                    # create | update | delete
    summary: Mapped[str] = mapped_column(String(300))
    changes: Mapped[str | None] = mapped_column(Text)                  # JSON {campo: [antes, depois]}
