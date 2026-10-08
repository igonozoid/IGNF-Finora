"""Histórico de alterações (auditoria, do IgnControl): toda gravação nas tabelas importantes vira uma linha com
quem fez, quando, o resumo e o antes/depois — automático, por um gancho no banco (não depende de cada tela).
"""
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from finora.core import money
from finora.core.current import current
from finora.models import (
    Account, Attachment, AuditLog, Budget, Category, CategoryRule, Contact, CostCenter, Entity, Entry, ExchangeRate,
    Goal, Permission, User,
)

# modelo -> (nome no texto, função que descreve o registro)
LABELS = {
    Entry: ("lançamento", lambda o: f"\"{o.description or ''}\" — {money.fmt(o.amount or 0)}"),
    Account: ("conta", lambda o: f"\"{o.name}\""),
    Category: ("categoria", lambda o: f"\"{o.name}\""),
    Contact: ("contato", lambda o: f"\"{o.name}\""),
    CostCenter: ("centro de custo", lambda o: f"\"{o.name}\""),
    Budget: ("orçamento", lambda o: f"da categoria nº {o.category_id} — {money.fmt(o.amount or 0)}"),
    ExchangeRate: ("cotação", lambda o: f"{o.currency} de {o.day:%d/%m/%Y}" if o.day else o.currency),
    Entity: ("entidade", lambda o: f"\"{o.name}\""),
    User: ("usuário", lambda o: f"\"{o.name}\""),
    Permission: ("permissão", lambda o: f"{o.module} do usuário nº {o.user_id}"),
    CategoryRule: ("regra", lambda o: f"\"{o.text}\""),
    Goal: ("meta", lambda o: f"\"{o.name}\" — {money.fmt(o.target or 0)}"),
    Attachment: ("comprovante", lambda o: f"\"{o.filename}\" do lançamento nº {o.entry_id}"),
}
FIELDS = {"description": "descrição", "amount": "valor", "due_date": "vencimento", "competence_date": "data",
          "paid_date": "pagamento", "status": "situação", "account_id": "conta", "dest_account_id": "conta destino",
          "category_id": "categoria", "contact_id": "contato", "cost_center_id": "centro de custo",
          "document_no": "documento", "name": "nome", "kind": "tipo", "opening_balance": "saldo inicial",
          "is_active": "ativo", "budget": "orçamento", "rate": "cotação", "currency": "moeda", "level": "nível",
          "email": "e-mail", "is_admin": "administrador", "password_hash": "senha", "locked_through": "fechamento",
          "dest_amount": "valor que chega"}
SKIP = {"base_amount", "data", "id", "last_login", "series_id", "installment", "created"}
SECRET = {"password_hash"}
ACTIONS = {"create": "Criou", "update": "Alterou", "delete": "Excluiu"}


@dataclass(frozen=True)
class AuditView:
    id: int
    at: datetime
    user: str
    action: str
    table: str
    summary: str
    changes: dict


def _plain(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _columns(obj) -> list[str]:
    return [c.key for c in inspect(obj).mapper.column_attrs if c.key not in SKIP]


def _summary(obj, action: str, changes: dict) -> str:
    noun, describe = LABELS[type(obj)]
    try:
        what = describe(obj)
    except Exception:          # descrição nunca derruba a gravação
        what = ""
    if isinstance(obj, Entry) and action == "update" and set(changes) <= {"status", "paid_date"}:
        if obj.status == "paid":
            return f"Baixou pagamento {what}"
        if changes.get("status", [None])[0] == "paid":
            return f"Desfez pagamento {what}"
    if isinstance(obj, Entry) and action == "update" and "deleted_at" in changes:
        return f"{'Restaurou da lixeira' if obj.deleted_at is None else 'Mandou para a lixeira'} {noun} {what}"[:300]
    if isinstance(obj, Entity) and action == "update" and set(changes) == {"locked_through"}:
        return (f"Fechou o período até {obj.locked_through:%d/%m/%Y}" if obj.locked_through
                else "Reabriu o período")
    if isinstance(obj, User) and action == "update" and set(changes) == {"password_hash"}:
        return f"Trocou a senha de {what}"
    text = f"{ACTIONS[action]} {noun} {what}".strip()
    if action == "update" and changes:
        text += ": " + ", ".join(FIELDS.get(k, k) for k in changes)
    return text[:300]


@event.listens_for(Session, "before_flush")
def _collect(s: Session, _ctx, _instances) -> None:
    pending = s.info.setdefault("audit_pending", [])
    for obj in s.new:
        if type(obj) in LABELS:
            pending.append((obj, "create", {k: [None, _plain(getattr(obj, k))] for k in _columns(obj)
                                            if getattr(obj, k) is not None and k not in SECRET}))
    for obj in s.dirty:
        if type(obj) not in LABELS or not s.is_modified(obj):
            continue
        state = inspect(obj)
        changes = {}
        for key in _columns(obj):
            hist = state.attrs[key].history
            if hist.has_changes():
                old = hist.deleted[0] if hist.deleted else None
                new = hist.added[0] if hist.added else None
                if old == new:
                    continue
                changes[key] = ["***", "***"] if key in SECRET else [_plain(old), _plain(new)]
        if changes:
            pending.append((obj, "update", changes))
    for obj in s.deleted:
        if type(obj) in LABELS:
            pending.append((obj, "delete", {k: [_plain(getattr(obj, k)), None] for k in _columns(obj)
                                            if getattr(obj, k) is not None and k not in SECRET}))


@event.listens_for(Session, "after_flush")
def _write(s: Session, _ctx) -> None:
    pending = s.info.pop("audit_pending", [])
    if not pending:
        return
    now = datetime.now().replace(microsecond=0)
    rows = []
    for obj, action, changes in pending:
        entity_id = obj.id if isinstance(obj, Entity) else getattr(obj, "entity_id", None)
        if isinstance(obj, Entity) and action == "delete":
            entity_id = None
        rows.append(dict(at=now, user_id=current.user_id, user_name=current.user_name, entity_id=entity_id,
                         table_name=obj.__tablename__, row_id=getattr(obj, "id", None), action=action,
                         summary=_summary(obj, action, changes),
                         changes=json.dumps(changes, ensure_ascii=False, default=str) if changes else None))
    s.connection().execute(AuditLog.__table__.insert(), rows)


def note(s: Session, entity_id: int | None, summary: str) -> None:
    """Registro manual de uma ação que não é uma gravação simples (ex.: importou um extrato com N linhas)."""
    s.add(AuditLog(at=datetime.now().replace(microsecond=0), user_id=current.user_id, user_name=current.user_name,
                   entity_id=entity_id, table_name="", row_id=None, action="note", summary=summary[:300]))
    s.commit()


def list_log(s: Session, entity_id: int | None = None, search: str = "", limit: int = 300,
             first: date | None = None, last: date | None = None) -> list[AuditView]:
    q = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit)
    if entity_id is not None:
        q = q.where((AuditLog.entity_id == entity_id) | AuditLog.entity_id.is_(None))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        from sqlalchemy import func
        q = q.where(func.lower(AuditLog.summary).like(like) | func.lower(AuditLog.user_name).like(like))
    if first:
        q = q.where(AuditLog.at >= datetime.combine(first, datetime.min.time()))
    if last:
        q = q.where(AuditLog.at <= datetime.combine(last, datetime.max.time()))
    return [AuditView(a.id, a.at, a.user_name or "—", a.action, a.table_name, a.summary,
                      json.loads(a.changes) if a.changes else {}) for a in s.scalars(q)]
