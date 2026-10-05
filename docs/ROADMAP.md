# Roadmap até a maturidade

As 8 etapas do CLAUDE.md estão concluídas (mais a 3b). Este documento lista o que falta para o Finora ser
considerado maduro, em fases. Cada item vira um passo pequeno, testado e com commit próprio.

## Decisões de distribuição

- **App portátil, sem instalador** (instalador fica para depois, se fizer sentido).
- **Tudo numa pasta só**: programa, banco, backups, preferências e licença.
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
- Referência de origem: o mockup se inspira no [IgnControl](https://github.com/igonozoid/IgnControl). Trazemos
  o que serve a um app pessoal e local (recibo imprimível, relatórios por contato/centro de custo, histórico de
  alterações leve, entidades na Pro); não trazemos login/usuários/permissões, acesso em rede/PWA nem MySQL.

## Fase A — Fundação (antes de outras pessoas testarem)

- [ ] Pasta de dados portátil (regra acima) e preferências/licença em `data/finora.ini` (sair do Registro)
- [ ] Python 3.12 no `.venv` e `requires-python >= 3.12`
- [ ] Alembic no lugar do ajuste provisório de colunas em `init_db`
- [ ] Ligar chaves estrangeiras no SQLite (`PRAGMA foreign_keys=ON`)
- [ ] Log de erros em arquivo + janela amigável de "algo deu errado"
- [ ] Testes de tela no repositório (pytest-qt) e testes rodando no GitHub (Windows e Linux)

## Fase B — Completar o básico (Free)

- [ ] Editar perfil (nome, moeda) depois do assistente
- [ ] Cartão de crédito com fechamento, vencimento e fatura
- [ ] Relatórios: extrato por conta, por categoria, por contato, inadimplência
- [ ] Lançamentos: filtro por conta/categoria, ordenar colunas, duplicar, pagar vários de uma vez
- [ ] Recibo imprimível (do IgnControl)
- [ ] Histórico de alterações leve (do IgnControl, simplificado)
- [ ] Busca global (Ctrl K) e seletor de período no cabeçalho (do mockup)
- [ ] Contatos ampliados (endereço, dados bancários)
- [ ] Fontes IBM Plex embutidas

## Fase C — Recursos pagos (hoje só com cadeado)

- [ ] Plus: exportar Excel/PDF, importar OFX + conciliação, orçado x realizado, anexos, backup em nuvem
- [ ] Pro: multimoeda, várias entidades (PF + MEI), centros de custo, autopreencher CPF/CNPJ
- [ ] App de licenças (repositório privado)

## Fase D — Distribuição

- [ ] Pacote portátil Windows (PyInstaller, `.zip`)
- [ ] Pacote portátil Linux (`.tar.gz`)
- [ ] Pacote macOS (sem assinatura, com aviso)
- [ ] Como o usuário recebe atualizações
- [ ] Termos de uso e aviso de privacidade (LGPD)
- [ ] (Depois) instalador e assinatura digital
