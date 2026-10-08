# Ajuda do IGNF Finora

## Primeiros passos {#inicio}

O Finora organiza o dinheiro que entra e sai: contas a pagar e a receber, saldo de cada conta, cartão de
crédito e relatórios simples, como a DRE pessoal.

1. **Cadastre suas contas** (banco, carteira, cartão de crédito, investimentos) em **Contas**, com o saldo de hoje.
2. **Lance o que entra e sai** em **Lançamentos** (botão **Novo lançamento** ou **Ctrl+N**). Contas fixas, como
   aluguel, podem se repetir sozinhas todo mês; compras parceladas viram as parcelas certas.
3. **Marque como pago** quando pagar: o saldo da conta se ajusta.
4. Acompanhe no **Dashboard** e nos **Relatórios**.

Dica: passe o mouse sobre os ícones **?** para ver explicações rápidas em cada tela.

## Dashboard {#dashboard}

O resumo do mês: saldo em contas, o que vence nos próximos 30 dias (a receber e a pagar), a sobra do mês,
gráfico de entradas e saídas dos últimos 6 meses, contas que vencem nos próximos 7 dias, maiores despesas e
**metas**.

- **Metas e objetivos**: reserva de emergência, viagem, carro… Em **Gerenciar**, diga quanto quer juntar e até
  quando. O progresso pode ser o saldo de uma conta (ex.: a poupança) ou um valor que você soma em **Guardei mais**.
  O Finora mostra quanto falta e quanto guardar por mês.
- O mês de referência é o do alto da tela (setas ‹ ›).

## Lançamentos {#entries}

Receitas, despesas e transferências entre suas contas.

- **Filtros**: Todos, A receber, A pagar, Atrasados, Pagos. Em **Mais filtros**: trimestre, semestre, ano, todo o
  período, por vencimento, competência ou pagamento, tipo, contato e centro de custo.
- **Repetir**: todo mês, semana, ano… ou **parcelar** (o valor é dividido nas parcelas).
- **Cartão de crédito**: compras no cartão entram na fatura do mês certo, conforme o dia de fechamento.
- **Recibo**: abra um lançamento e clique em **Recibo** para imprimir ou salvar em PDF (2 vias).
- **Comprovantes** (edições pagas): anexe a foto ou o PDF do boleto ou da nota.
- **Regras automáticas**: ao digitar a descrição de um lançamento novo, a categoria e o contato podem vir
  preenchidos (veja **Categorias › Regras automáticas**).
- **Excluir**: o lançamento vai para a **Lixeira** (ícone da lixeira na barra). Logo depois de excluir aparece
  **Desfazer**. Na lixeira dá para restaurar quando quiser; nada é apagado de verdade.
- **Imprimir/Exportar**: a lista como está na tela (com os filtros).

## Contas {#accounts}

Banco, carteira, cartão de crédito e investimentos. O saldo inicial é o saldo no dia em que começou a usar o
Finora. Cartões têm dia de fechamento, dia de vencimento e limite. Conta que não usa mais pode ser **inativada**
(o histórico continua nos relatórios).

## Categorias {#categories}

Grupos de gasto e de ganho, em árvore. Cada grupo pertence a uma linha da **DRE pessoal** (Moradia,
Alimentação, Transporte, Saúde, Educação, Lazer, Outras despesas, Investimentos/Reserva).

**Regras automáticas**: "se a descrição contém *uber* → Transporte". Valem para lançamento novo, para o extrato
importado e, com o botão **Aplicar aos lançamentos sem categoria**, para o que já foi lançado sem categoria.
Não diferenciam acentos nem maiúsculas; se duas regras servirem, vale a de texto mais longo.

## Centros de custo {#cost_centers}

Um segundo jeito de agrupar, além da categoria: Casa, Carro, Viagem, Obra… Útil para saber quanto custou um
projeto ao todo. Edições pagas.

## Contatos {#contacts}

Quem você paga e quem te paga, com CPF/CNPJ. Os contatos digitados num lançamento aparecem aqui sozinhos.
O CPF/CNPJ é usado no **recibo** e no relatório de **Imposto de Renda**. Nas edições pagas, o CNPJ preenche
nome e endereço sozinho.

## Conciliação {#reconcile}

Confere o extrato do banco com o que você lançou (edições pagas).

1. Baixe o extrato ou a fatura no site ou app do banco: **OFX**, **CSV** ou **Excel (.xlsx)**.
2. Escolha a conta e clique em **Importar extrato**. Com planilha, confira as colunas na prévia.
3. Para cada linha: **Confirmar** o lançamento sugerido, **Criar** um novo ou **Ignorar**.

Importar o mesmo período de novo não duplica nada.

## Relatórios {#reports}

DRE pessoal, fluxo de caixa, extrato por conta, por categoria, por contato, por centro de custo, a pagar e a
receber (com período personalizado), inadimplência, comparativo mês a mês, evolução do patrimônio, entradas e
saídas por mês, analítico, orçado x realizado e **Imposto de Renda**.

- **Imprimir** (todas as edições): prévia, retrato ou paisagem, com o cabeçalho da entidade (nome, endereço e
  logotipo, cadastrados em Administração › Entidades).
- **Excel e PDF**: edições pagas.
- **Gráfico**: alguns relatórios mostram um gráfico, que também sai na impressão. Desmarque **Gráfico** para
  esconder.
- **Imposto de Renda**: rendimentos por fonte pagadora, pagamentos de saúde e educação com CPF/CNPJ e saldos em
  31/12. É um resumo para conferir: as regras de dedução são da Receita Federal.

## Administração {#admin}

Edições pagas: **entidades** (cada pessoa ou empresa com dados separados), **usuários** com senha,
**permissões** por módulo (sem acesso, só consulta, total) e **histórico de alterações** (quem mudou o quê e
quando).

## Configurações {#settings}

Seus dados, moeda, aparência (tema claro/escuro, menu lateral ou em abas), **segurança** (PIN para abrir o
Finora), **lembretes de vencimento**, **backup**, onde ficam os dados (este computador ou servidor da rede),
licença e **Sobre**.

**Lembretes**: o Finora avisa no canto da tela as contas atrasadas e as que vencem em breve, uma vez por dia.
Marque **continuar ao lado do relógio** para ser avisado mesmo com a janela fechada.

**Atalhos**: crie atalhos na Área de trabalho e no menu Iniciar e escolha abrir o Finora junto com o Windows.

## Backup {#backup}

O Finora faz um backup automático por dia (guarda os últimos 7) em `data/backups`. Em **Configurações › Backup**
você faz um backup agora, restaura um backup e, nas edições pagas, manda uma cópia para uma pasta de nuvem
(OneDrive, Google Drive, Dropbox) ao fechar.

**Importante:** guarde de vez em quando uma cópia fora do computador (pendrive ou nuvem).

## Rede local {#rede}

Nas edições Plus e Pro, vários computadores podem usar os mesmos dados: um deles (ou um servidor Linux) guarda
o banco e os outros se conectam em **Configurações › Onde ficam os dados**.

## Atalhos de teclado {#atalhos}

| Tecla | O que faz |
|---|---|
| Ctrl+N | Novo lançamento |
| Ctrl+K | Procurar (em todos os meses) |
| Ctrl+T | Tema claro/escuro |
| Ctrl+1 … Ctrl+9 | Ir para as seções do menu |
| F1 | Esta ajuda |

## Algo deu errado? {#problemas}

- Em **Ajuda › Enviar relatório de problema** o Finora junta as informações técnicas (versão, sistema e o
  registro de erros, **sem os seus dados financeiros**) num arquivo .zip e abre o e-mail do suporte. É só anexar
  o arquivo.
- Seus dados ficam na pasta `data`, ao lado do programa. Os backups ficam em `data/backups`.
- Contato: veja **Configurações › Sobre**.
