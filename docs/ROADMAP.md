# Roadmap até a maturidade

As 8 etapas do CLAUDE.md estão concluídas (mais a 3b). Este documento lista o que falta para o Finora ser
considerado maduro, em fases. Cada item vira um passo pequeno, testado e com commit próprio.

## Decisões

### Edições (detalhes em `docs/EDICOES.md`)
- **Free**: 1 usuário, 1 moeda, 1 entidade, banco local neste PC.
- **Plus e Pro**: todos os recursos (multimoeda, multiusuário, multiempresa…). Plus limita a até **3 usuários
  e 10 entidades**; Pro é ilimitado.
- **Onde ficam os dados (Plus/Pro)**: o cliente escolhe — **neste PC** (banco local) ou **rede local**
  (vários PCs, Finora instalado em cada um).
- **Versão "web" (futuro, mensalidade)**: é **o mesmo app desktop**, só que com o banco **remoto** (nuvem),
  na hospedagem própria (HostGator: PHP + MySQL). Não é um site.
- **Versão mobile (futuro)**: app **simplificado** que conecta ao servidor web.
- **Decidido (06/10/2026) — servidor de banco**: na rede local, o **Finora Servidor** sobe um **MariaDB
  portátil** num PC e os outros PCs conectam direto nele (o código já é compatível: SQLAlchemy + Alembic).
  A nuvem segue a mesma ideia com o MySQL/MariaDB da HostGator. Trocas aceitas: as permissões são conferidas
  em cada PC (não no servidor) e a senha do banco fica em cada instalação. O **mobile**, quando vier, vai
  precisar de uma API própria no servidor web.

### Distribuição
- **App portátil, sem instalador** (instalador fica para depois, se fizer sentido).
- **Tudo numa pasta só** (modo local): programa, banco, backups, preferências e licença.
  - Windows: `C:\IGNF-Finora\` (sugestão; vale onde o usuário descompactar, desde que dê para gravar).
  - Linux: pasta portátil (`.tar.gz`), sugestão `~/IGNF-Finora/`.
  - macOS: o `.app` não pode guardar dados dentro (assinatura/somente leitura), então os dados ficam em
    `~/IGNF-Finora/`.
  - Se a pasta do programa não permitir gravar (ex.: "Arquivos de Programas"), o app avisa e usa
    `~/IGNF-Finora/`.
- **Sem assinatura digital por enquanto**: o Windows (SmartScreen) e o macOS (Gatekeeper) vão mostrar aviso.
- **Prioridade de plataforma**: 1º Windows, 2º Linux, 3º macOS.
- **Emissão de licenças** vai para um **app separado, em repositório privado** (chave privada + cadastro de
  clientes), reaproveitando `core/license_key.py`. Nunca é distribuído junto com o Finora.

### Do IgnControl
O mockup se inspira no [IgnControl](https://github.com/igonozoid/IgnControl). Trazemos: login, usuários,
permissões por módulo e auditoria (para Plus/Pro), escolha de entidade, recibo imprimível, relatórios por
contato e por centro de custo. Não trazemos o acesso externo por PWA do desktop (isso é assunto da versão web).

## Fase A — Fundação (antes de outras pessoas testarem)

- [x] Pasta de dados portátil (regra acima) e preferências/licença em `data/finora.ini` (sair do Registro)
- [x] Python 3.12 no `.venv` e `requires-python >= 3.12`
- [x] Alembic no lugar do ajuste provisório de colunas em `init_db` (essencial para banco em rede)
- [x] Ligar chaves estrangeiras no SQLite (`PRAGMA foreign_keys=ON`)
- [x] Log de erros em arquivo + janela amigável de "algo deu errado"
- [x] Testes de tela no repositório (pytest-qt) e testes rodando no GitHub (Windows e Linux)
- [x] Testes também contra o banco do Finora Servidor (quando ele existir, Fase E)
- [x] Ajustar `core/licensing.FEATURES` às edições novas (Plus com tudo; 3 usuários e 10 entidades)

## Fase B — Completar o básico (Free)

- [x] Editar perfil (nome, moeda) depois do assistente
- [x] Cartão de crédito com fechamento, vencimento e fatura
- [x] Relatórios: extrato por conta, por categoria, por contato, inadimplência
- [x] Lançamentos: filtro por conta/categoria, ordenar colunas, duplicar, pagar vários de uma vez
- [x] Recibo imprimível (do IgnControl)
- [x] Busca global (Ctrl K) e seletor de período no cabeçalho (do mockup)
- [x] Contatos ampliados (endereço, dados bancários)
- [x] Fontes IBM Plex embutidas

## Fase C — Recursos das edições pagas

Estratégia: construir tudo completo e depois "capar" a Free com `licensing.allowed()` (cadeado + convite).
Ordem de implementação:

- [x] Exportar Excel/PDF: lançamentos e todos os relatórios
- [x] Importar OFX (extrato do banco) sem duplicar
- [x] Conciliação: casar linhas do extrato com lançamentos, sugerir, criar o que falta (mockup: Conciliação)
- [x] Centros de custo: cadastro, campo no lançamento, relatório por centro de custo (mockup + IgnControl)
- [x] Orçado x realizado: orçamento mensal por categoria e por centro de custo, com alerta de estouro
- [x] Anexos de comprovantes nos lançamentos (guardados dentro do banco: vão no backup e no modo rede)
- [x] Multimoeda: moedas, cotações com histórico por data (manual ou PTAX), contas em outra moeda, transferência com câmbio
- [x] Autopreencher CNPJ (BrasilAPI) e endereço pelo CEP; CPF não tem consulta pública (LGPD)
- [x] Backup automático ao fechar numa pasta de nuvem (OneDrive, Google Drive, Dropbox), últimos 14 dias
- [x] Do IgnControl: fechamento de período (trava lançamentos até uma data)
- [x] Do IgnControl: previsão de caixa dia a dia (pior saldo projetado) e relatório analítico
- [x] App de licenças: repositório privado `igonozoid/IGNF-Finora-Licencas` (pasta `../IGNF-Finora-Licencas`)

Do IgnControl **não** trazemos: estoque, vendas, RH, rural, agenda de tarefas e cofre de senhas — fogem de
finanças pessoais. Podem virar módulos opcionais no futuro.

## Fase E — Multiusuário, multiempresa e rede local (Plus/Pro)

- [x] Usuários, login e troca de usuário (mockup: tela de login)
- [x] Várias entidades e escolha de entidade (mockup: "Escolha a entidade"); isolamento por `entity_id`
- [x] Permissões por módulo e entidade: nenhum / leitura / total (mockup: Administração › Permissões)
- [x] Histórico de alterações / auditoria: quem fez o quê e quando, antes/depois (mockup: Log de auditoria)
- [x] Tela Administração (mockup): usuários, permissões, entidades, fechamento de período, auditoria
- [x] Limites por edição (usuários e entidades) checados em `core/licensing.allowed()`
- [x] **Rede local** (Configurações › Onde ficam os dados): neste computador, num servidor da rede, ou este
  computador é o servidor (Windows testado; Linux pelo pacote oficial, a testar num PC Linux de verdade).
  - Não usar o arquivo SQLite em pasta compartilhada (corrompe com 2 PCs gravando).
  - **Finora Servidor**: um PC (Windows ou Linux) roda um MariaDB portátil cuidado pelo Finora (iniciar,
    parar, criar o banco e o usuário, mostrar o endereço para os outros PCs). Os outros PCs apontam para ele
    em Configurações › Onde ficam os dados.
  - Levar os dados deste PC para o servidor (cópia completa) e backup do servidor para um arquivo .db.
- [x] Indicador de conexão na barra de status (mockup: "Conectado · …"); falta "usuários online"

## Fase D — Distribuição

- [x] Pacote portátil Windows (PyInstaller, `.zip`): `python tools/build.py` (testa o executável antes)
- [x] Pacote portátil Linux (`.tar.gz`): mesmo script; o GitHub gera os dois em Actions › Pacotes
- [ ] Pacote macOS (sem assinatura, com aviso)
- [x] Atualizações: aviso de versão nova (GitHub Releases, 1x por dia) + LEIA-ME de como atualizar mantendo `data`
- [x] Atualizar com um clique (baixa, confere SHA-256, troca o programa e guarda o antigo; `data` intacta)
- [x] Atalhos opcionais (Área de trabalho, menu Iniciar, abrir com o sistema) — o app continua portátil
- [x] Ajuda (F1) por tela e "Enviar relatório de problema"
- [x] Termos de uso e aviso de privacidade (LGPD): aceite na 1ª abertura e em Configurações › Sobre (revisar com advogado)
- [ ] Assinatura digital: build pronto (`FINORA_SIGN_PFX`), falta comprar o certificado (ver `docs/ASSINATURA.md`)

## Fase F — Maturidade (out/2026)

- [x] Impressão padronizada de todos os relatórios e listas (prévia, retrato/paisagem, cabeçalho da entidade)
- [x] Lixeira: excluir não apaga do banco; Desfazer e restaurar
- [x] Regras automáticas de categoria (lançamento novo, extrato e "aplicar aos sem categoria")
- [x] Relatório Imposto de Renda (rendimentos, saúde/educação com CPF/CNPJ, saldos em 31/12)
- [x] Importar extrato/fatura em CSV e Excel (com prévia das colunas)
- [x] Lembretes de vencimento (aviso do sistema, ícone ao lado do relógio)
- [x] Metas e objetivos no Dashboard
- [x] Gráficos nos relatórios, também na impressão

## Futuro (a estudar)

- [ ] Modo nuvem: o mesmo app desktop com o banco remoto (HostGator, PHP + MySQL), por mensalidade
- [ ] API no servidor web para o app mobile
- [ ] App mobile simplificado, conectado à API do servidor web
