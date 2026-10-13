# Acessar o Finora de fora da empresa (VPN com Tailscale)

**Pendente** — combinado em 13/10/2026 para fazer depois. O banco fica no servidor 10.0.0.99 (MariaDB, porta 3306);
nunca abrir a porta 3306 do roteador para a internet. A saída é uma VPN: o Tailscale liga o servidor e o PC de casa
sem mexer no roteador.

## 1. Servidor (Ubuntu, pelo HopToDesk)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # abre um link: entrar com a conta (Google/Microsoft/GitHub)
tailscale ip -4              # endereço do servidor na VPN: 100.x.x.x
```

- Painel login.tailscale.com › Machines › servidor › **Disable key expiry** (senão cai a cada 6 meses).
- Se o firewall (ufw) estiver ligado: `sudo ufw allow in on tailscale0 to any port 3306 proto tcp`.

## 2. PC de casa (ou notebook)

1. Instalar o Tailscale para Windows e entrar com a **mesma conta**.
2. Instalar o Finora (zip da última versão em `C:\IGNF-Finora`, ativar a chave Pro).
3. Configurações › Onde ficam os dados › Num servidor da rede: endereço **100.x.x.x**, porta 3306, senha do
   servidor › Testar conexão › Usar este servidor › **Não** levar os dados deste PC.

Notebook que anda entre a empresa e a casa: usar sempre o endereço 100.x (funciona nos dois lugares).

## Cuidados

- Todos os PCs na mesma versão do Finora: o primeiro que abrir uma versão nova atualiza o banco do servidor.
- Pela internet fica mais lento que na rede local; testar e, se preciso, otimizar as telas mais pesadas.
- Plano gratuito do Tailscale serve para testes; para uso da empresa, conferir os planos. Alternativas abertas:
  NetBird, WireGuard próprio (esse precisa abrir uma porta no roteador).
