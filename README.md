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

- 🔒 **Local por padrão** — banco SQLite na pasta do app, sem servidor, sem cadastro online
- 🖧 **Rede local nas edições pagas** — vários PCs usando os mesmos dados, cada um com seu login
- 🌗 **Tema claro e escuro** com acento âmbar
- ⚡ **Interface condensada**, feita para teclado e mouse
- 🧾 **Pronto para crescer** — de uma pessoa até vários usuários e entidades (PF, MEI, empresa)

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
| Usuários | 1 | limitado | ilimitados |
| Entidades (PF, MEI, empresa) | 1 | limitado | ilimitadas |
| Dados neste PC ou em rede local | só neste PC | ✅ | ✅ |
| Moedas | 1 | várias | várias |
| Contas | até 3 | ilimitadas | ilimitadas |
| Lançamentos, recorrência, parcelamento | ✅ | ✅ | ✅ |
| Dashboard, DRE pessoal e fluxo de caixa | ✅ | ✅ | ✅ |
| Login, permissões e histórico de alterações | — | ✅ | ✅ |
| Importação OFX, anexos, orçamento, Excel/PDF | — | ✅ | ✅ |
| Backup em nuvem, centros de custo, autopreencher CPF/CNPJ | — | ✅ | ✅ |

Plus e Pro têm os mesmos recursos; muda só a quantidade de usuários e entidades.

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

## Licenças (para quem vende)

O app confere a chave **offline**, com assinatura Ed25519: ele só tem a chave pública
(`src/finora/core/licensing.py`). A chave privada, que emite licenças, fica fora do Git, em
`%USERPROFILE%\.ignf-finora\license_private.pem` — **guarde uma cópia em lugar seguro**.

```powershell
python tools/license_tool.py issue --edition plus --name "Maria Silva" --days 365   # chave anual
python tools/license_tool.py issue --edition pro --name "João Souza"                # sem vencimento
python tools/license_tool.py check FNR1-XXXXX-...                                    # conferir uma chave
```

Cada chave emitida fica registrada em `%USERPROFILE%\.ignf-finora\licencas_emitidas.csv`.
O cliente cola a chave em **Configurações › Sua edição**. Licença vencida volta para a Free sem perder dados.

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
├── tools/                # license_tool.py (emissão de licenças)
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
- [x] Primeiro uso: assistente com 1ª conta e categorias padrão
- [x] Cadastros: contas e categorias (árvore da DRE, ativar/inativar)
- [x] Lançamentos com recorrência, parcelamento e transferência
- [x] Dashboard
- [x] Contatos: cadastro PF/PJ com CPF/CNPJ validado e papéis
- [x] Relatórios: DRE pessoal e fluxo de caixa
- [x] Backup e restauração (manual, restauração segura e automático diário)
- [x] Licenciamento Free / Plus / Pro (chave offline assinada)
- [ ] Instalador Windows (PyInstaller + Inno Setup)

## Licença

© 2026 IGNF. Todos os direitos reservados. A edição Free é gratuita para uso pessoal.
