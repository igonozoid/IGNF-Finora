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
- **A decidir — como o app fala com o banco remoto**: celular não deve (nem consegue com segurança) falar
  direto com o MySQL, então o mobile exige uma **API** no servidor web (PHP, que a HostGator roda). O desktop
  poderia conectar direto no MySQL remoto, mas isso põe a senha do banco em cada instalação e a HostGator
  só libera MySQL remoto para IPs cadastrados. **Recomendação**: o desktop também usar a API — e o
  **Finora Servidor** (rede local, Fase E) falar o **mesmo protocolo** (HTTP/JSON). Assim um app só tem três
  modos de dados: este PC, rede local (Finora Servidor) e nuvem (API PHP), e o mobile reaproveita a API.

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
- [ ] Alembic no lugar do ajuste provisório de colunas em `init_db` (essencial para banco em rede)
- [ ] Ligar chaves estrangeiras no SQLite (`PRAGMA foreign_keys=ON`)
- [ ] Log de erros em arquivo + janela amigável de "algo deu errado"
- [ ] Testes de tela no repositório (pytest-qt) e testes rodando no GitHub (Windows e Linux),
      também contra PostgreSQL/MariaDB
- [x] Ajustar `core/licensing.FEATURES` às edições novas (Plus com tudo; 3 usuários e 10 entidades)

## Fase B — Completar o básico (Free)

- [ ] Editar perfil (nome, moeda) depois do assistente
- [ ] Cartão de crédito com fechamento, vencimento e fatura
- [ ] Relatórios: extrato por conta, por categoria, por contato, inadimplência
- [ ] Lançamentos: filtro por conta/categoria, ordenar colunas, duplicar, pagar vários de uma vez
- [ ] Recibo imprimível (do IgnControl)
- [ ] Busca global (Ctrl K) e seletor de período no cabeçalho (do mockup)
- [ ] Contatos ampliados (endereço, dados bancários)
- [ ] Fontes IBM Plex embutidas

## Fase C — Recursos das edições pagas (hoje só com cadeado)

- [ ] Exportar Excel/PDF, importar OFX + conciliação, orçado x realizado, anexos, backup em nuvem
- [ ] Multimoeda, centros de custo, autopreencher CPF/CNPJ
- [ ] App de licenças (repositório privado)

## Fase E — Multiusuário, multiempresa e rede local (Plus/Pro)

- [ ] Usuários, login e troca de usuário (mockup: tela de login)
- [ ] Várias entidades e escolha de entidade (mockup: "Escolha a entidade"); isolamento por `entity_id`
- [ ] Permissões por módulo e entidade: nenhum / leitura / total (mockup: Administração › Permissões)
- [ ] Histórico de alterações / auditoria: quem fez o quê e quando (mockup: Log de auditoria)
- [ ] Limites por edição (usuários e entidades) checados em `core/licensing.allowed()`
- [ ] **Rede local**: escolher "este PC" ou "rede" no primeiro uso/Configurações.
  - Não usar o arquivo SQLite em pasta compartilhada (corrompe com 2 PCs gravando).
  - **Decidido: "Finora Servidor"** — um PC (Windows ou Linux) roda o Finora em modo servidor, dono do
    banco; os outros PCs falam com ele pela rede. Mais simples para o cliente (não instala banco à parte) e
    as permissões ficam garantidas no servidor.
  - Os `services/` passam a poder rodar no servidor; a UI fala com eles localmente (modo "este PC") ou
    pela rede (modo LAN).
- [ ] Indicador de conexão na barra de status (mockup: "Conectado · …", "usuários online")

## Fase D — Distribuição

- [ ] Pacote portátil Windows (PyInstaller, `.zip`)
- [ ] Pacote portátil Linux (`.tar.gz`)
- [ ] Pacote macOS (sem assinatura, com aviso)
- [ ] Como o usuário recebe atualizações
- [ ] Termos de uso e aviso de privacidade (LGPD)
- [ ] (Depois) instalador e assinatura digital

## Futuro (a estudar)

- [ ] Modo nuvem: o mesmo app desktop com o banco remoto (HostGator, PHP + MySQL), por mensalidade
- [ ] API no servidor web (PHP), com o mesmo protocolo do Finora Servidor (ver "A decidir" acima)
- [ ] App mobile simplificado, conectado à API do servidor web
