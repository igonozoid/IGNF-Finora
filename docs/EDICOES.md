# Edições

A **Free** é para uma pessoa num computador. **Plus** e **Pro** têm todos os recursos; a diferença entre elas é
só a quantidade de usuários e de entidades.

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
| Login, permissões por módulo e histórico de alterações | | ✓ | ✓ |
| Importação OFX / conciliação | | ✓ | ✓ |
| Anexos de comprovantes | | ✓ | ✓ |
| Orçamento (orçado x realizado) | | ✓ | ✓ |
| Exportação Excel/PDF | | ✓ | ✓ |
| Backup automático em nuvem | | ✓ | ✓ |
| Centros de custo | | ✓ | ✓ |
| Autopreencher CPF/CNPJ | | ✓ | ✓ |

¹ **Rede local (LAN)**: um PC roda o **Finora Servidor** (Windows ou Linux) e os outros PCs, cada um com o
Finora instalado, se conectam a ele. Não é um arquivo numa pasta compartilhada (o SQLite corrompe nesse uso).
Ver `docs/ROADMAP.md`, Fase E.

**Futuro (a estudar):**
- **Nuvem** por assinatura mensal: o mesmo app desktop, com os dados do cliente num banco remoto
  (hospedagem própria com PHP e MySQL).
- **Mobile**: app simplificado que conecta ao servidor web.
