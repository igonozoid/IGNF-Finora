"""Listas do contato (Fase 4.2): outras contas bancárias, referências e pessoas de contato."""
import pytest

from finora.services import contacts

LISTS = {"banks": [{"bank_name": "Itaú", "bank_branch": "0412", "bank_account": "5521-3"}, {"bank_name": " "}],
         "references": [{"name": "Loja A", "kind": "comercial", "phone": "1130000000"},
                        {"name": "Sicredi", "kind": "bancaria", "notes": "desde 2010"}],
         "people": [{"name": "Ana", "job": "Financeiro", "extension": "21", "email": "ana@x.com"}]}


def test_guarda_listas_e_ignora_linha_vazia(session, profile):
    s = session
    cid = contacts.create(s, profile.id, name="Empresa", person_type="PJ", lists=LISTS)
    got = contacts.get_lists(s, cid)
    assert [b["bank_name"] for b in got["banks"]] == ["Itaú"]
    assert [(r["name"], r["kind"]) for r in got["references"]] == [("Loja A", "comercial"), ("Sicredi", "bancaria")]
    assert got["people"][0] == {"name": "Ana", "job": "Financeiro", "extension": "21", "email": "ana@x.com",
                                "phone": None}


def test_salvar_substitui_e_none_nao_mexe(session, profile):
    s = session
    cid = contacts.create(s, profile.id, name="Empresa", person_type="PJ", lists=LISTS)
    contacts.update(s, cid, name="Empresa", person_type="PJ", document=None, roles=set(),
                    lists={"banks": [{"bank_name": "Bradesco"}]})
    got = contacts.get_lists(s, cid)
    assert [b["bank_name"] for b in got["banks"]] == ["Bradesco"] and len(got["references"]) == 2
    contacts.update(s, cid, name="Empresa", person_type="PJ", document=None, roles=set(), lists=None)
    assert len(contacts.get_lists(s, cid)["people"]) == 1


def test_pessoas_de_contato_so_em_pj(session, profile):
    s = session
    cid = contacts.create(s, profile.id, name="Maria", person_type="PF", lists={"people": [{"name": "Ana"}]})
    assert contacts.get_lists(s, cid)["people"] == []
    contacts.update(s, cid, name="Maria", person_type="PJ", document=None, roles=set(),
                    lists={"people": [{"name": "Ana"}]})
    contacts.update(s, cid, name="Maria", person_type="PF", document=None, roles=set())
    assert contacts.get_lists(s, cid)["people"] == []


@pytest.mark.parametrize("lists, msg", [
    ({"people": [{"name": "Ana", "email": "ana"}]}, "E-mail"),
    ({"references": [{"name": "X", "kind": "outra"}]}, "Tipo de referência"),
    ({"banks": [{"bank_name": "B" * 61}]}, "longo"),
])
def test_validacoes(session, profile, lists, msg):
    with pytest.raises(ValueError, match=msg):
        contacts.create(session, profile.id, name="X", person_type="PJ", lists=lists)


def test_excluir_e_mesclar_levam_as_listas(session, profile):
    s, eid = session, profile.id
    keep = contacts.create(s, eid, name="Enel", person_type="PJ")
    drop = contacts.create(s, eid, name="ENEL SA", person_type="PJ", lists=LISTS)
    contacts.merge(s, keep, drop)
    assert len(contacts.get_lists(s, keep)["references"]) == 2
    contacts.delete(s, keep)
    assert contacts.get_lists(s, keep) == {"banks": [], "references": [], "people": []}
