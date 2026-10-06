"""Fechamento de período (do IgnControl): depois de conferir um mês, você o "fecha" e os lançamentos com
competência até aquela data não podem mais ser criados, alterados nem excluídos — a DRE e os relatórios do
passado ficam como estavam.

Pagar depois uma conta antiga continua permitido (o pagamento acontece numa data aberta). A trava fica num
gancho before_flush: vale para qualquer caminho que grave lançamentos, não só para as telas.
"""
from datetime import date

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from finora.models import Entity, Entry

# mudar só isso não mexe na competência; vale se o pagamento (antes e depois) estiver em data aberta
_PAYMENT_ATTRS = {"status", "paid_date", "base_amount"}


class PeriodLockedError(ValueError):
    pass


def locked_through(s: Session, entity_id: int) -> date | None:
    e = s.get(Entity, entity_id)
    return e.locked_through if e else None


def is_locked(s: Session, entity_id: int, day: date | None) -> bool:
    lock = locked_through(s, entity_id)
    return bool(lock and day and day <= lock)


def set_lock(s: Session, entity_id: int, day: date | None) -> None:
    """Fecha até `day` (inclusive). None reabre tudo."""
    e = s.get(Entity, entity_id)
    if day is not None and day > date.today():
        raise ValueError("Só dá para fechar períodos que já passaram.")
    e.locked_through = day
    s.commit()


def _message(lock: date) -> str:
    return (f"O período até {lock:%d/%m/%Y} está fechado: lançamentos dessa época não podem ser criados, "
            "alterados nem excluídos. Para mudar, reabra em Configurações › Fechamento de período.")


def _old(state, attr: str):
    hist = state.attrs[attr].history
    return hist.deleted[0] if hist.deleted else getattr(state.object, attr)


@event.listens_for(Session, "before_flush")
def _guard(s: Session, _ctx, _instances) -> None:
    locks: dict[int, date | None] = {}

    def lock_for(entity_id: int) -> date | None:
        if entity_id not in locks:
            e = s.get(Entity, entity_id)
            locks[entity_id] = e.locked_through if e else None
        return locks[entity_id]

    def closed(lock: date, *days) -> bool:
        return any(d is not None and d <= lock for d in days)

    for obj in s.new:
        if isinstance(obj, Entry) and obj.entity_id and (lock := lock_for(obj.entity_id)):
            if closed(lock, obj.competence_date):
                raise PeriodLockedError(_message(lock))
    for obj in s.deleted:
        if isinstance(obj, Entry) and (lock := lock_for(obj.entity_id)):
            if closed(lock, obj.competence_date):
                raise PeriodLockedError(_message(lock))
    for obj in s.dirty:
        if not isinstance(obj, Entry) or not s.is_modified(obj) or not (lock := lock_for(obj.entity_id)):
            continue
        state = inspect(obj)
        changed = {a.key for a in state.attrs if a.history.has_changes()}
        if not changed or changed == {"base_amount"}:   # recálculo de câmbio (cotação nova em data aberta)
            continue
        if changed <= _PAYMENT_ATTRS:
            # pagar/desfazer pagamento de algo antigo: ok se as datas de pagamento estão em período aberto
            if closed(lock, _old(state, "paid_date"), obj.paid_date):
                raise PeriodLockedError(_message(lock))
            continue
        if closed(lock, _old(state, "competence_date"), obj.competence_date):
            raise PeriodLockedError(_message(lock))
