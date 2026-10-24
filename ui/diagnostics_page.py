from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

from core.diagnostics import build_report
from core.paths import LOG_FILE
from ui.operations import exclusive_action
from ui.workers import CallWorker


class DiagnosticsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        title = QLabel("Диагностика")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("Отчёт о компонентах, процессах, резервных копиях и последних ошибках. "
                      "Секрет Telegram-прокси и содержимое списков доменов в него не включаются.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        actions = QHBoxLayout()
        for text, callback in (("Обновить отчёт", lambda: self.collect(False)),
                               ("Проверить доступ к GitHub", lambda: self.collect(True)),
                               ("Открыть папку журнала", self.open_logs)):
            button = QPushButton(text)
            button.setObjectName("secondaryButton")
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.report = QTextEdit()
        self.report.setObjectName("logView")
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Нажмите «Обновить отчёт». Проверка выполняется в фоне.")
        layout.addWidget(self.report, 1)
        self.copy_button = QPushButton("Скопировать отчёт")
        self.copy_button.setObjectName("primaryButton")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_report)
        layout.addWidget(self.copy_button)

    @exclusive_action
    def collect(self, check_network=False):
        self.copy_button.setEnabled(False)
        self.main_window.set_busy(True, "Собираю диагностику…")
        self.worker = CallWorker(lambda: build_report(check_network))
        self.worker.finished_ok.connect(self.show_report)
        self.worker.finished_error.connect(lambda message: self.report.setPlainText("Не удалось собрать отчёт: " + message))
        self.main_window.operations.start(self.worker)

    def show_report(self, report):
        self.report.setPlainText(report)
        self.copy_button.setEnabled(True)
        self.copy_button.setText("Скопировать отчёт")

    def copy_report(self):
        QApplication.clipboard().setText(self.report.toPlainText())
        self.copy_button.setText("Отчёт скопирован")

    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE.parent)))
