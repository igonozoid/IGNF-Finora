"""RH (módulo "hr", decisão D4)."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.models import EmployeeProfile, EmployeeRecord
from finora.services import contacts, hr


def test_funcionario_salario_beneficios_e_folha(session, profile):
    s, eid = session, profile.id
    ana = hr.add_employee(s, eid, "Ana Diarista")
    hr.save_profile(s, eid, ana, job_title="Diarista", employment_type="Diarista", initial_salary=D("1200"),
                    admission_date=date(2024, 3, 1), inss_rate=D("0.08"))
    assert hr.list_employees(s, eid)[0][0].salary == D("1200.00")             # sem reajuste: o inicial
    hr.save_record(s, eid, ana, kind="salary", day=date(2025, 1, 1), amount=D("1518"), net_amount=D("1400"))
    hr.save_record(s, eid, ana, kind="salary", day=date(2026, 1, 1), amount=D("1600"))
    hr.save_record(s, eid, ana, kind="benefit", name="Unimed", amount=D("300"))
    hr.save_record(s, eid, ana, kind="benefit", name="Seguro", amount=D("50"), active=False)
    joao = contacts.create(s, eid, name="João", roles={"employee"})           # contato que já trabalha para mim
    hr.save_profile(s, eid, joao, initial_salary=D("2000"), staff_category="office")
    lst, summ = hr.list_employees(s, eid)
    assert [(e.name, e.salary, e.benefits, e.total) for e in lst] == [
        ("Ana Diarista", D("1600.00"), D("300.00"), D("1900.00")), ("João", D("2000.00"), D("0.00"), D("2000.00"))]
    assert (summ.count, summ.active, summ.payroll) == (2, 2, D("3900.00"))
    assert [e.name for e in hr.list_employees(s, eid, staff="office")[0]] == ["João"]
    hr.save_profile(s, eid, joao, termination_date=date(2026, 1, 31), admission_date=date(2025, 1, 1))
    assert [e.name for e in hr.list_employees(s, eid)[0]] == ["Ana Diarista"]
    assert [e.name for e in hr.list_employees(s, eid, status="terminated")[0]] == ["João"]
    assert len(hr.list_employees(s, eid, status=None)[0]) == 2


def test_custo_com_encargos(session, profile):
    s, eid = session, profile.id
    cid = hr.add_employee(s, eid, "Ana")
    hr.save_profile(s, eid, cid, initial_salary=D("1200"), inss_rate=D("0.08"))
    c = hr.cost(s, cid)
    got = dict(c.lines)
    assert got["INSS patronal (8%)"] == D("96.00") and got["FGTS (8%)"] == D("96.00")
    assert got["Provisão de 13º (1/12)"] == D("100.00") and got["Provisão de 1/3 de férias"] == D("33.33")
    assert got["INSS sobre o 13º"] == D("8.00") and got["FGTS sobre 1/3 de férias"] == D("2.67")
    assert c.charges == D("96") + D("96") + D("100") + D("8") + D("8") + D("33.33") + D("2.67") + D("2.67")
    assert c.total == D("1200.00") + c.charges
    assert hr.fmt_rate(D("0.08")) == "8" and hr.fmt_rate(D("0.075")) == "7,5" and hr.fmt_rate(None) == ""


@pytest.mark.parametrize("kind, data, msg", [
    ("salary", {"amount": D("1")}, "data e do valor"),
    ("vacation", {}, "período aquisitivo"),
    ("vacation", {"day": date(2026, 2, 10), "end_day": date(2026, 2, 1)}, "antes do início"),
    ("thirteenth", {}, "ano"),
    ("benefit", {"name": "Unimed"}, "nome e do valor"),
    ("other", {}, "Tipo"),
])
def test_validacoes_do_historico(session, profile, kind, data, msg):
    cid = hr.add_employee(session, profile.id, "Ana")
    with pytest.raises(ValueError, match=msg):
        hr.save_record(session, profile.id, cid, kind=kind, **data)


def test_validacoes_do_perfil(session, profile):
    s, eid = session, profile.id
    cid = hr.add_employee(s, eid, "Ana")
    with pytest.raises(ValueError, match="fração"):
        hr.save_profile(s, eid, cid, inss_rate=D("8"))
    with pytest.raises(ValueError, match="antes da admissão"):
        hr.save_profile(s, eid, cid, admission_date=date(2026, 1, 1), termination_date=date(2025, 1, 1))
    with pytest.raises(ValueError, match="nome"):
        hr.add_employee(s, eid, " ")


def test_registros_editar_remover_e_mesclar(session, profile):
    s, eid = session, profile.id
    a = hr.add_employee(s, eid, "Ana")
    b = hr.add_employee(s, eid, "ANA SILVA")
    rid = hr.save_record(s, eid, b, kind="thirteenth", period="2025", amount=D("1500"), day=date(2025, 12, 20))
    hr.save_record(s, eid, b, rid, kind="thirteenth", period="2025", amount=D("1600"))
    assert [(r.kind, r.amount) for r in hr.records(s, b)] == [("thirteenth", D("1600.00"))]
    contacts.merge(s, a, b)
    assert len(hr.records(s, a)) == 1
    assert s.query(EmployeeProfile).filter_by(contact_id=a).count() == 1
    hr.delete_record(s, hr.records(s, a)[0].id)
    assert s.query(EmployeeRecord).count() == 0
