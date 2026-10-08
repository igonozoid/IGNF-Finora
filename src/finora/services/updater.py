"""Atualizar com um clique: o pacote novo (já baixado e conferido) substitui o programa; a pasta data fica.

Como o programa não pode trocar os próprios arquivos enquanto roda, um script pequeno (PowerShell no Windows,
sh no Linux) espera o Finora fechar, guarda o programa antigo em _update/antigo, copia o novo e abre de novo.
Se a cópia falhar, ele devolve o antigo. Os dados (pasta data) não são tocados; ao abrir, o Finora atualiza o
banco sozinho, com backup antes.
"""
import hashlib
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

UPDATE_DIR = "_update"
KEEP = {"data", UPDATE_DIR}           # nunca mexe nessas pastas da instalação


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, expected: str) -> None:
    if not expected or sha256(path) != expected.lower():
        raise ValueError("O arquivo baixado não confere (pode ter vindo incompleto). Tente de novo mais tarde.")


def extract(package: Path, dest: Path, exe_name: str) -> Path:
    """Descompacta e devolve a pasta do programa novo (a que tem o executável)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if package.name.endswith(".zip"):
        with zipfile.ZipFile(package) as z:
            _safe_names(dest, z.namelist())
            z.extractall(dest)
    else:
        with tarfile.open(package) as t:
            _safe_names(dest, t.getnames())
            t.extractall(dest, filter="data")
    found = next((p.parent for p in dest.rglob(exe_name) if p.is_file()), None)
    if found is None:
        raise ValueError("O pacote baixado não tem o programa do Finora.")
    if (found / "data").exists():          # pacote nunca deveria trazer dados; por garantia, não leva
        shutil.rmtree(found / "data")
    return found


def _safe_names(dest: Path, names: list[str]) -> None:
    root = dest.resolve()
    for n in names:
        if not (dest / n).resolve().is_relative_to(root):
            raise ValueError("Pacote inválido.")


def _ps(text: str | Path) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def write_script(app_dir: Path, new_dir: Path, pid: int, exe_name: str) -> Path:
    upd = app_dir / UPDATE_DIR
    old = upd / "antigo"
    log = upd / "atualizacao.log"
    if sys.platform == "win32":
        keep = ",".join(_ps(k) for k in KEEP)
        script = f"""$ErrorActionPreference = 'Stop'
$app = {_ps(app_dir)}; $new = {_ps(new_dir)}; $old = {_ps(old)}; $log = {_ps(log)}
function Log($m) {{ Add-Content -Path $log -Value ("$(Get-Date -Format s) " + $m) }}
Log 'Esperando o Finora fechar'
try {{ Wait-Process -Id {pid} -Timeout 120 -ErrorAction SilentlyContinue }} catch {{}}
Start-Sleep -Milliseconds 800
if (Test-Path $old) {{ Remove-Item $old -Recurse -Force }}
New-Item -ItemType Directory -Path $old | Out-Null
$keep = @({keep})
try {{
  Get-ChildItem -LiteralPath $app | Where-Object {{ $keep -notcontains $_.Name }} | ForEach-Object {{
    Move-Item -LiteralPath $_.FullName -Destination $old }}
  Get-ChildItem -LiteralPath $new | ForEach-Object {{ Copy-Item -LiteralPath $_.FullName -Destination $app -Recurse -Force }}
  Log 'Programa novo copiado'
}} catch {{
  Log ("Falhou: " + $_ + " - devolvendo a versão antiga")
  Get-ChildItem -LiteralPath $app | Where-Object {{ $keep -notcontains $_.Name }} | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Get-ChildItem -LiteralPath $old | ForEach-Object {{ Move-Item -LiteralPath $_.FullName -Destination $app }}
}}
Start-Process -FilePath (Join-Path $app {_ps(exe_name)}) -WorkingDirectory $app
"""
        path = upd / "atualizar.ps1"
        path.write_text(script, encoding="utf-8-sig")
    else:
        keep = " ".join(KEEP)
        script = f"""#!/bin/sh
APP="{app_dir}"; NEW="{new_dir}"; OLD="{old}"; LOG="{log}"
echo "$(date) esperando o Finora fechar" >> "$LOG"
while kill -0 {pid} 2>/dev/null; do sleep 1; done
sleep 1
rm -rf "$OLD"; mkdir -p "$OLD"
for f in "$APP"/* "$APP"/.[!.]*; do
  [ -e "$f" ] || continue
  case " {keep} " in *" $(basename "$f") "*) continue;; esac
  mv "$f" "$OLD"/
done
if cp -a "$NEW"/. "$APP"/; then echo "$(date) programa novo copiado" >> "$LOG"
else
  echo "$(date) falhou, devolvendo a versão antiga" >> "$LOG"
  cp -a "$OLD"/. "$APP"/
fi
cd "$APP" && nohup "./{exe_name}" >/dev/null 2>&1 &
"""
        path = upd / "atualizar.sh"
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
    return path


def launch(script: Path) -> None:
    import subprocess
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True)
