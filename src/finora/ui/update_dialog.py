"""Versão nova: novidades e "Atualizar agora" (baixa, confere, troca o programa e abre de novo; data fica)."""
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QTextBrowser, QVBoxLayout,
)

from finora import __version__
from finora.core.logs import log
from finora.services import updater, updates
from finora.ui import theme
from finora.ui.widgets import button


def app_dir() -> Path | None:
    """Pasta do programa (a que tem o executável e a pasta data). None rodando pelo código-fonte."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else None


class UpdateDialog(QDialog):
    def __init__(self, parent, release: updates.Release, t: dict):
        super().__init__(parent)
        self.release, self.t = release, t
        self.window_ = parent
        self.nam = QNetworkAccessManager(self)
        self.reply: QNetworkReply | None = None
        self.file: QFile | None = None
        self.expected = release.sha256
        self.setObjectName("wizard")
        self.setWindowTitle("Versão nova do IGNF Finora")
        self.resize(560, 420)
        title = QLabel(f"Versão {release.version} disponível", objectName="sectionTitle")
        sub = QLabel(f"Você está com a {__version__}." + (f" Publicada em {release.published:%d/%m/%Y}."
                                                            if release.published else ""))
        sub.setProperty("role", "muted")
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "Melhorias e correções.")
        self.status = QLabel(wordWrap=True)
        self.status.setProperty("role", "muted")
        self.bar = QProgressBar(textVisible=True)
        self.bar.hide()
        btns = QHBoxLayout()
        page = button("Ver no site", "link", t, "fa6s.up-right-from-square")
        btns.addWidget(page)
        btns.addStretch(1)
        later = button("Depois", "secondary")
        self.go = button("Atualizar agora", "primary", t, "fa6s.download", "on_acc")
        btns.addWidget(later)
        btns.addWidget(self.go)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addWidget(notes, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addLayout(btns)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release.url)))
        later.clicked.connect(self.reject)
        self.go.clicked.connect(self.start)
        if app_dir() is None or not release.can_install:
            self.go.setEnabled(False)
            self.status.setText("Atualização automática indisponível aqui: baixe pelo site, descompacte numa pasta "
                                "nova e copie para ela a pasta data desta versão (veja o LEIA-ME)."
                                if app_dir() is None else
                                "Essa versão não tem o pacote deste sistema para atualizar sozinho. Baixe pelo site.")
        else:
            self.status.setText("O Finora baixa a versão nova, confere o arquivo, fecha, troca o programa e abre de "
                                "novo. Seus dados (pasta data) ficam como estão, e um backup é feito antes.")

    def _get(self, url: str) -> QNetworkReply:
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", f"IGNF-Finora/{__version__}".encode())
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        return self.nam.get(req)

    def start(self):
        self.go.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        if not self.expected:
            self.status.setText("Conferindo a versão…")
            self.reply = self._get(self.release.sums_url)
            self.reply.finished.connect(self._sums)
        else:
            self._download()

    def _sums(self):
        reply, self.reply = self.reply, None
        reply.deleteLater()
        text = bytes(reply.readAll()).decode("utf-8", errors="replace") if reply.error() == QNetworkReply.NoError else ""
        self.expected = updates.sha_from_sums(text, self.release.asset_name)
        if not self.expected:
            self._fail("Não consegui conferir a versão nova agora. Tente mais tarde ou baixe pelo site.")
            return
        self._download()

    def _download(self):
        upd = app_dir() / updater.UPDATE_DIR
        upd.mkdir(exist_ok=True)
        self.target = upd / self.release.asset_name
        self.file = QFile(str(self.target))
        if not self.file.open(QIODevice.WriteOnly):
            self._fail("Não consegui gravar na pasta do Finora (sem permissão?).")
            return
        self.status.setText(f"Baixando {self.release.asset_name}…")
        self.reply = self._get(self.release.asset_url)
        self.reply.readyRead.connect(lambda: self.file.write(self.reply.readAll()))
        self.reply.downloadProgress.connect(self._progress)
        self.reply.finished.connect(self._downloaded)

    def _progress(self, got: int, total: int):
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(got * 100 / total))
            self.bar.setFormat(f"{got / 1e6:.0f} de {total / 1e6:.0f} MB")

    def _downloaded(self):
        reply, self.reply = self.reply, None
        self.file.write(reply.readAll())
        self.file.close()
        reply.deleteLater()
        if reply.error() != QNetworkReply.NoError:
            self._fail(f"O download falhou: {reply.errorString()}")
            return
        try:
            self.status.setText("Conferindo e preparando…")
            QApplication.processEvents()
            updater.verify(self.target, self.expected)
            exe = Path(sys.executable).name
            new = updater.extract(self.target, app_dir() / updater.UPDATE_DIR / "novo", exe)
            script = updater.write_script(app_dir(), new, QApplication.applicationPid(), exe)
        except (ValueError, OSError) as e:
            self._fail(str(e))
            return
        self._backup()
        QMessageBox.information(self, "Atualizar", "Tudo pronto. O Finora vai fechar e abrir de novo já na versão "
                                                   f"{self.release.version} (leva alguns segundos).")
        log.info("Atualizando para %s", self.release.version)
        updater.launch(script)
        self.accept()
        if self.window_ is not None:
            self.window_.quitting = True
            self.window_.close()
        QApplication.instance().quit()

    def _backup(self):
        """Cópia dos dados antes de trocar o programa (em data/backups, com a versão no nome)."""
        try:
            from finora.core import db, settings
            from finora.services import backup
            if settings.get_db_config().mode != "client":
                backup.backup_to(db.BACKUP_DIR / f"antes-da-versao-{self.release.version}.db")
        except Exception:                      # backup nunca impede a atualização (o banco não é tocado)
            log.exception("Backup antes de atualizar falhou")

    def _fail(self, text: str):
        self.bar.hide()
        self.status.setProperty("role", "error")
        self.status.setText(text)
        self.status.style().polish(self.status)
        self.go.setEnabled(True)
        if self.file is not None and self.file.isOpen():
            self.file.close()
