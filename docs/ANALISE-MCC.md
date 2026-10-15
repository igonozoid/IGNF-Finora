# Análise de correlação — Finora × MCC × IgnControl

Data: 15/10/2026 · Fontes: branch `main` de cada repositório nessa data.

| Repositório | Papel |
|---|---|
| `igonozoid/IGNF-Finora` | **Projeto oficial** |
| `igonozoid/MCC_CLAUDE-REA` | Clone do sistema usado hoje (MCC) |
| `igonozoid/IgnControl` | 1ª tentativa de implementação |

---

## 1. Resumo executivo

1. **O Finora é a base certa.** Usa a mesma stack do clone do MCC (Python + PySide6 + SQLite), mas com
   arquitetura melhor: SQLAlchemy/Alembic, `Decimal` em vez de `REAL`, testes, licenciamento, rede via MariaDB
   e módulos. O IgnControl (Laravel/web) ficou como fonte de ideias, e o Finora já absorveu a maior parte delas.
2. **O Finora cobre cerca de 75% do uso diário do MCC.** O núcleo é o mesmo: despesas e receitas, a pagar e a
   receber, baixa, baixa múltipla, parcelamento, transferências, OFX/conciliação, centros de custo, permissões,
   bloqueio de período, lixeira, lembretes, recibo e relatórios. As lacunas estão em detalhes que o usuário do MCC
   sente na hora: periodicidades, baixa com valor diferente, observação, contas compartilhadas, cerca de 10
   relatórios específicos e a duplicata (lista na seção 4).
3. **Hoje não existe migração de dados MCC → Finora.** E há um ponto crítico: no **MCC original** (Delphi) os dados
   ficam num **servidor DataSnap remoto do fornecedor**, não num arquivo local. Caminhos possíveis:
   - **(a) clone `mcc.db`**: importador direto SQLite → Finora. É viável e simples (mapeamento na seção 3).
   - **(b) MCC original**: exportar pelo próprio MCC (os relatórios têm *Exportar para Excel/CSV/TXT*) e importar
     essas planilhas no Finora. **Não usar** a credencial embutida no `mcc.exe`, que a análise do REA encontrou:
     é um risco de segurança e jurídico.
4. **Do IgnControl ainda faltam no Finora:** perfil de crédito e referências de contatos, observações no
   lançamento, safra e ativos rurais, devolução em vendas e API REST. RH, agenda e cofre de senhas ficaram fora por
   decisão do ROADMAP. Vale reavaliar essa decisão só se o MCC/BPO precisar desses recursos (o MCC não tem nenhum
   dos três).

---

## 2. Os três projetos lado a lado

| | **Finora** (oficial) | **MCC original** | **MCC clone** (`MCC_CLAUDE-REA`) | **IgnControl** |
|---|---|---|---|---|
| Tipo | Desktop portátil | Desktop Delphi (roda via Wine) | Desktop + web | Web (LAN + túnel) |
| Stack | Python 3.12 · PySide6 · SQLAlchemy · Alembic | Delphi VCL · FireDAC · QuickReport | Python/PySide6 (`mcc-desktop`) + Node (`mcc-clone`) | Laravel 12 · Livewire 3 |
| Dados | SQLite local / MariaDB (Finora Servidor) | **Servidor DataSnap REST do fornecedor** (porta 5081) | SQLite `mcc.db` (formato igual no desktop e no web) | MySQL |
| Dinheiro | `Numeric(15,2)` / `Decimal` | ? | `REAL` (float) | `DECIMAL(15,4)` |
| Multiempresa | Entidade (`entity_id`) | Conta controle | `empresas` (`empresa_id NULL` = compartilhado) | `company_id` |
| Testes | pytest + pytest-qt, CI | — | unittest + node test | PHPUnit |

O clone do MCC foi reconstruído por engenharia reversa (REA) a partir de 80 formulários `TF*.dfm` e de
`analise/schema.json` (61 tabelas em memória). As telas e regras estão documentadas em
`analise/MCC-funcionalidades.md` e `analise/screens.txt`.

---

## 3. Mapeamento de dados MCC (clone) → Finora

Base: `mcc-desktop/mcc/core/db.py` × `finora/models/entities.py`.

| MCC (`mcc.db`) | Finora | Observações para o importador |
|---|---|---|
| `empresas` (conta controle) | `Entity` | `pessoa F/J` → `person_type PF/PJ`; `bloqueio_ate` → `locked_through`; **bairro sem campo** (concatenar em `address` ou criar coluna); `usa_centro_custo` sem equivalente |
| `empresa_logos` | `Entity.logo` | direto |
| `empresa_config` | `core/settings` por entidade | conta padrão, exibir saldos, campo inicial: **parcial** |
| `contas` tipo `B`/`C` | `Account` kind `bank`/`cash` | `REAL` → `Decimal`; **`empresa_id NULL` (compartilhada) não tem equivalente**: `Account` não tem `shared`; **`limite` (cheque especial) só existe para cartão** |
| `centros` | `CostCenter` | `orcamento` → `budget`; **`aplica_despesa`/`aplica_receita` e `projecao` não têm campo** |
| `pessoas` tipo `C`/`F` | `Contact` com `is_customer`/`is_supplier` | `empresa_id NULL` → `shared=True`; **faltam `bairro`, `documento2` (RG/IE), `contato`, `limite`**; `banco`/`agencia`/`conta_bancaria` → `bank_info` (texto único) |
| `pessoas_extra` (JSON: perfil, referências) | — | **sem destino** (igual às lacunas de contatos do IgnControl) |
| `itens` D/R (lista plana) | `Category` income/expense | criar uma categoria por item; **não há grupo da DRE**: importar em "Outras despesas/receitas" e pedir para o usuário reclassificar |
| `lancamentos` | `Entry` | `tipo D/R` → `expense/income`; `situacao V/P` → `paid/pending`; `data_mov` → `competence_date`; `vencimento` → `due_date`; `data_pagamento` → `paid_date`; `documento` → `document_no`; `descricao` (= item) → `category_id` + `description`; **`pessoa` é texto livre** → `contact_id` por nome normalizado (sem acento/maiúscula); **`observacao` sem campo**; `grupo` → `series_id`; `parcela`/`total_parcelas` → `installment "3/12"`; `excluido_em` → `deleted_at` |
| `movbancarias` T (transferência) | `Entry` kind `transfer` | `situacao P` → `pending` |
| `movbancarias` D/R (depósito/retirada) | `Entry` income/expense **sem categoria** | conferir se relatórios/DRE tratam lançamento sem categoria como "ajuste de saldo" e não como receita/despesa |
| `ofx_importados` | `BankLine.fitid` | evita reimportar |
| `usuarios` + `perm_*` | `User` + `Permission` | **a senha não migra** (hash diferente): forçar nova senha; `perm_despesas/receitas/centros/bancos/fluxo/config` (0/1/2) → módulos `financial/reports/admin` (`none/read/full`), com perda de granularidade; `todas_empresas` + `usuario_empresas` → `UserEntity` |

---

## 4. Paridade funcional: o que o usuário do MCC vai sentir falta no Finora

✅ = Finora tem · 🟡 = tem parcialmente · ❌ = não tem

### Lançamentos
| Recurso MCC | Finora | Nota |
|---|---|---|
| Incluir/alterar/excluir, localizar, busca rápida | ✅ | busca global Ctrl K |
| Parcelamento 1–360 | ✅ | |
| **Periodicidade** diária, semanal, quinzenal, mensal, bimestral, trimestral, semestral, anual | 🟡 | Finora: só semanal, mensal e anual; **parcelado só mensal** |
| Nº doc. com sufixo "n/N" automático no parcelamento | 🟡 | `installment` separado |
| "Mov = vencimento" no parcelamento | ❌ | |
| Baixa / baixa múltipla | ✅ | |
| **Baixa com valor diferente (juros/desconto), outra conta e obs.** | ❌ | `set_paid` só marca pago e data |
| Estornar baixa | ✅ | `set_paid(False)` |
| Excluir: esta / seguintes / **todas** / **todas em aberto** | 🟡 | Finora: "esta" e "esta e as próximas em aberto" |
| Registros excluídos + restaurar | ✅ | Lixeira |
| **Transferir lançamentos para outra conta controle** | ❌ | |
| Repetir no mês seguinte | 🟡 | "Duplicar" |
| **Observação** do lançamento | ❌ | só `description` |
| Filtro por campo de data (movimento / vencimento / ambos), trimestre/semestre/ano | 🟡 | conferir na UI |
| Movimentação bancária: depósito, retirada, transferência **prevista × realizada** | 🟡 | transferência ✅; depósito/retirada viram receita/despesa |

### Cadastros e configuração
| Recurso MCC | Finora | Nota |
|---|---|---|
| Contas bancária/caixa, ativa | ✅ | |
| **Conta compartilhada entre contas controle** | ❌ | categorias/centros/contatos já têm `shared` |
| **Limite da conta (cheque especial)** | ❌ | só no cartão |
| Centros: **aplica a despesa/receita, projeção mensal** | ❌ | só `budget` |
| Clientes/fornecedores: 4 abas (dados, **perfil do cliente**, dados bancários, obs.) | 🟡 | sem perfil/referências, bairro, RG/IE, contato |
| Itens de despesa/receita | ✅ | categorias (com DRE, que é melhor) |
| Usuários, permissões por módulo e por conta controle | ✅ | granularidade diferente |
| Proteção de dados (bloqueio com senha do admin) | ✅ | fechamento de período |
| Config. da conta controle (conta padrão, exibir saldos, campo inicial, itens próprios/de todas) | 🟡 | |
| Lembrete de contas, "ativar lembrete novamente" | ✅ | |
| Logomarca nos relatórios | ✅ | |

### Dashboard e relatórios (o MCC tem cerca de 50)
| Relatório MCC | Finora |
|---|---|
| Despesas/receitas detalhado e totais por item | ✅ por categoria / analítico |
| A pagar / a receber por pessoa | ✅ por contato, inadimplência |
| **Análise de pontualidade** (atraso/antecipação médio por pessoa) | ❌ |
| Fluxo de caixa realizado, por dia, previsão | ✅ |
| Extrato de conta, **extrato de previsão bancária**, **extrato do caixa interno** | 🟡 |
| **Extrato de fechamento de caixa** (todas as contas) | ❌ |
| **Saldo de contas em uma data (realizado × previsto)** | 🟡 |
| **Comparativo de saldos entre duas datas** | ❌ |
| Demonstrativo anual por **item, pessoa, centro, conta** | 🟡 só por categoria (`category_by_month`) |
| **Orçamento por centro / projeção por centro de lucro** | 🟡 orçamento por categoria |
| **Fluxo de caixa por centro** (pago, recebido, a pagar, a receber) | ❌ |
| Relatório analítico com **agrupamentos livres** (item, pessoa, conta, centro, mês, situação) | 🟡 |
| Relatório de clientes / fornecedores (cadastro) | ❌ |
| DRE | ✅ (melhor: DRE pessoal/empresa) |
| Gráficos gerenciais | ✅ |
| Dashboard caixa × competência × **análise linear diária/semanal/mensal** | 🟡 |
| Recibo **1 ou 2 vias** e **duplicata mercantil/serviço** | 🟡 só recibo |
| Exportar Excel, CSV, TXT, HTML, PDF | 🟡 Excel/PDF |

---

## 5. Recursos do IgnControl ainda não trazidos ao Finora

| Área | IgnControl | Prioridade sugerida |
|---|---|---|
| Contatos — crédito | limite, consulta de crédito (data), pendência e local, nome da mãe, classificação, frequência de compra | **Alta** (o MCC também tem "perfil do cliente") |
| Contatos — referências | comerciais, bancárias, várias contas bancárias, contatos de departamento, documentos anexos, foto, data importante | Alta (referências) / Média (demais) |
| Lançamento | `notes` (observações), nº doc. e obs. na transferência | **Alta** (o MCC também tem) |
| Centro de custo | aplica a despesa/receita, projeção de receita | **Alta** (o MCC também tem) |
| Cadastro rápido | flag "precisa revisar" em cadastro criado dentro do lançamento | Média |
| Entidade / moeda | bairro, complemento, país; casas decimais e ativa por moeda | Baixa |
| Vendas | devolução, status "liquidado" | Média |
| Produtos | perfil tributário | Quando vier NF-e |
| Rural | **safra** (plantio, previsão, produtividade esperada × real) e **ativos/máquinas** | Média |
| API REST (Sanctum) com permissão por módulo | base para mobile/nuvem | Fase futura |
| Acesso externo (Cloudflare Tunnel + Access, sócios só leitura) | | Fase futura (versão nuvem) |
| RH, agenda/tarefas, cofre de senhas | decisão do ROADMAP: **fora** | reavaliar só sob demanda |

## 6. O que o Finora já tem além dos outros dois

Cartão de crédito com fatura · importação CSV/Excel além do OFX · conciliação com sugestão aprendida · regras
automáticas de categoria · metas · anexos · orçado × realizado · relatório IRPF · multimoeda com PTAX · DRE com
grupos · produção por lote · pecuária · estoque com custo médio · licenciamento Free/Plus/Pro · backup em nuvem ·
Finora Servidor (MariaDB) · atualizador com um clique.

---

## 7. Riscos e cuidados

- **Dados reais do MCC estão no servidor do fornecedor.** É preciso confirmar como exportar tudo: relatório de
  lançamentos "todo período / todas situações" por conta controle, cadastros e extratos. Fazer um teste de
  exportação antes de planejar o importador (b).
- **Credencial embutida no `mcc.exe`**: não usar. Vale avisar o fornecedor.
- `REAL` no clone → arredondamento ao converter para `Decimal`: conferir os saldos antes e depois da importação.
- `pessoa` como texto livre no MCC → duplicidades de contato. Prever uma tela de "mesclar contatos" ou uma revisão
  pós-importação.
- Senhas não migram: primeiro acesso com redefinição.
- Itens sem grupo da DRE: a DRE do Finora fica concentrada em "Outras" até o usuário reclassificar. Regras
  automáticas de categoria podem acelerar isso.

## 8. Próximo passo: plano de implementação (proposta de fases)

1. **Paridade MCC — núcleo de lançamentos**: periodicidades, baixa com valor/conta/obs., observações, exclusão
   "todas/todas em aberto", transferir para outra entidade, conta compartilhada e limite, centro aplica
   despesa/receita + projeção.
2. **Importador MCC**: (a) `mcc.db` do clone → Finora, com relatório de conferência de saldos; (b) planilhas
   exportadas do MCC original.
3. **Relatórios MCC**: pontualidade, comparativo de saldos, fechamento de caixa, saldos em data, fluxo e
   orçamento/projeção por centro, demonstrativo anual por pessoa/centro/conta, analítico com agrupamentos livres,
   cadastros, duplicata e recibo em 2 vias, CSV/TXT.
4. **Contatos completos** (MCC perfil + IgnControl crédito/referências).
5. **Módulos IgnControl restantes**: safra/ativos rurais, devolução em vendas.
6. **Piloto paralelo** (MCC e Finora lado a lado por 1 mês) e desligamento do MCC.
7. **Futuro**: API REST, nuvem, mobile.
