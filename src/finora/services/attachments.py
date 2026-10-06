"""Comprovantes anexados aos lançamentos (foto do recibo, boleto em PDF, nota fiscal…)."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.models import Attachment, Entry

MAX_SIZE = 10 * 1024 * 1024         # 10 MB por arquivo
MAX_PER_ENTRY = 10
TYPES = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".txt", ".xml", ".ofx", ".csv", ".xlsx",
         ".xls", ".doc", ".docx", ".odt", ".ods", ".zip"}


@dataclass(frozen=True)
class AttachmentView:
    id: int
    filename: str
    size: int
    added: date

    @property
    def size_label(self) -> str:
        kb = self.size / 1024
        return f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB".replace(".", ",")


def list_for(s: Session, entry_id: int) -> list[AttachmentView]:
    q = (select(Attachment.id, Attachment.filename, Attachment.size, Attachment.added)
         .where(Attachment.entry_id == entry_id).order_by(Attachment.id))
    return [AttachmentView(*row) for row in s.execute(q)]


def counts(s: Session, entry_ids: list[int]) -> dict[int, int]:
    if not entry_ids:
        return {}
    q = (select(Attachment.entry_id, func.count(Attachment.id)).where(Attachment.entry_id.in_(entry_ids))
         .group_by(Attachment.entry_id))
    return dict(s.execute(q).all())


def add(s: Session, entry_id: int, path: str | Path, today: date | None = None) -> int:
    """Copia o arquivo para dentro do banco. Levanta ValueError com mensagem pronta."""
    e = s.get(Entry, entry_id)
    if e is None:
        raise ValueError("Salve o lançamento antes de anexar.")
    path = Path(path)
    if path.suffix.lower() not in TYPES:
        raise ValueError("Esse tipo de arquivo não pode ser anexado. Use PDF, foto (JPG/PNG) ou documento.")
    try:
        size = path.stat().st_size
    except OSError:
        raise ValueError("Não consegui abrir o arquivo.") from None
    if size > MAX_SIZE:
        mb = f"{size / 1024 / 1024:.1f}".replace(".", ",")
        raise ValueError(f"O arquivo tem {mb} MB; o limite é 10 MB. "
                         "Diminua a foto ou salve o PDF com qualidade menor.")
    if size == 0:
        raise ValueError("O arquivo está vazio.")
    used = s.scalar(select(func.count(Attachment.id)).where(Attachment.entry_id == entry_id))
    if used >= MAX_PER_ENTRY:
        raise ValueError(f"Cada lançamento aceita até {MAX_PER_ENTRY} anexos.")
    a = Attachment(entity_id=e.entity_id, entry_id=entry_id, filename=path.name[:200], size=size,
                   added=today or date.today(), data=path.read_bytes())
    s.add(a)
    s.commit()
    return a.id


def content(s: Session, attachment_id: int) -> tuple[str, bytes]:
    a = s.get(Attachment, attachment_id)
    if a is None:
        raise ValueError("Anexo não encontrado.")
    return a.filename, a.data


def save_copy(s: Session, attachment_id: int, dest: str | Path) -> Path:
    """Grava o anexo num arquivo (para abrir no programa padrão ou guardar onde quiser)."""
    _name, data = content(s, attachment_id)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def remove(s: Session, attachment_id: int) -> None:
    a = s.get(Attachment, attachment_id)
    if a is not None:
        s.delete(a)
        s.commit()
