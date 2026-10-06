"""Regras de negócio. Importar o pacote registra os ganchos de gravação dos lançamentos."""
from finora.services import fx  # noqa: F401  (preenche Entry.base_amount na moeda principal)
from finora.services import period_lock  # noqa: F401  (impede mexer em período fechado)
from finora.services import audit  # noqa: F401  (histórico de alterações)
