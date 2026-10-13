"""DRE: grupos (linhas) na ordem do relatório, em dois modelos — pessoal e empresa.

Cada entidade escolhe o modelo (Entity.dre_model). A categoria-grupo guarda a chave da linha (Category.dre_group).
As chaves dos dois modelos são diferentes; se uma entidade troca de modelo, as categorias são remapeadas
(`categories.convert_model`) e, por garantia, o relatório também traduz chaves do outro modelo (TO_BUSINESS /
TO_PERSONAL).
"""

MODELS = {"personal": "Pessoal (família, pessoa física)", "business": "Empresa (comércio, serviços, rural)"}

PERSONAL = {
    "receitas": "Receitas",
    "moradia": "Moradia",
    "alimentacao": "Alimentação",
    "transporte": "Transporte",
    "saude": "Saúde",
    "educacao": "Educação",
    "lazer": "Lazer",
    "outras": "Outras despesas",
    "investimentos": "Investimentos/Reserva",
}

BUSINESS = {
    "receita_bruta": "Receita bruta",
    "deducoes": "Impostos sobre vendas",
    "custos": "Custos dos produtos e serviços",
    "pessoal": "Despesas com pessoal",
    "administrativas": "Despesas administrativas",
    "comerciais": "Despesas comerciais",
    "receitas_fin": "Receitas financeiras e outras",
    "despesas_fin": "Despesas financeiras",
    "impostos_lucro": "IRPJ e CSLL",
    "retiradas": "Retiradas e distribuição de lucros",
    "imobilizado": "Investimentos e imobilizado",
}

# chave gravada em Category.dre_group -> rótulo (os dois modelos)
GROUPS = {**PERSONAL, **BUSINESS}
INCOME_GROUPS = {"receitas", "receita_bruta", "receitas_fin"}
# fora do resultado do dia a dia (Dashboard: "Sobra do mês" / resultado)
NOT_RESULT = {"investimentos", "retiradas", "imobilizado"}

TO_BUSINESS = {"receitas": "receita_bruta", "moradia": "administrativas", "alimentacao": "administrativas",
               "transporte": "administrativas", "saude": "pessoal", "educacao": "pessoal",
               "lazer": "administrativas", "outras": "administrativas", "investimentos": "imobilizado"}
TO_PERSONAL = {"receita_bruta": "receitas", "receitas_fin": "receitas", "deducoes": "outras", "custos": "outras",
               "pessoal": "outras", "administrativas": "outras", "comerciais": "outras", "despesas_fin": "outras",
               "impostos_lucro": "outras", "retiradas": "outras", "imobilizado": "investimentos"}

HELP = {
    "receita_bruta": "Vendas e serviços prestados, antes dos impostos.",
    "deducoes": "Impostos que incidem sobre as vendas: DAS do Simples, ISS, ICMS, PIS/COFINS; e devoluções.",
    "liquida": "O que sobra das vendas depois dos impostos sobre elas.",
    "custos": "O que custou produzir ou comprar o que foi vendido: matéria-prima, mercadoria, mão de obra direta, "
              "insumos da produção.",
    "bruto": "Receita líquida menos os custos. Mostra se o produto/serviço se paga.",
    "operacional": "O que o negócio gera depois de todas as despesas do dia a dia.",
    "antes_ir": "Resultado operacional mais o financeiro (juros, tarifas, rendimentos).",
    "liquido": "O lucro do período, depois de todos os impostos.",
    "saldo": "O que sobrou depois de retiradas dos sócios e investimentos.",
}


def groups_for(model: str | None) -> dict[str, str]:
    return BUSINESS if model == "business" else PERSONAL


def normalize(group: str | None, kind: str, model: str | None) -> str:
    """Chave da linha da DRE no modelo da entidade (traduz do outro modelo; sem grupo -> padrão do tipo)."""
    groups = groups_for(model)
    if group in groups:
        return group
    other = (TO_BUSINESS if model == "business" else TO_PERSONAL).get(group or "")
    if other:
        return other
    if model == "business":
        return "receita_bruta" if kind == "income" else "administrativas"
    return "receitas" if kind == "income" else "outras"
