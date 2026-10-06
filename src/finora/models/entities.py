from datetime import date
from decimal import Decimal
from sqlalchemy import ForeignKey, String, Numeric, Boolean, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="BRL")

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

class CostCenter(Base):
    __tablename__ = "cost_centers"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    name: Mapped[str] = mapped_column(String(80))
    budget: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

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
    # Contato ampliado (todos opcionais)
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))
    zip_code: Mapped[str | None] = mapped_column(String(9))
    address: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2))
    pix_key: Mapped[str | None] = mapped_column(String(120))
    bank_info: Mapped[str | None] = mapped_column(String(120))     # banco · agência · conta
    notes: Mapped[str | None] = mapped_column(String(1000))

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
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    description: Mapped[str | None] = mapped_column(String(200))
    document_no: Mapped[str | None] = mapped_column(String(40))
    competence_date: Mapped[date]
    due_date: Mapped[date]
    paid_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|paid|canceled
    installment: Mapped[str | None] = mapped_column(String(10))  # ex.: 4/12
    # Liga lançamentos de uma mesma recorrência/parcelamento (para "editar este e os próximos").
    series_id: Mapped[str | None] = mapped_column(String(32), index=True)

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
