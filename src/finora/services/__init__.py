"""Regras de negócio. Importar o pacote registra o cálculo automático do valor na moeda principal."""
from finora.services import fx  # noqa: F401  (gancho before_flush que preenche Entry.base_amount)
