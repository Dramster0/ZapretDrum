"""Autopick UI reuses the shared operation controller and strategy launch path."""
from dataclasses import asdict

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QScrollArea, QMessageBox
from PyQt6.QtCore import Qt

from core.installer import is_installed
from core.state import load_state, save_state
from core.strategies import discover_strategies, find_strategy
from ui.widgets import Card
from ui.theme import TEXT_SECONDARY
from ui.operations import exclusive_action
from ui.workers import AutoTestWorker


class AutoTestPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.worker = None
        self._baseline = []
        self._version = None
        self._fresh_result = False
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        title = QLabel("Автоподбор стратегии")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel("Сначала проверим HTTP-доступ без обхода, затем со стратегиями. "
                      "Во время проверки соединение может прерываться. В конце восстановим прежний обход. "
                      "Эти проверки не подтверждают работу голоса Discord и воспроизведения видео.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        controls = Card()
        self.status_label = QLabel("Готов к запуску")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        controls.body.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        controls.body.addWidget(self.progress_bar)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Начать автоподбор")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_test)
        self.cancel_button = QPushButton("Отменить")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.cancel_test)
        self.cancel_button.setEnabled(False)
        self.saved_button = QPushButton("Последний полный результат")
        self.saved_button.setObjectName("secondaryButton")
        self.saved_button.clicked.connect(self.reload_saved)
        for button in (self.start_button, self.cancel_button, self.saved_button):
            buttons.addWidget(button)
        controls.body.addLayout(buttons)
        self.baseline_label = QLabel()
        self.baseline_label.setWordWrap(True)
        controls.body.addWidget(self.baseline_label)
        self.baseline_button = QPushButton("Подробности проверки без обхода")
        self.baseline_button.setObjectName("secondaryButton")
        self.baseline_button.clicked.connect(lambda: self.show_details("Без обхода", self._baseline))
        controls.body.addWidget(self.baseline_button)
        root.addWidget(controls)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.addStretch(1)
        scroll.setWidget(self.results_container)
        root.addWidget(scroll, 1)
        self.reload_saved()

    def _render(self, results, baseline, version):
        self._version, self._baseline = version, baseline
        while self.results_layout.count() > 1:
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.baseline_label.setText(
            f"Без обхода: {sum(check['ok'] for check in baseline)}/{len(baseline)} HTTP-проверок."
            if baseline else "Сравнение без обхода пока не выполнено.")
        self.baseline_button.setVisible(bool(baseline))
        for rank, result in enumerate(results, start=1):
            card = Card()
            strategy = find_strategy(result["strategy"])
            label = QLabel(f"{rank}. {strategy.name if strategy else result['strategy']}")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            card.body.addWidget(label)
            latency = result.get("avg_latency_ms")
            summary = f"{result['success']}/{result['total']} проверок"
            if latency is not None:
                summary += f" · HTTP-отклик {latency:.0f} мс"
            if not strategy:
                summary += " · файл стратегии отсутствует"
            if version != load_state().installed_version or version is None and not self._fresh_result:
                summary += " · результат другой или неизвестной версии zapret"
            info = QLabel(summary)
            info.setWordWrap(True)
            info.setStyleSheet(f"color: {TEXT_SECONDARY};")
            card.body.addWidget(info)
            row = QHBoxLayout()
            details = QPushButton("Подробности")
            details.setObjectName("secondaryButton")
            details.clicked.connect(lambda checked=False, r=result: self.show_details(r["strategy"], r.get("checks", [])))
            row.addWidget(details)
            apply = QPushButton("Запустить и запомнить")
            apply.setObjectName("secondaryButton")
            apply.setEnabled(bool(strategy and result["success"] and (version is not None or self._fresh_result)
                                  and version == load_state().installed_version))
            apply.clicked.connect(lambda checked=False, name=result["strategy"]: self.apply_strategy(name))
            row.addWidget(apply)
            card.body.addLayout(row)
            self.results_layout.insertWidget(self.results_layout.count() - 1, card)

    def reload_saved(self):
        if self.worker and self.worker.isRunning():
            return
        state = load_state()
        self._fresh_result = False
        self._render(state.last_test_results, state.last_test_baseline, state.last_test_version)
        if state.last_test_results:
            caption = ("Последний полный результат: " + state.last_test_at.replace("T", " ")
                       if state.last_test_at else "Ранее сохранённые результаты без даты. Рекомендуется повторить проверку.")
        else:
            caption = "Готов к запуску"
        self.status_label.setText(caption)
        self.progress_bar.setValue(100 if state.last_test_at and state.last_test_results else 0)
        self.saved_button.setEnabled(bool(state.last_test_results))

    @exclusive_action
    def start_test(self):
        if not is_installed():
            QMessageBox.information(self, "zapret не установлен", "Сначала установите zapret на странице «Обновление».")
            return
        strategies = discover_strategies()
        if not strategies:
            QMessageBox.information(self, "Нет стратегий", "Стратегии не найдены.")
            return
        self._version = load_state().installed_version
        self.start_button.setEnabled(False)
        self.saved_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Подготовка…")
        self.worker = AutoTestWorker(strategies)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.finished_error.connect(self._on_error)
        self.main_window.operations.start(self.worker)
        self.main_window.set_busy(True, "Идёт автоподбор…")

    def cancel_test(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Отмена: ожидаю завершения текущего запроса или запуска и восстановления обхода…")

    def _on_progress(self, message, completed, total):
        if message.startswith("Восстанавливаю"):
            self.cancel_button.setEnabled(False)
        if self.worker and self.worker._cancelled.is_set():
            message = "Отмена запрошена. " + message
        self.status_label.setText(f"{message} ({completed}/{total})")
        self.progress_bar.setValue(min(99, int(completed / max(total, 1) * 100)))

    def _on_finished(self, run):
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        results = [result.to_dict() for result in run.results]
        baseline = [asdict(check) for check in run.baseline]
        self._fresh_result = True
        self._render(results, baseline, self._version)
        complete = not run.cancelled and not run.error and len(results) == run.total and run.total > 0
        if complete:
            state = load_state()
            state.last_test_results = results
            state.last_test_at = run.completed_at
            state.last_test_version = self._version
            state.last_test_baseline = baseline
            try:
                save_state(state)
            except OSError as exc:
                QMessageBox.warning(self, "Результат не сохранён", str(exc))
            self.progress_bar.setValue(100)
            caption = "Проверка завершена: " + run.completed_at.replace("T", " ") + "."
        else:
            self.progress_bar.setValue(min(99, int(len(results) / max(run.total, 1) * 100)))
            caption = "Проверка отменена." if run.cancelled else "Проверка завершилась с ошибкой."
            caption += f" Готово стратегий: {len(results)}/{run.total}. Предыдущий полный результат сохранён."
        self.status_label.setText(caption + " " + run.restoration)
        self.saved_button.setEnabled(bool(load_state().last_test_results))
        self.main_window.home_page.reload_strategies()
        if run.error:
            QMessageBox.warning(self, "Автоподбор: требуется внимание", run.error)

    def _on_error(self, message):
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.saved_button.setEnabled(bool(load_state().last_test_results))
        self.status_label.setText("Автоподбор не завершён. Предыдущие сохранённые результаты не изменены.")
        QMessageBox.warning(self, "Ошибка автоподбора", message)

    def show_details(self, title, checks):
        from ui.main_window import _show_log_dialog
        lines = []
        for check in checks:
            latency = check.get("latency_ms")
            text = check["name"] + ": " + ("успешно" if check["ok"] else check.get("error") or "ошибка")
            if latency is not None:
                text += f" ({latency:.0f} мс)"
            lines.append(text)
        _show_log_dialog(self, title, "\n".join(lines) if lines else "В старом результате подробности не сохранялись. Запустите автоподбор снова.")

    def apply_strategy(self, name):
        strategy = find_strategy(name)
        if (strategy is None or self._version != load_state().installed_version
                or self._version is None and not self._fresh_result):
            QMessageBox.information(self, "Повторите проверку", "Стратегия отсутствует или версия zapret не соответствует результату.")
            return
        self.main_window.start_strategy(strategy, make_favorite=True)
        self.main_window.go_to("home")

