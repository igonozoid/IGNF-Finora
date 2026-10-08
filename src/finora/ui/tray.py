"""Ícone ao lado do relógio e lembretes de vencimento (aviso do Windows).

- Ao abrir e, com o Finora aberto ou ao lado do relógio, uma vez por dia: "2 contas vencem até amanhã".
  Clicar no aviso abre Lançamentos › A pagar.
- Configurações › Lembretes: ligar/desligar, com quantos dias de antecedência e se fechar a janela deixa o
  Finora ao lado do relógio (para continuar avisando).
"""
from datetime import date

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from finora.core import settings
from finora.core.db import Session
from finora.core.logs import log
from finora.services import reminders

CHECK_MS = 30 * 60 * 1000       # confere de meia em meia hora (o aviso sai no máximo 1 vez por dia)


class Tray(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.last: reminders.Reminder | None = None
        self.icon: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon = QSystemTrayIcon(window.windowIcon(), window)
            self.icon.setToolTip("IGNF Finora")
            menu = QMenu(window)
            menu.addAction("Abrir o Finora", self.show_window)
            menu.addAction("Contas a pagar", self.open_payable)
            menu.addSeparator()
            menu.addAction("Sair", self.quit)
            self.icon.setContextMenu(menu)
            self.icon.activated.connect(self._activated)
            self.icon.messageClicked.connect(self.open_payable)
        self.timer = QTimer(self, interval=CHECK_MS)
        self.timer.timeout.connect(lambda: self.check())
        self.timer.start()
        self.refresh_visibility()

    @property
    def available(self) -> bool:
        return self.icon is not None

    def refresh_visibility(self):
        if self.icon is not None:
            self.icon.setVisible(settings.get_reminders() or settings.get_tray())

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def show_window(self):
        self.w.showNormal()
        self.w.raise_()
        self.w.activateWindow()

    def open_payable(self):
        self.show_window()
        self.w.go_to("entries")
        self.w.page("entries").show_filter("payable")

    def quit(self):
        self.w.quitting = True
        self.w.close()

    def check(self, force: bool = False) -> reminders.Reminder | None:
        """Mostra o aviso se houver contas a vencer/atrasadas e ainda não avisou hoje nesta entidade."""
        if not settings.get_reminders():
            return None
        key = f"{date.today().isoformat()}:{self.w.profile.id}"
        if not force and settings.get_reminder_last() == key:
            return None
        try:
            with Session() as s:
                r = reminders.check(s, self.w.profile.id, settings.get_reminder_days())
        except Exception:                     # banco fora do ar (rede): tenta na próxima
            log.exception("Lembrete de vencimento falhou")
            return None
        self.last = r
        settings.set_reminder_last(key)
        if r.empty:
            return r
        title = f"IGNF Finora — {self.w.profile.name}"
        if self.icon is not None:
            self.icon.show()
            self.icon.showMessage(title, r.text(self.w.profile.currency), QSystemTrayIcon.Warning
                                  if r.overdue else QSystemTrayIcon.Information, 15000)
        log.info("Lembrete: %s atrasadas, %s a vencer", r.overdue, r.soon)
        return r

    def notify(self, text: str):
        if self.icon is not None and self.icon.isVisible():
            self.icon.showMessage("IGNF Finora", text, QSystemTrayIcon.Information, 6000)
