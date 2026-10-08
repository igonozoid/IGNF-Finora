"""Regras de negócio. Importar o pacote registra os ganchos de gravação."""
from finora.services import fx  # noqa: F401  (preenche Entry.base_amount na moeda principal)
from finora.services import period_lock  # noqa: F401  (impede mexer em período fechado)
from finora.services import permissions  # noqa: F401  (só grava onde o usuário tem acesso Total)
from finora.services import audit  # noqa: F401  (histórico de alterações)
from finora.services import trash  # noqa: F401  (lançamentos na lixeira somem de todas as consultas)
