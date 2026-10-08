# Edições

A **Free** é para uma pessoa num computador. **Plus** e **Pro** têm todos os recursos; a diferença entre elas é
só a quantidade de usuários e de entidades.

**Como construímos:** primeiro o app completo (o que Plus/Pro terão); depois a Free é "capada" marcando os
recursos pagos em `core/licensing.py` (`allowed()`), que aparecem com cadeado e convite para upgrade.

| Recurso | Free | Plus | Pro |
|---|---|---|---|
| Usuários | 1 | até 3 | ilimitados |
| Entidades (PF, MEI, empresa) | 1 | até 10 | ilimitadas |
| Onde ficam os dados | este PC | este PC **ou** rede local¹ | este PC **ou** rede local¹ |
| Moedas | 1 | várias | várias |
| Contas | até 3 | ilimitadas | ilimitadas |
| Lançamentos, recorrência, parcelamento, transferências | ✓ | ✓ | ✓ |
| Categorias, DRE pessoal, fluxo de caixa, Dashboard | ✓ | ✓ | ✓ |
| Backup e restauração local | ✓ | ✓ | ✓ |
| Recibo imprimível e em PDF | ✓ | ✓ | ✓ |
| Imprimir relatórios e listas (prévia, retrato ou paisagem, cabeçalho da entidade) | ✓ | ✓ | ✓ |
| Login, permissões por módulo e histórico de alterações | | ✓ | ✓ |
| Importação OFX | | ✓ | ✓ |
| Anexos de comprovantes | | ✓ | ✓ |
| Orçamento (orçado x realizado) | | ✓ | ✓ |
| Exportação Excel/PDF | | ✓ | ✓ |
| Backup automático em pasta de nuvem (OneDrive, Google Drive, Dropbox) | | ✓ | ✓ |
| Centros de custo | | ✓ | ✓ |
| Autopreencher pelo CNPJ e endereço pelo CEP | | ✓ | ✓ |
| Fechamento de período | | ✓ | ✓ |
| Conciliação com o extrato do banco | | ✓ | ✓ |

¹ **Rede local (LAN)**: um PC vira o **Finora Servidor** (Windows ou Linux): o Finora baixa do site oficial e
cuida de um banco MariaDB portátil, e os outros PCs, cada um com o Finora, se conectam a ele (Configurações ›
Onde ficam os dados). Não é um arquivo numa pasta compartilhada (o SQLite corrompe nesse uso).
Quem já tem um servidor Linux na rede pode usar o MariaDB dele: ver `docs/SERVIDOR-UBUNTU.md`.
Ver `docs/ROADMAP.md`, Fase E.

**Futuro (a estudar):**
- **Nuvem** por assinatura mensal: o mesmo app desktop, com os dados do cliente num banco remoto
  (hospedagem própria com PHP e MySQL).
- **Mobile**: app simplificado que conecta ao servidor web.
