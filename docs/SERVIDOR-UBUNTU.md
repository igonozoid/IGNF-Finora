# Finora em rede com um servidor Ubuntu

Para quem já tem um computador Linux ligado o tempo todo na rede (Ubuntu Server ou Desktop). Nele fica só o
**banco de dados**; o Finora continua instalado nos PCs (Windows ou Linux) de quem usa.

## 1. No servidor (uma vez)

Copie o script `tools/servidor-ubuntu.sh` para o servidor (pendrive, `scp` ou baixando do GitHub) e rode:

```bash
sudo bash servidor-ubuntu.sh
```

No fim ele mostra **endereço, porta e senha**. A senha fica guardada em `/root/finora-servidor.txt`
(`sudo cat /root/finora-servidor.txt`). Pode rodar o script de novo a qualquer momento: ele não apaga nada e
mantém a mesma senha.

O que o script faz: instala o MariaDB do Ubuntu (`apt`), libera a rede (porta 3306) e comprovantes de até
10 MB, cria o banco e o usuário `finora`, libera a porta no firewall (`ufw`) só para a rede local e agenda um
backup diário em `/var/backups/finora` (últimos 14 dias).

## 2. Em cada PC com o Finora (Plus ou Pro)

1. Configurações › **Onde ficam os dados** › **Num servidor da rede**.
2. Endereço, porta (3306) e senha mostrados pelo script › **Testar conexão** › **Usar este servidor**.
3. No **primeiro** PC, o Finora pergunta se leva os dados dele para o servidor (que está vazio). Nos outros,
   os dados já estão lá.

O Finora reabre conectado; a barra de baixo mostra "Dados no Finora Servidor 10.0.0.99:3306".

## Dicas

- **Não conecta?** No servidor: `sudo systemctl status mariadb` e `sudo ss -ltnp | grep 3306` (deve mostrar
  `0.0.0.0:3306`). No firewall: `sudo ufw status`.
- **Backup manual** em qualquer PC conectado: Configurações › Backup › Fazer backup agora (gera um `.db` com os
  dados do servidor, que abre em qualquer Finora).
- **Restaurar no servidor** um backup diário do script:
  `gunzip -c /var/backups/finora/finora-AAAA-MM-DD.sql.gz | sudo mariadb finora`.
