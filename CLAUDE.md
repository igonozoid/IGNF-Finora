# IGNF Finora — guia de desenvolvimento

App desktop de finanças **pessoais** em Python 3.12 + PySide6. Usuário leigo, 1 usuário, banco SQLite local em `data/finora.db`.
Referência visual: mockup "App Financeiro" (exportado em `docs/mockup/`). Siga-o.

## Regras
- Textos da UI em PT-BR, linguagem simples; termos técnicos ganham ícone "?" com tooltip.
- Ícones: qtawesome, prefixo `fa6s.` (sólido) / `fa6.` (regular — o qtawesome não tem `fa6r.`).
- Tema: `ui/theme.py` (LIGHT/DARK). Gere o QSS a partir desses tokens; nada de cor fixa nos widgets.
- Densidade alta: linhas de tabela 26px, fonte 9pt, espaçamentos 4/8/12.
- Valores monetários: `Decimal`, nunca float. Fonte monoespaçada em colunas de valor.
- Toda regra de negócio em `services/`; a UI não faz SQL.
- Recursos pagos sempre checam `core/licensing.allowed()`; na Free, mostrar o recurso com cadeado e convite para upgrade.
- Migrações via Alembic a partir da 1ª versão publicada.
- Commits pequenos, mensagem em PT-BR.

## Ordem de construção
1. MainWindow: barra lateral (Dashboard, Lançamentos, Contas, Categorias, Contatos, Relatórios, Configurações), QStackedWidget, alternância de tema persistida (QSettings), barra de status.
2. Primeiro uso: assistente (nome, moeda, 1ª conta, categorias padrão).
3. Contas e Categorias (árvore com grupo da DRE, ativar/inativar).
3b. Contatos: lista com busca, cadastro PF/PJ (nome, CPF/CNPJ, papéis), editar; os criados pelo lançamento aparecem aqui. Autopreencher CPF/CNPJ é Pro (cadeado).
4. Lançamentos: tabela filtrável (Todos/A receber/A pagar/Atrasados/Pagos), formulário lateral, recorrência, parcelamento, transferência.
5. Dashboard: 4 cards, gráfico 6 meses (QtCharts), vencimentos 7 dias, top categorias.
6. Relatórios: DRE pessoal (Receitas, Despesas fixas, variáveis, Investimentos, Resultado), fluxo de caixa.
7. Backup/restauração.
8. Licença (chave offline assinada).

## DRE pessoal — grupos
Receitas · (−) Moradia · (−) Alimentação · (−) Transporte · (−) Saúde · (−) Educação · (−) Lazer · (−) Outras despesas · = Sobra do mês · (−) Investimentos/Reserva · = Saldo livre
