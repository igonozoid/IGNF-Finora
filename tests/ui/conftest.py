"""Ambiente dos testes de tela: banco, pastas e preferências temporários; diálogos simulados.

As telas rodam em modo "offscreen" (sem abrir janela), igual no Windows e no Linux do GitHub.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, timedelta  # noqa: E402
from decimal import Decimal as D  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from finora.core import db  # noqa: E402
from finora.services import accounts, categories, entries, setup  # noqa: E402
from finora.services.entries import EntryData  # noqa: E402
from finora.ui import locale_br, theme  # noqa: E402


class Dialogs:
    """Respostas prontas para as janelas de confirmação (e registro do que foi mostrado)."""

    def __init__(self):
        self.answer_yes = True
        self.choice = None          # texto do botão a "clicar" em QMessageBox personalizados
        self.shown: list[str] = []
        self.save_path = ""
        self.open_path = ""


@pytest.fixture
def dialogs(monkeypatch):
    d = Dialogs()

    def info(*a, **k):
        d.shown.append(str(a[2]) if len(a) > 2 else "")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(info))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(info))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(info))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes if d.answer_yes else QMessageBox.No))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: d.shown.append(self.text()) or 0)
    monkeypatch.setattr(QMessageBox, "clickedButton",
                        lambda self: next((b for b in self.buttons() if b.text() == d.choice), None))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (d.save_path, "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (d.open_path, "")))
    return d


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Banco e pastas de dados temporários; o app inteiro passa a usá-los."""
    original = db.engine
    eng = db.sqlite_pragmas(create_engine(f"sqlite:///{tmp_path / 'finora.db'}"))
    db.init_db(eng, tmp_path / "backups")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "finora.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(db, "engine", eng)
    db.Session.configure(bind=eng)
    yield tmp_path
    db.Session.configure(bind=original)
    eng.dispose()


@pytest.fixture
def profile(data_dir):
    with db.Session() as s:
        return setup.run_first_setup(s, name="Rodrigo", currency="BRL", account_name="Nubank",
                                     account_kind="bank", balance=D("1000"))


@pytest.fixture
def sample(profile):
    """Alguns lançamentos no mês atual: salário pago, aluguel recorrente, luz atrasada, mercado."""
    today = date.today()
    with db.Session() as s:
        bank = accounts.list_accounts(s, profile.id)[0].id
        exp = {label: cid for cid, label in categories.choices(s, profile.id, "expense")}
        inc = {label: cid for cid, label in categories.choices(s, profile.id, "income")}

        def add(**kw):
            base = dict(kind="expense", amount=D("100"), due_date=today, account_id=bank)
            base.update(kw)
            return entries.create(s, profile.id, EntryData(**base))

        add(kind="income", description="Salário", amount=D("5000"), category_id=inc["Receitas › Salário"],
            contact="Empresa X", paid=True, paid_date=today)
        add(description="Aluguel", amount=D("1500"), category_id=exp["Moradia › Aluguel ou financiamento"],
            repeat="monthly", times=3, contact="Imobiliária")
        add(description="Conta de luz", amount=D("180.40"), category_id=exp["Moradia › Luz"],
            due_date=today - timedelta(days=1) if today.day > 1 else today, contact="Enel")
        add(description="Mercado", amount=D("640.10"), category_id=exp["Alimentação › Supermercado"])
    return profile


@pytest.fixture
def app_t(qapp):
    qapp.setStyle("Fusion")
    locale_br.install(qapp)
    return theme.apply(qapp, "light")


def _destroy(qapp, w):
    """Fecha e DESTRÓI a janela. Sem isso as janelas dos testes anteriores continuam vivas e
    cada troca de tema reestiliza todas elas — os testes ficam cada vez mais lentos."""
    w.close()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


@pytest.fixture
def window(qtbot, qapp, app_t, sample, dialogs):
    from finora.ui.main_window import MainWindow
    w = MainWindow(sample)
    w.restart = lambda: dialogs.shown.append("REINICIAR")   # reabrir o app não faz sentido em teste
    w.pages[6].restart_requested.disconnect()
    w.pages[6].restart_requested.connect(w.restart)
    w.resize(1366, 800)
    w.show()
    qtbot.waitExposed(w)
    yield w
    _destroy(qapp, w)


def pump(qtbot, ms: int = 30):
    qtbot.wait(ms)
