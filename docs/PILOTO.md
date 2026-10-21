# Piloto: do MCC para o Finora (versão 0.6.0)

Roteiro das issues #62 (instalar), #63 (importação inicial e conferência assinada) e #64 (um mês em paralelo).
O banco fica no **Finora Servidor** (MariaDB em `10.0.0.99:3306`); o Finora vai instalado em cada PC.

## 1. Antes de começar (responsável)

- [ ] Backup do servidor: em qualquer PC já conectado, **Configurações › Backup › Fazer backup agora** (gera um
      `.db` com tudo o que está no servidor). Guarde fora do computador.
- [ ] Combine com a equipe o dia: no dia da importação ninguém lança nada no MCC depois da exportação.

## 2. Instalar o Finora 0.6.0 em cada PC (#62)

1. Feche o Finora, se estiver aberto (inclusive o ícone ao lado do relógio: botão direito › Sair).
2. Baixe `IGNF-Finora-0.6.0-windows.zip` em <https://github.com/igonozoid/IGNF-Finora/releases/tag/v0.6.0>.
3. Descompacte em `C:\IGNF-Finora` (não use "Arquivos de Programas"). Se já houver um Finora ali, descompacte
   **por cima**: a pasta `data` fica intacta. Quem já tem a 0.5.x pode também usar o aviso de versão nova do app.
4. Abra o `IGNF-Finora.exe`. Na primeira vez em cada PC: aceite os termos.
5. **Licença Pro** (em cada PC): Configurações › Edição › **Ativar licença** › escolha `IGNF-Finora-Pro.lic`.
6. **Servidor**: Configurações › **Onde ficam os dados** › **Num servidor da rede** › endereço `10.0.0.99`,
   porta `3306` e a senha do servidor › **Testar conexão** › **Usar este servidor**. O Finora reabre e a barra
   de baixo mostra "Dados no Finora Servidor 10.0.0.99:3306".
7. **Usuários**: as planilhas do MCC não trazem os usuários. Em **Administração › Usuários**, crie um para cada
   pessoa da equipe, com as permissões (Financeiro, Contatos, Relatórios…) e as entidades que ela vê.

## 3. Exportar do MCC original (no dia da importação)

Para a conta controle (empresa), período **01/01/2000 a 31/12/2030**, situação **Todas**, em **CSV**, numa pasta só:

| Relatório no MCC | Arquivo |
|---|---|
| Relatório Analítico — Despesas (descritivo) | `analitico-despesas.csv` |
| Relatório Analítico — Receitas (descritivo) | `analitico-receitas.csv` |
| Saldo de contas | `contas.csv` |
| Extrato de cada conta bancária e Extrato do caixa interno | `extrato-<conta>.csv` |
| Clientes e Fornecedores | `clientes.csv`, `fornecedores.csv` |

Anote na tela do MCC o **saldo de cada conta** e os totais **a pagar** e **a receber** do dia.

## 4. Importar e conferir (#63) — só num PC

1. Configurações › **Trazer dados do MCC** › **Planilhas do MCC (CSV)…** › selecione **todos** os CSV da pasta.
2. Digite o **nome da empresa**, o tipo (**Pessoa jurídica**) e o **CNPJ**.
3. **Ver prévia** (nada é gravado). Confira nas notas:
   - "Saldo de <conta>: MCC R$ … · montado R$ …" — tem de ser igual em todas as contas;
   - datas de pagamento achadas, transferências e séries de parcelas reagrupadas;
   - avisos (movimentações antigas de um lado só ficam de fora, como no saldo do próprio MCC).
4. A tabela da conferência compara saldos e totais. Se algo **não bater**, o botão Importar fica travado: pare e
   chame o suporte com a planilha da conferência.
5. **Exportar conferência** (Excel) › imprima › o **responsável financeiro assina** (é a conferência assinada).
6. **Importar**. O Finora faz um backup do servidor antes (`antes-de-importar-….db`, em Configurações › Backup) e
   importa tudo ou nada. Depois **Concluir**.
7. Arrumação depois da importação (pode ser nos dias seguintes):
   - **Contatos › A revisar**: confira os criados a partir do nome solto; junte os repetidos com **Mesclar…**.
   - **Categorias › Reclassificar…**: tire os itens de "Despesas do MCC" / "Receitas do MCC" e ponha nos grupos
     certos da DRE (o Finora sugere).
   - Confira os relatórios que vocês usam no MCC: **Relatórios** (Fluxo por centro, Saldos em uma data, Analítico
     agrupado…) e o **Dashboard › Caixa × competência**.

## 5. Um mês em paralelo (#64)

- O **MCC continua sendo o oficial**: os lançamentos do dia a dia seguem nele.
- **Toda semana**: exporte de novo os mesmos CSV e importe de novo na mesma empresa (passos 3 e 4). A reimportação
  **atualiza** o que já veio (o que foi pago, valores, datas), cria o que é novo e manda para a lixeira o que foi
  excluído no MCC — sem duplicar. Confira de novo a prévia (saldos iguais) e guarde a conferência.
- Digite o **nome da empresa exatamente igual** ao da primeira importação: é por ele que o Finora reconhece que é
  a mesma empresa (a prévia avisa "já foi importada das planilhas: o que já veio será atualizado"). Se esse aviso
  não aparecer, pare: o nome está diferente e a importação criaria outra entidade.
- **Não lance** na entidade importada durante o paralelo: o que for digitado direto no Finora não vem do MCC e
  ficaria em dobro quando o mesmo lançamento chegar pela reimportação. Para treinar, use outra entidade
  (Administração › Entidades › nova, ex.: "Treino").
- Anote o que faltar ou estranhar (tela, relatório, número) para virar ajuste (#65).

## 6. Virada (#66)

No fechamento do mês: última exportação e importação, conferência assinada, e a partir daí os lançamentos passam a
ser feitos **só no Finora**. O MCC fica só para consulta (exporte tudo e guarde).

## Se algo der errado

- **Voltar ao estado de antes de uma importação**: Configurações › Backup › escolha `antes-de-importar-….db` ›
  Restaurar (no servidor, troca os dados do servidor; todos os PCs veem o resultado).
- O servidor também guarda um backup diário (ver `docs/SERVIDOR-UBUNTU.md`).
- Finora abre "em segundo plano" ao clicar de novo: já está aberto; a 0.5.1 em diante traz a janela para a frente.
