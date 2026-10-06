"""Finora Servidor: um MariaDB portátil cuidado pelo próprio Finora, para usar o app em vários PCs da rede.

Fica tudo dentro da pasta de dados (data/servidor): os programas do MariaDB (baixados do site oficial, com
conferência do SHA-256), os dados do banco e a configuração. Nada é instalado no sistema.
"""
import hashlib
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

VERSION = "11.4.13"                       # LTS
PACKAGES = {
    "win32": (f"https://archive.mariadb.org/mariadb-{VERSION}/winx64-packages/mariadb-{VERSION}-winx64.zip",
              "d62986d433eeebfde218560b276103831604a61e929e87f1a17f5aebd80257e2", 95_024_126),
    "linux": (f"https://archive.mariadb.org/mariadb-{VERSION}/bintar-linux-systemd-x86_64/"
              f"mariadb-{VERSION}-linux-systemd-x86_64.tar.gz",
              "3cebf63914df3154b7cb6d548337eb2be42c773aeb641110446b72e2746cfed7", 0),
}
DEFAULT_PORT = 3306
DB_NAME, DB_USER = "finora", "finora"
EXE = ".exe" if sys.platform == "win32" else ""


class ServerError(RuntimeError):
    """Mensagem pronta para mostrar ao usuário."""


@dataclass(frozen=True)
class Layout:
    root: Path                            # data/servidor

    @property
    def programs(self) -> Path:
        return self.root / "mariadb"

    @property
    def datadir(self) -> Path:
        return self.root / "dados"

    @property
    def config(self) -> Path:
        return self.root / "finora-servidor.cnf"

    @property
    def log(self) -> Path:
        return self.root / "servidor.log"

    def bin(self, name: str) -> Path:
        return self.programs / "bin" / f"{name}{EXE}"


def layout(root: Path | None = None) -> Layout:
    from finora.core import db          # segue a pasta de dados em uso (os testes trocam por uma temporária)
    return Layout(Path(root or db.DATA_DIR / "servidor"))


# ---------- programas ----------
def installed(lay: Layout | None = None) -> bool:
    lay = lay or layout()
    return lay.bin("mariadbd").exists()


def download(lay: Layout | None = None, progress=None) -> Path:
    """Baixa e descompacta o MariaDB oficial para data/servidor/mariadb. `progress(baixado, total)`."""
    import requests
    lay = lay or layout()
    key = "win32" if sys.platform == "win32" else "linux" if sys.platform.startswith("linux") else None
    if key is None:
        raise ServerError("O Finora Servidor funciona no Windows e no Linux. No macOS, use um servidor em outro PC.")
    url, sha, size = PACKAGES[key]
    lay.root.mkdir(parents=True, exist_ok=True)
    pkg = lay.root / url.rsplit("/", 1)[1]
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or size or 0)
            done = 0
            with pkg.open("wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except Exception as exc:
        pkg.unlink(missing_ok=True)
        raise ServerError("Não consegui baixar o MariaDB. Confira a internet e tente de novo.") from exc
    if digest.hexdigest() != sha:
        pkg.unlink(missing_ok=True)
        raise ServerError("O arquivo baixado veio diferente do original (conferência SHA-256). Tente de novo.")
    _extract(pkg, lay.programs)
    pkg.unlink(missing_ok=True)
    return lay.programs


def _extract(pkg: Path, dest: Path) -> None:
    """Descompacta tirando a pasta de cima (mariadb-11.4.x-…) e o que não é preciso (testes, símbolos)."""
    skip = ("/mysql-test/", "/sql-bench/", ".pdb", "/include/", "/man/", "/docs/")
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if pkg.suffix == ".zip":
        with zipfile.ZipFile(pkg) as z:
            for m in z.infolist():
                if not any(x in "/" + m.filename for x in skip):
                    z.extract(m, tmp)
    else:
        with tarfile.open(pkg) as t:
            members = [m for m in t.getmembers() if not any(x in "/" + m.name for x in skip)]
            t.extractall(tmp, members=members, filter="data")
    (top,) = [p for p in tmp.iterdir() if p.is_dir()]
    shutil.rmtree(dest, ignore_errors=True)
    top.rename(dest)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------- preparar, iniciar, parar ----------
def write_config(lay: Layout, port: int) -> None:
    lay.config.write_text(
        "[mysqld]\n"
        f"datadir={lay.datadir.as_posix()}\n"
        f"port={port}\n"
        "bind-address=0.0.0.0\n"                 # aceita os outros PCs da rede
        "character-set-server=utf8mb4\n"
        "collation-server=utf8mb4_unicode_ci\n"
        "max_allowed_packet=32M\n"               # comprovantes de até 10 MB
        f"log-error={lay.log.as_posix()}\n"
        "[client]\n"
        f"port={port}\n", encoding="utf-8")


def _run(args: list, timeout: float = 120) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout,
                          creationflags=flags)


def initialize(lay: Layout, root_password: str, port: int = DEFAULT_PORT) -> None:
    """Cria a pasta de dados do banco (uma vez só)."""
    if (lay.datadir / "mysql").exists():
        return
    if not installed(lay):
        raise ServerError("Baixe o MariaDB primeiro.")
    lay.datadir.mkdir(parents=True, exist_ok=True)
    write_config(lay, port)
    if sys.platform == "win32":
        r = _run([lay.bin("mariadb-install-db"), f"--datadir={lay.datadir}", f"--password={root_password}",
                  f"--port={port}"])
    else:
        script = lay.programs / "scripts" / "mariadb-install-db"
        r = _run([script, "--no-defaults", f"--basedir={lay.programs}", f"--datadir={lay.datadir}",
                  "--auth-root-authentication-method=normal"])
    if r.returncode != 0:
        shutil.rmtree(lay.datadir, ignore_errors=True)
        raise ServerError(f"Não consegui preparar o banco do servidor.\n\n{(r.stderr or r.stdout)[-600:]}")
    if sys.platform != "win32":
        _set_root_password_after_init(lay, root_password, port)


def _set_root_password_after_init(lay: Layout, root_password: str, port: int) -> None:
    start(lay, port)
    wait_ready(port, "root", "", timeout=60)
    _sql(port, "root", "", f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{_esc(root_password)}'")
    stop(lay, port, root_password)


def start(lay: Layout, port: int = DEFAULT_PORT) -> int:
    """Inicia o MariaDB em segundo plano (continua rodando mesmo se o Finora deste PC fechar). Retorna o PID."""
    if is_listening(port):
        return 0
    write_config(lay, port)
    args = [str(lay.bin("mariadbd")), f"--defaults-file={lay.config}"]
    if sys.platform != "win32":
        args.append(f"--basedir={lay.programs}")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | \
            subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, **kwargs)
    return proc.pid


def stop(lay: Layout, port: int, root_password: str) -> None:
    if not is_listening(port):
        return
    r = _run([lay.bin("mariadb-admin"), "-uroot", f"-p{root_password}", "-h127.0.0.1", f"-P{port}", "shutdown"])
    if r.returncode != 0:
        raise ServerError(f"Não consegui parar o servidor.\n\n{(r.stderr or r.stdout)[-400:]}")
    for _ in range(50):
        if not is_listening(port):
            return
        time.sleep(0.2)


def is_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def wait_ready(port: int, user: str, password: str, timeout: float = 30) -> None:
    import pymysql
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            pymysql.connect(host="127.0.0.1", port=port, user=user, password=password, connect_timeout=2).close()
            return
        except Exception as exc:          # ainda subindo
            last = exc
            time.sleep(0.5)
    raise ServerError(f"O servidor não respondeu a tempo. Veja o arquivo {layout().log}.\n\n{last}")


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _sql(port: int, user: str, password: str, *statements: str, database: str | None = None) -> None:
    import pymysql
    con = pymysql.connect(host="127.0.0.1", port=port, user=user, password=password, database=database,
                          autocommit=True, connect_timeout=5)
    try:
        with con.cursor() as cur:
            for st in statements:
                cur.execute(st)
    finally:
        con.close()


def setup_database(port: int, root_password: str, app_password: str) -> None:
    """Cria o banco "finora" e o usuário que os PCs da rede usam (com acesso só a esse banco)."""
    pw = _esc(app_password)
    _sql(port, "root", root_password,
         f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
         f"CREATE USER IF NOT EXISTS '{DB_USER}'@'%' IDENTIFIED BY '{pw}'",
         f"ALTER USER '{DB_USER}'@'%' IDENTIFIED BY '{pw}'",
         f"GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'%'",
         "FLUSH PRIVILEGES")


def new_password() -> str:
    """Senha fácil de ditar para os outros PCs (sem letras parecidas)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def lan_addresses() -> list[str]:
    """Endereços IPv4 deste PC na rede (para informar nos outros PCs)."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))          # não envia nada: só descobre a interface de saída
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return found or ["127.0.0.1"]


def check_connection(host: str, port: int, password: str) -> None:
    """Testa a conexão de um PC cliente com o servidor. Levanta ServerError com mensagem pronta."""
    import pymysql
    try:
        pymysql.connect(host=host, port=port, user=DB_USER, password=password, database=DB_NAME,
                        connect_timeout=5).close()
    except pymysql.err.OperationalError as exc:
        code = exc.args[0] if exc.args else 0
        if code == 1045:
            raise ServerError("O servidor respondeu, mas recusou a senha. Confira a senha mostrada no servidor.")
        if code in (2003, 2005):
            raise ServerError(f"Não encontrei o servidor em {host}:{port}. Confira se o endereço está certo, se o "
                              "Finora Servidor está ligado e se o firewall do servidor libera a porta.")
        raise ServerError(f"Não consegui conectar: {exc}")
    except Exception as exc:
        raise ServerError(f"Não consegui conectar: {exc}")


def env_has_firewall_hint() -> str:
    if sys.platform == "win32":
        return ("Na primeira vez, o Windows pergunta se o MariaDB pode usar a rede: marque \"Redes privadas\" e "
                "clique em Permitir. Sem isso, os outros PCs não conseguem conectar.")
    return "Se o Linux tiver firewall ligado (ufw), libere a porta: sudo ufw allow 3306/tcp"

