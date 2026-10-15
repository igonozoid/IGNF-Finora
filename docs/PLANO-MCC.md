# Plano de implementação — novo Finora (substituto do MCC)

Base: [`ANALISE-MCC.md`](ANALISE-MCC.md) · Data: 15/10/2026 · Repositório alvo: `igonozoid/IGNF-Finora`

## Objetivo

Colocar o Finora em condições de **substituir o MCC** no uso diário, com os dados trazidos de lá e com os recursos
do IgnControl que ainda faltam, sem quebrar o que o Finora já tem.

## Regras que valem para todas as fases (do `CLAUDE.md` do Finora)

- Regra de negócio em `services/`; a UI não faz SQL. Dinheiro sempre em `Decimal`.
- Mudou modelo → revisão Alembic (`alembic revision --autogenerate -m "…"`) revisada à mão. O teste
  `test_migracoes_batem_com_os_modelos` precisa passar.
- Código compatível com MariaDB/PostgreSQL: nada de SQL exclusivo do SQLite. Rodar a suíte também contra o Finora
  Servidor.
- Recurso pago → `core/licensing.allowed()` com cadeado na Free.
- Textos em PT-BR simples, ajuda (F1) atualizada em `assets/ajuda.md`.
- Cada item abaixo vira um **commit pequeno com teste** (service + tela). Uma fase só fecha com a CI verde
  (Windows e Linux).

Legenda de tamanho: **P** ≤ 1 dia · **M** 2–3 dias · **G** 4–6 dias.

---

## Fase 0 — Preparação (P, ~2 dias)

| # | Tarefa | Saída |
|---|---|---|
| 0.1 | Instalar Git e Python 3.12 na máquina de desenvolvimento e clonar o Finora com histórico | ambiente de dev |
| 0.2 | Rodar `pytest` e os testes de tela para ter a linha de base | relatório da suíte |
| 0.3 | **Teste de exportação no MCC original**: exportar para Excel/CSV, de 1 conta controle, o relatório de despesas e o de receitas (todo período, todas situações), os cadastros de clientes e fornecedores, o extrato de cada conta e as movimentações bancárias | planilhas de amostra em `amostras/mcc/` (fora do Git, por ter dados reais) |
| 0.4 | Conferir nessas planilhas quais colunas o MCC entrega (doc., pessoa, vencimento, pagamento, conta, centro, obs.) | lista de colunas → define a Fase 2b |
| 0.5 | Gerar um `mcc.db` de teste com o clone (`mcc-desktop`) e dados fictícios cobrindo todos os casos | fixture `tests/data/mcc_exemplo.db` |
| 0.6 | Abrir no GitHub um *milestone* por fase e uma *issue* por item | quadro de acompanhamento |

**Critério de saída:** suíte verde localmente; amostras do MCC original conferidas; fixture pronta.

---

## Fase 1 — Paridade MCC: núcleo de lançamentos e cadastros (G, ~3 semanas)

Prioridade máxima: é o que o usuário do MCC sente no primeiro dia.

### 1A. Lançamentos
| # | Tarefa | Onde mexe | Tam. |
|---|---|---|---|
| 1.1 | **Observações** no lançamento (`Entry.notes`, Text) e na transferência; aparece no formulário, na lista (coluna opcional), na busca, no recibo e nos relatórios | `models`, migração, `services/entries.py`, `ui/entries_page.py`, `services/search.py` | M |
| 1.2 | **Periodicidades** diária, quinzenal, bimestral, trimestral e semestral em `REPEATS`; **parcelado com periodicidade** (hoje só mensal) | `services/entries.py` (`REPEATS`, `occurrence`), formulário | M |
| 1.3 | Parcelamento: opção "data de competência = vencimento" e nº do documento com sufixo `n/N` | `entries.create` | P |
| 1.4 | **Baixa completa**: data, **valor pago** (juros/multa/desconto), **conta de pagamento** e observação; na baixa múltipla, só a data. Guardar `original_amount` para relatório de juros/descontos | `Entry.original_amount`, `entries.set_paid`, novo `ui/payment_dialog.py` | M |
| 1.5 | Excluir em série: **"esta"**, **"esta e as próximas"**, **"todas"** e **"todas em aberto"** (tudo para a Lixeira) | `entries.delete(scope=…)`, diálogo de exclusão | P |
| 1.6 | **Transferir lançamentos para outra entidade** (seleção múltipla; limpa centro de custo e categoria não compartilhada; checa permissão nas duas entidades e o fechamento de período) | `services/entries.py` + ação no menu de contexto | M |
| 1.7 | "Repetir no mês seguinte" (atalho do "Duplicar" com +1 mês) | `ui/entries_page.py` | P |
| 1.8 | Filtro por **campo de data** (competência / vencimento / pagamento) e períodos trimestre/semestre/ano/todo | `entries.list_entries`, cabeçalho | M |
| 1.9 | **Depósito e retirada** (ajuste de saldo sem receita/despesa): `kind` novo `adjust` com sinal, fora da DRE e dentro do saldo e do extrato | `Entry.kind`, `accounts._movements`, `reports`, formulário | M |

### 1B. Cadastros
| # | Tarefa | Onde mexe | Tam. |
|---|---|---|---|
| 1.10 | **Conta compartilhada** entre entidades (`Account.shared`, mesmo padrão de `scope.py`) | `models`, `services/scope.py`, `services/accounts.py`, `ui/accounts_page.py` | M |
| 1.11 | **Limite da conta** (cheque especial) para conta bancária; aviso quando o saldo previsto passa do limite | `Account.credit_limit` (já existe, liberar para `bank`), dashboard | P |
| 1.12 | Centro de custo: **aplica a despesas / aplica a receitas** e **projeção mensal de receita** (`budget` = orçamento de despesa) | `CostCenter.applies_expense/applies_income/projection`, `cost_centers.choices(kind)` | M |
| 1.13 | Entidade: **bairro**, complemento e país; opção "usa centro de custo" (esconde o campo) | `Entity`, `entity_admin.DETAILS`, Configurações | P |
| 1.14 | Contato: **bairro**, **RG/IE** (`document2`), **pessoa de contato**; dados bancários em campos separados (banco, agência, conta, titular), mantendo `pix_key` | `Contact`, `contacts.DETAILS`, `ui/contacts_page.py` | M |
| 1.15 | Preferências por entidade (estilo FConfigConta): **conta padrão** do lançamento, campo inicial do formulário, exibir saldos no painel | `core/settings.py` (chaves por `entity_id`) | P |

### 1C. Permissões (opcional; decidir na revisão da fase)
| 1.16 | Separar `financial` em **Despesas**, **Receitas**, **Bancos/Conciliação** e **Centros**, como no MCC, com migração que copia o nível atual para os quatro | `services/permissions.py` (`MODULES`, `PAGE_MODULE`, `_guard`) | M |

**Critério de saída:** roteiro de uso do MCC (incluir, parcelar quinzenal, baixar com juros, excluir em aberto,
transferir para outra empresa, depósito/retirada) feito de ponta a ponta no Finora; testes de service e de tela
para cada item.

---

## Fase 2 — Importador MCC (G, ~2–3 semanas)

Novo módulo `services/mcc_import/` e assistente em **Configurações › Trazer dados do MCC** (Plus/Pro, porque cria
várias entidades).

### 2A. Do `mcc.db` (clone MCC_CLAUDE-REA)
| # | Tarefa | Tam. |
|---|---|---|
| 2.1 | Leitor somente leitura do SQLite do MCC (abre cópia; nunca grava no original) | P |
| 2.2 | Mapeamento conforme `ANALISE-MCC.md` §3: empresas → `Entity` (+logo, bloqueio); contas (compartilhadas → `shared`); centros; pessoas (NULL → `shared`; C/F → papéis); itens → categorias em "Outras despesas/receitas"; lançamentos; movbancarias (T → transfer, D/R → `adjust`); `ofx_importados` → `BankLine.fitid` | G |
| 2.3 | **Pessoa em texto → contato**: casar por nome normalizado (sem acento e sem maiúscula, igual ao `ordem_pt`); se não existir, criar um contato marcado "importado – revisar" | M |
| 2.4 | `REAL` → `Decimal` com `quantize(0.01)`; registrar diferenças de arredondamento | P |
| 2.5 | Séries: `grupo` → `series_id`; `parcela/total` → `installment`; lixeira: `excluido_em` → `deleted_at` | P |
| 2.6 | Usuários: criar com **senha a redefinir** no 1º acesso; `perm_*` → permissões (tabela da §3); `usuario_empresas` → `UserEntity` | M |
| 2.7 | **Relatório de conferência** (PDF/Excel): por entidade e conta, saldo realizado e previsto no MCC × Finora em 3 datas, nº de lançamentos por tipo e situação, total a pagar/receber. Divergência ≠ 0 bloqueia o "Concluir" | M |
| 2.8 | Importação **idempotente** (tabela `import_map(origem, id_origem, id_finora)`): reimportar atualiza em vez de duplicar, o que permite rodar várias vezes no piloto | M |
| 2.9 | Backup automático antes de importar; tudo numa transação por entidade | P |

### 2B. Das planilhas exportadas do MCC original
| # | Tarefa | Tam. |
|---|---|---|
| 2.10 | Reaproveitar `services/statement_import.py` (`read_table`, `parse_date`, `parse_amount`, `guess`) com **perfis de coluna** do MCC definidos na Fase 0.4 | M |
| 2.11 | Assistente: escolher a entidade e a conta, apontar os arquivos (despesas, receitas, clientes, fornecedores, movimentações), prévia, importar → mesmo pipeline e mesma conferência da 2A | M |
| 2.12 | Tratar o que a planilha não traz (ex.: id de série): agrupar parcelas por doc. + descrição + pessoa | P |

### 2C. Pós-importação
| # | Tarefa | Tam. |
|---|---|---|
| 2.13 | **Mesclar contatos** duplicados (move lançamentos, estoque e vendas para o contato mantido; registra na auditoria) | M |
| 2.14 | **Reclassificar categorias na DRE** em lote, com sugestão por nome do item; usar as regras automáticas já existentes | M |

**Critério de saída:** fixture `mcc_exemplo.db` e as amostras reais da Fase 0 importam com conferência zerada;
reimportar não duplica nada.

---

## Fase 3 — Relatórios do MCC (G, ~2–3 semanas)

Todos como `TableReport` em `ui/report_lists.py`, com service em `services/reports.py`, registrados em
`REPORTS` (`ui/reports_page.py`). Impressão e Excel/PDF já vêm da infraestrutura (`Sheet`).

| # | Relatório | Tam. |
|---|---|---|
| 3.1 | **Análise de pontualidade** (pagamentos/recebimentos por contato: ocorrências, maior atraso, maior antecipação, média) | P |
| 3.2 | **Saldos em uma data** (realizado × previsto por conta) | P |
| 3.3 | **Comparativo de saldos** entre duas datas | P |
| 3.4 | **Extrato de fechamento de caixa** (movimento realizado de todas as contas, acumulado) | P |
| 3.5 | Extrato de conta com modo **previsto** (inclui em aberto) | P |
| 3.6 | **Demonstrativo anual** agrupado por categoria, **contato, centro ou conta** (12 meses + média + total) | M |
| 3.7 | **Orçamento por centro de custo / projeção por centro de lucro** (meta × meses do período × realizado, % atingido) | M |
| 3.8 | **Fluxo de caixa por centro** (pago, recebido, a pagar, a receber, saldo real e previsto) | P |
| 3.9 | **Analítico com agrupamentos livres** (até 2 níveis entre categoria, contato, conta, centro, mês, situação e tipo; ordem escolhida; detalhado ou totalizado) | G |
| 3.10 | Relatório de **cadastros** (clientes / fornecedores) | P |
| 3.11 | **Juros e descontos** na baixa (usa `original_amount` da 1.4) | P |
| 3.12 | Dashboard: aba **Caixa × Competência** (período hoje/semana/mês/personalizado, "considerar vencidos") e **análise linear** diária/semanal/mensal | M |
| 3.13 | Recibo em **2 vias** e **duplicata** mercantil/serviço (valor por extenso já existe em `core/extenso.py`), margens configuráveis | M |
| 3.14 | Exportar também em **CSV** (além de Excel/PDF) | P |

**Critério de saída:** para cada relatório, números iguais ao MCC clone sobre a mesma fixture (teste automatizado
comparando com `mcc-desktop/mcc/core/finance.relatorio`).

---

## Fase 4 — Contatos completos (M, ~1–2 semanas)

Junta o "perfil do cliente" do MCC com o cadastro de crédito do IgnControl. Formulário em abas: Dados ·
Endereço · Bancos · Crédito · Referências · Observações · Anexos.

| # | Tarefa | Tam. |
|---|---|---|
| 4.1 | Crédito: limite, consultado em (data), pendência e local, nome da mãe (PF), classificação, frequência de compra | M |
| 4.2 | Tabelas filhas: **contas bancárias** (várias), **referências comerciais**, **referências bancárias**, **pessoas de contato** (PJ: nome, cargo, ramal, e-mail) | M |
| 4.3 | **Anexos do contato** (reaproveitar `Attachment`, ligando a contato) e foto opcional | M |
| 4.4 | Data importante / aniversário → aparece nos **lembretes** | P |
| 4.5 | Aviso em Vendas e no lançamento a receber quando o cliente passa do **limite de crédito** ou tem pendência | P |
| 4.6 | Flag **"precisa revisar"** para contato, categoria ou centro criado dentro do lançamento ou na importação, com filtro na lista | P |

---

## Fase 5 — Recursos restantes do IgnControl (M, ~2 semanas)

| # | Tarefa | Tam. |
|---|---|---|
| 5.1 | Vendas: tipo **devolução** (entra estoque, gera estorno a receber/pagar) e status **liquidado** | M |
| 5.2 | Agricultura: **Safra** (área, cultura, plantio, colheita prevista e real, produtividade esperada × real; colheita gera entrada no estoque) ligando as atividades existentes | G |
| 5.3 | Agricultura: **Ativos** (máquinas/implementos) e custo por ativo nas atividades | M |
| 5.4 | Moedas: casas decimais e ativa/inativa | P |
| 5.5 | Produto: **perfil tributário** (só se a NF-e entrar no roadmap) | — |

---

## Fase 6 — Piloto e desligamento do MCC (~4–6 semanas de calendário)

| # | Tarefa |
|---|---|
| 6.1 | Gerar a versão (`tools/build.py`) e instalar o Finora Servidor + os PCs da equipe |
| 6.2 | Importação inicial (Fase 2) e conferência assinada pelo responsável financeiro |
| 6.3 | **Uso em paralelo por 1 mês**: lançar nos dois e, toda semana, reimportar e conferir saldos (o importador é idempotente) |
| 6.4 | Treinamento curto com um roteiro "do MCC para o Finora" (onde ficou cada tela/relatório) em `docs/` e na ajuda F1 |
| 6.5 | Coletar ajustes do piloto → *issues* de correção |
| 6.6 | Fechamento do mês no MCC → última importação → MCC passa a ser só consulta (exportar tudo e guardar) |

**Critério de saída:** um fechamento mensal completo feito só no Finora, sem divergências.

---

## Fase 7 — Futuro (fora do escopo deste plano)

API REST com permissão por módulo (o desenho de `routes/api.php` do IgnControl serve de referência) → modo nuvem
(mesmo app, banco remoto) → app mobile. Acesso externo para sócios só leitura (modelo Cloudflare Access do
IgnControl). Assinatura digital e instalador Windows (pendentes no ROADMAP).

---

## Cronograma estimado (1 desenvolvedor + Claude)

| Fase | Duração | Acumulado |
|---|---|---|
| 0 Preparação | 2 dias | sem. 1 |
| 1 Paridade núcleo | 3 semanas | sem. 4 |
| 2 Importador | 2–3 semanas | sem. 7 |
| 3 Relatórios | 2–3 semanas | sem. 10 |
| 4 Contatos | 1–2 semanas | sem. 12 |
| 5 IgnControl restante | 2 semanas | sem. 14 |
| 6 Piloto | 4–6 semanas (em paralelo com a 4 e a 5) | ~sem. 14–16 |

As fases 4 e 5 não bloqueiam o piloto: ele pode começar ao fim da Fase 3.

## Decisões em aberto

1. **Permissões granulares** do MCC (item 1.16): separar Financeiro em 4 módulos ou manter como está?
2. **Depósito/retirada** como `kind="adjust"` (proposto) ou como receita/despesa numa categoria "Ajuste de saldo"?
3. **Edição** dos recursos novos: o importador do MCC e os relatórios novos ficam em Plus/Pro ou na Free?
4. **RH e agenda** continuam fora? (O MCC não tem; só entram se o BPO pedir.)
5. **Credencial embutida no MCC**: avisar o fornecedor antes do desligamento?

## Riscos

| Risco | Mitigação |
|---|---|
| O MCC original não exporta tudo (ex.: id de série, centro) | Fase 0.3 antes de tudo; heurística da 2.12; completar à mão |
| Divergência de saldo por arredondamento `REAL` | conferência 2.7 bloqueia; relatório de diferenças |
| Contatos duplicados por nome livre | 2.3 + mesclar (2.13) + flag revisar (4.6) |
| Usuários estranham a mudança de tela | roteiro 6.4, preferências 1.15, nomes de relatórios iguais aos do MCC |
| Regressão no que já funciona | uma migração por item, CI Windows/Linux e testes contra MariaDB |
