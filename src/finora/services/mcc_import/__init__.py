"""Trazer dados do MCC para o Finora (Fase 2 de docs/PLANO-MCC.md).

- `reader`: abre o banco do clone do MCC (mcc.db) numa cópia, só para leitura, e confere o formato.
- `mapper`: cria as entidades, cadastros, lançamentos e usuários do Finora a partir do banco do MCC.
- `conference`: confere saldos e totais MCC × Finora depois da importação (o que não bater impede concluir).
- `sheets`: planilhas CSV exportadas do MCC original (perfis de coluna) -> um banco no formato do clone, que segue
  o mesmo caminho (reader, mapper, conference); confere os saldos com o rodapé dos extratos.
"""
