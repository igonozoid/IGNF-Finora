from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from finora.services import accounts, categories, entries, period_lock, reconcile, rules
from finora.services.entries import EntryData

OFX = (Path(__file__).parent / "data" / "extrato.ofx").read_bytes()


def _cats(s, eid, kind="expense"):
    return {label.split(" › ")[-1]: cid for cid, label in categories.choices(s, eid, kind)}


def test_regra_mais_especifica_ganha_e_ignora_acentos(session, profile):
    s, eid = session, profile.id
    exp = _cats(s, eid)
    transporte = next(v for k, v in exp.items() if k in ("Transporte", "Combustível", "Aplicativo"))
    mercado = next(v for k, v in exp.items() if k in ("Mercado", "Supermercado", "Restaurante"))
    rules.create(s, eid, text="uber", kind="expense", category_id=transporte)
    rules.create(s, eid, text="Uber Eats", kind="", category_id=mercado, description="iFood/Uber Eats")
    assert rules.match(s, eid, "UBER *TRIP 12/10", "expense").category_id == transporte
    best = rules.match(s, eid, "Pagto UBER EATS", "expense")
    assert best.category_id == mercado and best.description == "iFood/Uber Eats"
    assert rules.match(s, eid, "uber", "income") is None               # regra só de despesa
    assert rules.match(s, eid, "Uber Eats estorno", "income").category_id is None   # categoria de despesa não serve
    rules.create(s, eid, text="Farmácia", category_id=transporte, kind="expense")
    assert rules.match(s, eid, "FARMACIA SAO JOAO", "expense") is not None
    with pytest.raises(ValueError, match="Já existe"):
        rules.create(s, eid, text="UBER", kind="expense", category_id=transporte)
    with pytest.raises(ValueError, match="pelo menos"):
        rules.create(s, eid, text="x", category_id=transporte)
    with pytest.raises(ValueError, match="Escolha"):
        rules.create(s, eid, text="algo")
    inc = _cats(s, eid, "income")
    with pytest.raises(ValueError, match="outro tipo"):
        rules.create(s, eid, text="salario", kind="expense", category_id=next(iter(inc.values())))


def test_regra_na_conciliacao_e_nos_lancamentos_sem_categoria(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    exp = _cats(s, eid)
    luz = exp["Luz"]
    rules.create(s, eid, text="enel", kind="expense", category_id=luz, description="Conta de luz")
    reconcile.import_ofx(s, eid, bank, OFX)
    sug = {ln.memo: ln.suggestion for ln in reconcile.lines(s, eid, bank)}["PAG BOLETO ENEL"]
    assert sug.kind == "new" and sug.category_id == luz and sug.description == "Conta de luz"

    ids = entries.create(s, eid, EntryData(kind="expense", description="Boleto ENEL setembro", amount=D("150"),
                                           due_date=date(2026, 9, 10), account_id=bank))
    old = entries.create(s, eid, EntryData(kind="expense", description="ENEL agosto", amount=D("140"),
                                           due_date=date(2026, 8, 10), account_id=bank))
    period_lock.set_lock(s, eid, date(2026, 8, 31))                    # agosto fechado: não mexe
    assert rules.apply_to_existing(s, eid) == 1
    assert entries.get(s, ids[0]).category_id == luz and entries.get(s, old[0]).category_id is None
