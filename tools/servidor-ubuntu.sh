#!/usr/bin/env bash
# Prepara um Ubuntu (Server ou Desktop) como banco do IGNF Finora para a rede local.
#
# Uso (no servidor):   sudo bash servidor-ubuntu.sh
#   com senha escolhida: sudo FINORA_SENHA='minha-senha' bash servidor-ubuntu.sh
#
# O que faz (pode rodar de novo sem problema):
#   - instala o MariaDB do próprio Ubuntu (apt) e deixa ligado sempre que o servidor ligar;
#   - libera o acesso pela rede (porta 3306) e o tamanho dos comprovantes (até 10 MB);
#   - cria o banco "finora" e o usuário "finora" com uma senha gerada (guardada em /root/finora-servidor.txt);
#   - se o firewall (ufw) estiver ligado, libera a porta só para a rede local;
#   - agenda um backup diário do banco em /var/backups/finora (guarda os últimos 14).
# No fim mostra o endereço, a porta e a senha para configurar os PCs com o Finora
# (Configurações › Onde ficam os dados › Num servidor da rede).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Rode com sudo:  sudo bash $0"
    exit 1
fi

echo "== Instalando o MariaDB…"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mariadb-server >/dev/null

echo "== Configurando para a rede local…"
cat > /etc/mysql/mariadb.conf.d/60-finora.cnf <<'CNF'
# IGNF Finora: aceita os PCs da rede e comprovantes de até 10 MB
[mysqld]
bind-address         = 0.0.0.0
character-set-server = utf8mb4
collation-server     = utf8mb4_unicode_ci
max_allowed_packet   = 32M
CNF
systemctl enable mariadb >/dev/null 2>&1
systemctl restart mariadb

INFO=/root/finora-servidor.txt
if [ -n "${FINORA_SENHA:-}" ]; then                     # senha escolhida: sudo FINORA_SENHA='...' bash ...
    SENHA="$FINORA_SENHA"
elif [ -f "$INFO" ] && grep -q '^senha=' "$INFO"; then  # rodando de novo: mantém a mesma
    SENHA=$(grep '^senha=' "$INFO" | cut -d= -f2-)
else
    # (o "|| true" evita que o pipefail derrube o script quando o head fecha o tr)
    SENHA=$( (tr -dc 'abcdefghjkmnpqrstuvwxyz23456789' </dev/urandom || true) | head -c 12 \
             | sed 's/.\{4\}/&-/g; s/-$//')
fi
case "$SENHA" in *\'*|*\\*) echo "A senha não pode ter aspas simples nem barra invertida."; exit 1;; esac
printf 'senha=%s\n' "$SENHA" > "$INFO"
chmod 600 "$INFO"

# Entrar como administrador do MariaDB: normalmente o root do Linux entra direto (unix_socket). Se esse servidor
# já tinha um MariaDB/MySQL com senha no root, pergunta a senha.
DB="mariadb"
command -v mariadb >/dev/null 2>&1 || DB="mysql"
ADMIN=("$DB")
if ! "${ADMIN[@]}" -e "SELECT 1" >/dev/null 2>&1; then
    echo "O administrador (root) do MariaDB deste servidor tem senha."
    read -r -s -p "Senha do root do MariaDB: " ROOTPW </dev/tty
    echo
    ADMIN=("$DB" -uroot "-p$ROOTPW")
    if ! "${ADMIN[@]}" -e "SELECT 1" >/dev/null 2>&1; then
        echo "Senha do root não confere. Nada foi alterado no banco."
        exit 1
    fi
fi

echo "== Criando o banco e o usuário do Finora…"
"${ADMIN[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS finora CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'finora'@'%' IDENTIFIED BY '${SENHA}';
ALTER USER 'finora'@'%' IDENTIFIED BY '${SENHA}';
GRANT ALL PRIVILEGES ON finora.* TO 'finora'@'%';
FLUSH PRIVILEGES;
SQL
"${ADMIN[@]}" -N -e "SELECT CONCAT('   usuário criado: ', user, '@', host) FROM mysql.user WHERE user='finora'"

REDE=$(ip route | awk '/proto kernel/ && /src/ {print $1; exit}')
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    echo "== Firewall ligado: liberando a porta 3306 para a rede ${REDE}…"
    ufw allow from "${REDE}" to any port 3306 proto tcp >/dev/null
fi

echo "== Agendando backup diário em /var/backups/finora (últimos 14)…"
mkdir -p /var/backups/finora
chmod 700 /var/backups/finora
cat > /etc/cron.daily/finora-backup <<'CRON'
#!/bin/sh
# Backup diário do banco do IGNF Finora (os últimos 14 ficam guardados)
DEST=/var/backups/finora
$(command -v mariadb-dump || echo mysqldump) --single-transaction --routines finora | gzip > "$DEST/finora-$(date +%F).sql.gz"
ls -1t "$DEST"/finora-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
CRON
chmod 755 /etc/cron.daily/finora-backup

IP=$(hostname -I | awk '{print $1}')
echo
echo "================================================================"
echo " Servidor do IGNF Finora pronto."
echo
echo " Nos PCs com o Finora (edição Plus ou Pro):"
echo "   Configurações › Onde ficam os dados › Num servidor da rede"
echo
echo "   Endereço: ${IP}"
echo "   Porta:    3306"
echo "   Senha:    ${SENHA}"
echo
echo " A senha fica guardada em ${INFO} (só o root lê)."
echo " Backup diário: /var/backups/finora"
echo "================================================================"
