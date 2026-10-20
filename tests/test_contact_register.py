"""Relatório de cadastros: clientes / fornecedores (Fase 3.10, relatório do MCC)."""
from finora.services import contacts, reports

CNPJ = "11222333000181"


def test_relatorio_de_cadastros(session, profile):
    s, eid = session, profile.id
    contacts.create(s, eid, name="Contábil Exemplo", person_type="PJ", document=CNPJ, roles={"supplier"},
                    details={"phone": "3536220000", "email": "contato@contabil.test", "address": "Av. Brasil, 100",
                             "district": "Centro", "city": "Itajubá", "state": "MG", "zip_code": "37500-000",
                             "contact_person": "Ana"})
    contacts.create(s, eid, name="Maria Cliente", roles={"customer"})
    rev = contacts.create(s, eid, name="Nome Solto")
    contacts.update(s, rev, name="Nome Solto", person_type="PF", document=None, roles={"customer", "supplier"})
    s.get(contacts.Contact, rev).needs_review = True
    s.commit()

    rows = {r.name: r for r in reports.contact_register(s, eid)}
    c = rows["Contábil Exemplo"]
    assert (c.document, c.roles, c.phone, c.email, c.address, c.city, c.zip_code, c.contact_person) == \
        ("11.222.333/0001-81", "Eu pago", "3536220000", "contato@contabil.test", "Av. Brasil, 100, Centro",
         "Itajubá/MG", "37500-000", "Ana")
    assert rows["Nome Solto"].roles == "Me paga, Eu pago" and rows["Nome Solto"].needs_review
    assert (rows["Maria Cliente"].document, rows["Maria Cliente"].address, rows["Maria Cliente"].city) == ("", "", "")
    assert [r.name for r in reports.contact_register(s, eid, "customer")] == ["Maria Cliente", "Nome Solto"]
    assert [r.name for r in reports.contact_register(s, eid, "supplier")] == ["Contábil Exemplo", "Nome Solto"]
    assert [r.name for r in reports.contact_register(s, eid, "review")] == ["Nome Solto"]
