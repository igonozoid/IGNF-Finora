<div align="center">

# 🪙 IGNF Finora

**Gestão financeira pessoal, simples de verdade.**
Desktop · Offline · Seus dados ficam no seu computador.

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-Qt%206-41CD52?logo=qt&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-local-003B57?logo=sqlite&logoColor=white)
![Status](https://img.shields.io/badge/status-em%20desenvolvimento-E09A0A)
![Plataforma](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)

</div>

---

## Sobre

O **IGNF Finora** é um aplicativo desktop para quem quer organizar o próprio dinheiro sem precisar entender de contabilidade. Linguagem simples, ajuda contextual em cada tela (ícone **?**) e relatórios no padrão de mercado — incluindo uma **DRE pessoal** que mostra, mês a mês, quanto entrou, quanto saiu e quanto sobrou.

- 🔒 **100% local** — banco SQLite na pasta do app, sem servidor, sem cadastro online
- 🌗 **Tema claro e escuro** com acento âmbar
- ⚡ **Interface condensada**, feita para teclado e mouse
- 🧾 **Pronto para crescer** — de pessoa física até várias entidades (PF + MEI)

## Funcionalidades

| Módulo | O que faz |
|---|---|
| **Dashboard** | Saldo total, a receber/pagar nos próximos 30 dias, resultado do mês, gráfico entradas × saídas |
| **Lançamentos** | Receitas, despesas e transferências · vencimento e pagamento · recorrência e parcelamento · nº do documento |
| **Contas** | Conta corrente, carteira, cartão de crédito, investimento · moeda por conta · ativar/inativar |
| **Categorias** | Plano de categorias em árvore, já ligado às linhas da DRE · categorias prontas no primeiro uso |
| **Contatos** | Cadastro único (pagador, recebedor, empresa) · PF/PJ · autopreencher por CPF/CNPJ* |
| **Relatórios** | DRE pessoal · fluxo de caixa projetado · extrato por conta · por categoria · orçado × realizado* |
| **Conciliação*** | Importa extrato OFX e casa com os lançamentos automaticamente |
| **Backup** | Cópia do banco com um clique e restauração |

<sub>* recursos das edições pagas — veja abaixo.</sub>

## Edições

| | **Free** | **Plus** | **Pro** |
|---|:---:|:---:|:---:|
| Lançamentos, recorrência, parcelamento | ✅ | ✅ | ✅ |
| Contas | até 3 | ilimitadas | ilimitadas |
| Dashboard e DRE pessoal | ✅ | ✅ | ✅ |
| Importação OFX e conciliação | — | ✅ | ✅ |
| Anexos de comprovantes | — | ✅ | ✅ |
| Orçamento (orçado × realizado) | — | ✅ | ✅ |
| Exportar Excel / PDF | — | ✅ | ✅ |
| Backup automático em nuvem | — | ✅ | ✅ |
| Multimoeda | — | — | ✅ |
| Várias entidades (ex.: PF + MEI) | — | — | ✅ |
| Centros de custo | — | — | ✅ |
| Autopreencher CPF/CNPJ | — | — | ✅ |

Detalhes em [`docs/EDICOES.md`](docs/EDICOES.md).

## Começando

**Requisitos:** Windows 10/11 · Python 3.12+ (oficial, de [python.org](https://www.python.org/downloads/))

```powershell
git clone https://github.com/igonozoid/IGNF-Finora.git
cd IGNF-Finora
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m finora
```

> 💡 Se o PowerShell bloquear o script de ativação:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Na primeira execução o banco é criado em `data/finora.db`.

## Estrutura do projeto

```
IGNF-Finora/
├── data/                 # banco SQLite (ignorado pelo Git)
├── docs/                 # especificações, edições, telas
├── src/finora/
│   ├── __main__.py       # ponto de entrada
│   ├── core/             # banco, licença, configurações
│   ├── models/           # tabelas (SQLAlchemy)
│   ├── services/         # regras de negócio (saldo, DRE, recorrência)
│   └── ui/               # janelas, telas e tema (PySide6)
├── tests/
├── CLAUDE.md             # guia para desenvolvimento assistido
└── pyproject.toml
```

## Stack

- **[PySide6](https://doc.qt.io/qtforpython-6/)** — interface nativa Qt 6
- **[SQLAlchemy 2](https://www.sqlalchemy.org/)** + **Alembic** — banco e migrações (SQLite hoje, MySQL/MariaDB amanhã sem reescrever)
- **[QtAwesome](https://github.com/spyder-ide/qtawesome)** — ícones Font Awesome
- **openpyxl** · **ofxparse** · **requests**

## Roadmap

- [x] Estrutura do projeto e banco local
- [x] Janela principal: menu lateral, tema claro/escuro
- [ ] Cadastros: contas, categorias (com padrão), contatos
- [x] Lançamentos com recorrência e parcelamento
- [ ] Dashboard
- [ ] Relatórios: DRE pessoal e fluxo de caixa
- [ ] Backup e restauração
- [ ] Licenciamento Free / Plus / Pro
- [ ] Instalador Windows (PyInstaller + Inno Setup)

## Licença

© 2026 IGNF. Todos os direitos reservados. A edição Free é gratuita para uso pessoal.
