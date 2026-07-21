from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QIcon, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLineEdit,
    QStackedWidget,
    QScrollArea,
    QProgressBar,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QTextEdit,
)

from core import process_manager
from core import service_manager
from core import user_lists
from core import app_updater
from core.app_version import get_app_version
from core.paths import (
    APP_DATA_DIR,
    ZAPRET_DIR,
    GITHUB_RELEASES_PAGE,
    DEVELOPER_TELEGRAM_URL,
    resource_path,
)
from core.installer import is_installed, ReleaseInfo
from core.state import load_state, save_state
from core.strategies import discover_strategies, Strategy, find_strategy
from core.updater import check_for_updates, UpdateCheckResult

from ui.theme import STYLESHEET, TEXT_SECONDARY, SUCCESS, DANGER, BORDER, ACCENT
from ui.widgets import Card, StrategyRow, PowerButton, make_avatar, nav_button, MainTitleBar, DialogTitleBar, ResizeGrip
from ui.workers import (
    InstallWorker,
    FetchReleasesWorker,
    StartStrategyWorker,
    StopWorker,
    AutoTestWorker,
    InstallServiceWorker,
    RemoveServiceWorker,
    CheckAppUpdateWorker,
    DownloadAppUpdateWorker,
    FetchChangelogWorker,
)


def _open_folder(path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _make_frameless_dialog(parent, title: str, width: int, height: int) -> tuple:
    """Общая обвязка для наших диалогов: без системной рамки, скруглённые
    углы, свой заголовок с крестиком закрытия и перетаскиванием мышью.
    Возвращает (dialog, content_layout) - контент кладётся в content_layout.

    Важно: сам верхнеуровневый QDialog с WA_TranslucentBackground не красит
    свой фон через QSS (проверено - при таком сочетании флагов Qt оставляет
    его прозрачным). Поэтому фон и скруглённые углы рисует дочерний виджет
    (dialogRoot) - точно так же, как это уже сделано в MainWindow."""
    dialog = QDialog(parent)
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    dialog.resize(width, height)

    dialog_outer = QVBoxLayout(dialog)
    dialog_outer.setContentsMargins(0, 0, 0, 0)
    dialog_outer.setSpacing(0)

    dialog_root = QWidget()
    dialog_root.setObjectName("dialogRoot")
    dialog_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog_outer.addWidget(dialog_root)

    outer = QVBoxLayout(dialog_root)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    title_bar = DialogTitleBar(dialog, title)
    outer.addWidget(title_bar)

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(20, 16, 20, 16)
    outer.addWidget(content, 1)

    return dialog, content_layout


def _show_log_dialog(parent, title: str, text: str) -> None:
    dialog, layout = _make_frameless_dialog(parent, title, 560, 420)
    view = QTextEdit()
    view.setObjectName("logView")
    view.setReadOnly(True)
    view.setPlainText(text.strip() or "(пусто)")
    layout.addWidget(view)
    dialog.exec()


def _show_changelog_dialog(parent, entries: list) -> None:
    """Окно 'Что нового?' в духе ArnUnlock: заголовок, крестик закрытия,
    и список версий с их описанием (текст релизов с GitHub, отрендеренный
    как markdown - заголовки/списки/жирный текст из релиза будут смотреться
    аккуратно, а не сырыми звёздочками и решётками)."""
    dialog, layout = _make_frameless_dialog(parent, "Что нового?", 480, 560)

    view = QTextEdit()
    view.setObjectName("changelogView")
    view.setReadOnly(True)

    if entries:
        md_parts = []
        for entry in entries:
            date = entry.published_at[:10]
            heading = f"## v{entry.version}" + (f"  •  {date}" if date else "")
            body = entry.notes or "_Без описания изменений._"
            md_parts.append(f"{heading}\n\n{body}\n\n---")
        view.setMarkdown("\n\n".join(md_parts))
    else:
        view.setMarkdown(
            "Пока не удалось загрузить список изменений "
            "(нет подключения к интернету, либо ещё не опубликовано ни одного релиза)."
        )
    layout.addWidget(view, 1)

    footer = QLabel(
        f'Нашли баг? Напишите в Telegram: '
        f'<a href="{DEVELOPER_TELEGRAM_URL}" style="color:{ACCENT};">@Dramster1</a>'
    )
    footer.setOpenExternalLinks(True)
    footer.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
    layout.addWidget(footer)

    dialog.exec()


def _confirm(
    parent, title: str, text: str,
    ok_text: str = "Продолжить", cancel_text: str = "Отмена", danger: bool = False,
) -> bool:
    """QMessageBox.question, но с русскими подписями кнопок вместо системных Yes/No
    (которые на некоторых сборках Windows остаются на английском), и со своим
    оформлением - иначе кнопки без objectName не подхватывают тёмную тему
    и рисуются дефолтным светлым стилем Windows."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Question)
    ok_btn = box.addButton(ok_text, QMessageBox.ButtonRole.YesRole)
    cancel_btn = box.addButton(cancel_text, QMessageBox.ButtonRole.NoRole)
    ok_btn.setObjectName("dangerButton" if danger else "primaryButton")
    cancel_btn.setObjectName("secondaryButton")
    # setObjectName() после того, как виджет уже создан, не применяется сам -
    # нужно явно попросить Qt пересчитать стиль (та же особенность, что и
    # со строками стратегий в StrategyRow._restyle()).
    for btn in (ok_btn, cancel_btn):
        btn.style().unpolish(btn)
        btn.style().polish(btn)
    box.setDefaultButton(ok_btn)
    box.exec()
    return box.clickedButton() is ok_btn


def _ping_text_for(file_name: str, results: list[dict]) -> tuple[str, bool | None]:
    for r in results:
        if r.get("strategy") == file_name:
            success, total = r.get("success", 0), r.get("total", 0)
            latency = r.get("avg_latency_ms")
            if success == 0:
                return "Timeout", False
            if latency:
                return f"{latency:.0f} ms", success == total
            return f"{success}/{total}", success == total
    return "—", None


# --------------------------------------------------------------------------- #
# Home — список стратегий слева + большая кнопка подключения справа
# --------------------------------------------------------------------------- #
class HomePage(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.main_window = main_window
        self.rows: dict[str, StrategyRow] = {}
        self.selected_file_name: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        self.install_card = Card()
        install_label = QLabel("zapret ещё не установлен")
        install_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        self.install_card.body.addWidget(install_label)
        install_hint = QLabel("Нажмите, чтобы скачать последнюю версию с GitHub — это займёт меньше минуты.")
        install_hint.setStyleSheet(f"color: {TEXT_SECONDARY};")
        install_hint.setWordWrap(True)
        self.install_card.body.addWidget(install_hint)
        install_btn = QPushButton("Скачать и установить zapret")
        install_btn.setObjectName("primaryButton")
        install_btn.clicked.connect(lambda: main_window.go_to("update"))
        self.install_card.body.addWidget(install_btn)
        root.addWidget(self.install_card)

        content_row = QHBoxLayout()
        content_row.setSpacing(18)
        root.addLayout(content_row, 1)

        # --- левая колонка: список стратегий ---
        left_card = Card()
        left_card.body.setContentsMargins(4, 4, 4, 4)

        header_row = QHBoxLayout()
        list_title = QLabel("Стратегии")
        list_title.setStyleSheet("font-size: 16px; font-weight: 700;")
        header_row.addWidget(list_title)
        header_row.addStretch(1)
        refresh_btn = QPushButton("🔄")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.setFixedWidth(40)
        refresh_btn.setToolTip("Обновить список стратегий")
        refresh_btn.clicked.connect(self.reload_strategies)
        header_row.addWidget(refresh_btn)
        left_card.body.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_container)
        left_card.body.addWidget(scroll, 1)

        self.empty_label = QLabel("Стратегии не найдены. Установите zapret на странице «Обновление».")
        self.empty_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        left_card.body.addWidget(self.empty_label)

        content_row.addWidget(left_card, 3)

        # --- правая колонка: кнопка подключения ---
        right_col = QVBoxLayout()
        right_col.setSpacing(16)
        right_col.addStretch(1)

        self.power_button = PowerButton()
        self.power_button.clicked.connect(self._on_power_clicked)
        power_row = QHBoxLayout()
        power_row.addStretch(1)
        power_row.addWidget(self.power_button)
        power_row.addStretch(1)
        right_col.addLayout(power_row)

        right_col.addStretch(1)

        selected_card = Card()
        sel_row = QHBoxLayout()
        self.selected_avatar_holder = QHBoxLayout()
        self.selected_avatar = make_avatar("general")
        self.selected_avatar_holder.addWidget(self.selected_avatar)
        sel_row.addLayout(self.selected_avatar_holder)

        sel_text_col = QVBoxLayout()
        sel_text_col.setSpacing(1)
        self.selected_name_label = QLabel("Стратегия не выбрана")
        self.selected_name_label.setStyleSheet("font-weight: 700; font-size: 13px;")
        self.selected_sub_label = QLabel("ZAPRET | BAT")
        self.selected_sub_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        sel_text_col.addWidget(self.selected_name_label)
        sel_text_col.addWidget(self.selected_sub_label)
        sel_row.addLayout(sel_text_col)
        sel_row.addStretch(1)
        selected_card.body.addLayout(sel_row)

        self.status_caption = QLabel("")
        self.status_caption.setWordWrap(True)
        self.status_caption.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        selected_card.body.addWidget(self.status_caption)

        mode_row = QVBoxLayout()
        mode_row.setSpacing(8)
        self.mode_service_btn = QPushButton("⚙  Меню service.bat")
        self.mode_service_btn.setObjectName("secondaryButton")
        self.mode_service_btn.setMinimumHeight(38)
        self.mode_service_btn.setToolTip(
            "Открыть оригинальное консольное меню zapret: установка автозапуска "
            "как службы Windows, диагностика, обновление hosts и т.д."
        )
        self.mode_service_btn.clicked.connect(self._open_service_menu)
        mode_row.addWidget(self.mode_service_btn)
        selected_card.body.addLayout(mode_row)

        right_col.addWidget(selected_card)

        # --- служба Windows (автозапуск) ---
        service_card = Card()
        service_title = QLabel("СЛУЖБА WINDOWS (АВТОЗАПУСК)")
        service_title.setObjectName("sectionLabel")
        service_card.body.addWidget(service_title)

        self.service_status_label = QLabel("Проверка...")
        self.service_status_label.setWordWrap(True)
        self.service_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        service_card.body.addWidget(self.service_status_label)

        service_btn_row = QVBoxLayout()
        service_btn_row.setSpacing(8)
        self.install_service_btn = QPushButton("⬇  Установить как службу")
        self.install_service_btn.setObjectName("secondaryButton")
        self.install_service_btn.setMinimumHeight(38)
        self.install_service_btn.setToolTip(
            "Выбранная слева стратегия будет запускаться автоматически при "
            "старте Windows, даже если это приложение закрыто."
        )
        self.install_service_btn.clicked.connect(self._on_install_service_clicked)

        self.remove_service_btn = QPushButton("🗑  Удалить службу")
        self.remove_service_btn.setObjectName("dangerButton")
        self.remove_service_btn.setMinimumHeight(38)
        self.remove_service_btn.clicked.connect(self._on_remove_service_clicked)

        service_btn_row.addWidget(self.install_service_btn)
        service_btn_row.addWidget(self.remove_service_btn)
        service_card.body.addLayout(service_btn_row)

        right_col.addWidget(service_card)

        self.install_service_worker: InstallServiceWorker | None = None
        self.remove_service_worker: RemoveServiceWorker | None = None

        right_container = QWidget()
        right_container.setLayout(right_col)
        right_container.setFixedWidth(300)
        content_row.addWidget(right_container, 2)

    # ------------------------------------------------------------------ #
    def reload_strategies(self) -> None:
        for i in reversed(range(self.list_layout.count() - 1)):
            item = self.list_layout.itemAt(i)
            w = item.widget()
            if w:
                w.setParent(None)
        self.rows.clear()

        strategies = discover_strategies()
        self.empty_label.setVisible(len(strategies) == 0)
        state = load_state()

        for strategy in strategies:
            row = StrategyRow(strategy.name, strategy.file_name)
            text, ok = _ping_text_for(strategy.file_name, state.last_test_results)
            row.set_ping_text(text, ok)
            row.clicked.connect(self._on_row_clicked)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self.rows[strategy.file_name] = row

        preselect = state.favorite_strategy or state.last_strategy
        if preselect and preselect in self.rows:
            self.selected_file_name = preselect
            self.rows[preselect].set_selected(True)
        self._update_selected_card()

        running = process_manager.is_running() if process_manager.IS_WINDOWS else False
        self.refresh(running, state.last_strategy if running else None)

    def _on_row_clicked(self, file_name: str) -> None:
        self.selected_file_name = file_name
        for fn, row in self.rows.items():
            row.set_selected(fn == file_name)
        self._update_selected_card()

    def _update_selected_card(self) -> None:
        strategy = find_strategy(self.selected_file_name) if self.selected_file_name else None
        if strategy is None:
            self.selected_name_label.setText("Стратегия не выбрана")
            self.selected_sub_label.setText("Выберите стратегию слева")
            return
        self.selected_name_label.setText(strategy.name)
        self.selected_sub_label.setText("ZAPRET | BAT")

        old_avatar = self.selected_avatar
        self.selected_avatar = make_avatar(strategy.name)
        self.selected_avatar_holder.replaceWidget(old_avatar, self.selected_avatar)
        old_avatar.setParent(None)
        old_avatar.deleteLater()

    def _target_strategy(self) -> Strategy | None:
        if self.selected_file_name:
            strategy = find_strategy(self.selected_file_name)
            if strategy:
                return strategy
        state = load_state()
        for candidate in (state.favorite_strategy, state.last_strategy):
            if candidate:
                strategy = find_strategy(candidate)
                if strategy:
                    return strategy
        strategies = discover_strategies()
        return strategies[0] if strategies else None

    def _on_power_clicked(self) -> None:
        if not is_installed():
            self.main_window.go_to("update")
            return

        running = process_manager.is_running() if process_manager.IS_WINDOWS else False
        if running:
            self.main_window.stop_strategy()
            return

        target = self._target_strategy()
        if target is None:
            QMessageBox.information(self, "Нет стратегий", "Стратегии не найдены.")
            return
        self.power_button.set_busy(True)
        self.main_window.start_strategy(target)

    def _open_service_menu(self) -> None:
        if not process_manager.IS_WINDOWS:
            QMessageBox.warning(self, "Только Windows", "service.bat запускается только на Windows.")
            return
        if not is_installed():
            QMessageBox.information(self, "zapret не установлен", "Сначала установите zapret.")
            return
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "service.bat", "service.bat"],
            cwd=str(ZAPRET_DIR),
        )

    def _on_install_service_clicked(self) -> None:
        if not process_manager.IS_WINDOWS:
            QMessageBox.warning(self, "Только Windows", "Служба Windows доступна только на Windows.")
            return
        if not is_installed():
            QMessageBox.information(self, "zapret не установлен", "Сначала установите zapret.")
            return

        target = self._target_strategy()
        if target is None:
            QMessageBox.information(self, "Нет стратегий", "Стратегии не найдены.")
            return

        confirm = _confirm(
            self,
            "Установить как службу?",
            f'Стратегия "{target.name}" будет запускаться автоматически при '
            f"старте Windows, даже если это приложение закрыто.\n\n"
            f"Если уже установлена другая служба zapret - она будет заменена.\n\n"
            f"Продолжить?",
        )
        if not confirm:
            return

        self.install_service_btn.setEnabled(False)
        self.remove_service_btn.setEnabled(False)
        self.service_status_label.setText("Устанавливаю службу...")
        self.main_window.set_busy(True, f"Устанавливаю службу для {target.name}...")

        self.install_service_worker = InstallServiceWorker(target)
        self.install_service_worker.log.connect(lambda msg: self.service_status_label.setText(msg))
        self.install_service_worker.finished_ok.connect(self._on_install_service_finished)
        self.install_service_worker.finished_error.connect(self._on_service_error)
        self.install_service_worker.start()

    def _on_install_service_finished(self, success: bool, full_log: str) -> None:
        self.install_service_btn.setEnabled(True)
        self.remove_service_btn.setEnabled(True)
        self.main_window.set_busy(False)
        self._refresh_service_status()

        if success:
            QMessageBox.information(
                self, "Готово",
                "Служба установлена и запущена. Обход блокировок теперь будет работать "
                "даже после перезагрузки компьютера или закрытия этого приложения."
            )
        else:
            _show_log_dialog(
                self, "Не удалось установить службу автоматически",
                "Автоматическая установка не завершилась уверенным успехом. "
                "Вот полный лог service.bat - возможно, проблему видно в нём:\n\n" + full_log
                + '\n\nМожно также открыть "Меню service.bat" и установить вручную.'
            )

    def _on_remove_service_clicked(self) -> None:
        if not process_manager.IS_WINDOWS:
            QMessageBox.warning(self, "Только Windows", "Служба Windows доступна только на Windows.")
            return

        confirm = _confirm(
            self, "Удалить службу?",
            "Служба zapret (автозапуск при старте Windows) будет удалена. "
            "Обычный запуск через кнопку подключения продолжит работать как раньше.\n\n"
            "Продолжить?",
        )
        if not confirm:
            return

        self.install_service_btn.setEnabled(False)
        self.remove_service_btn.setEnabled(False)
        self.service_status_label.setText("Удаляю службу...")
        self.main_window.set_busy(True, "Удаляю службу...")

        self.remove_service_worker = RemoveServiceWorker()
        self.remove_service_worker.log.connect(lambda msg: self.service_status_label.setText(msg))
        self.remove_service_worker.finished_ok.connect(self._on_remove_service_finished)
        self.remove_service_worker.finished_error.connect(self._on_service_error)
        self.remove_service_worker.start()

    def _on_remove_service_finished(self, success: bool, full_log: str) -> None:
        self.install_service_btn.setEnabled(True)
        self.remove_service_btn.setEnabled(True)
        self.main_window.set_busy(False)
        self._refresh_service_status()
        QMessageBox.information(self, "Готово", "Служба удалена.")

    def _on_service_error(self, message: str) -> None:
        self.install_service_btn.setEnabled(True)
        self.remove_service_btn.setEnabled(True)
        self.main_window.set_busy(False)
        self._refresh_service_status()
        QMessageBox.warning(self, "Ошибка", message)

    def _refresh_service_status(self) -> None:
        if not process_manager.IS_WINDOWS:
            self.service_status_label.setText("Доступно только на Windows")
            self.install_service_btn.setEnabled(False)
            self.remove_service_btn.setEnabled(False)
            return

        status = service_manager.get_service_status()
        name = service_manager.get_installed_service_strategy_name()
        if status == "running":
            suffix = f" ({name})" if name else ""
            self.service_status_label.setText(f"● Служба работает{suffix} - запускается вместе с Windows")
            self.service_status_label.setStyleSheet(f"color: {SUCCESS}; font-size: 11px; font-weight: 600;")
        elif status == "stopped":
            self.service_status_label.setText("Служба установлена, но остановлена")
            self.service_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        else:
            self.service_status_label.setText("Служба не установлена (используется обычный запуск)")
            self.service_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")

    def refresh(self, running: bool, current_file_name: str | None) -> None:
        installed = is_installed()
        self.install_card.setVisible(not installed)
        self.power_button.setEnabled(installed or running)
        self.power_button.set_busy(False)
        self.power_button.set_connected(running)

        for fn, row in self.rows.items():
            row.set_active(running and fn == current_file_name)

        self._refresh_service_status()

        if running and current_file_name:
            self.status_caption.setText(f"Запущена стратегия: {current_file_name}")
        elif running and not installed:
            self.status_caption.setText(
                "⚠ Обнаружен уже запущенный процесс winws.exe (не из этого приложения). "
                "Кнопка остановит его так же, как и свой."
            )
        elif running:
            self.status_caption.setText("winws.exe запущен")
        else:
            self.status_caption.setText("")


# --------------------------------------------------------------------------- #
# Автоподбор
# --------------------------------------------------------------------------- #
class AutoTestPage(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.main_window = main_window
        self.worker: AutoTestWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Автоподбор стратегии")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Приложение по очереди запустит каждую стратегию и проверит доступность "
            "Discord и YouTube, затем предложит лучший вариант."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        control_card = Card()
        self.status_label = QLabel("Готов к запуску")
        control_card.body.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        control_card.body.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.start_button = QPushButton("Начать автотест")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_test)
        self.cancel_button = QPushButton("Отменить")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.cancel_test)
        self.cancel_button.setEnabled(False)
        btn_row.addWidget(self.start_button)
        btn_row.addWidget(self.cancel_button)
        btn_row.addStretch(1)
        control_card.body.addLayout(btn_row)
        root.addWidget(control_card)

        results_label = QLabel("РЕЗУЛЬТАТЫ")
        results_label.setObjectName("sectionLabel")
        root.addWidget(results_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setSpacing(8)
        self.results_layout.addStretch(1)
        scroll.setWidget(self.results_container)
        root.addWidget(scroll, 1)

    def start_test(self) -> None:
        if not is_installed():
            QMessageBox.information(self, "zapret не установлен", "Сначала установите zapret на странице «Обновление».")
            return

        strategies = discover_strategies()
        if not strategies:
            QMessageBox.information(self, "Нет стратегий", "Стратегии не найдены.")
            return

        self._clear_results()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Подготовка...")

        self.worker = AutoTestWorker(strategies)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.finished_error.connect(self._on_error)
        self.worker.start()
        self.main_window.set_busy(True, "Идёт автотест стратегий...")

    def cancel_test(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("Останавливаю...")

    def _on_progress(self, msg: str, i: int, total: int) -> None:
        self.status_label.setText(f"{msg}  ({i}/{total})")
        self.progress_bar.setValue(int(i / total * 100))

    def _clear_results(self) -> None:
        for i in reversed(range(self.results_layout.count() - 1)):
            item = self.results_layout.itemAt(i)
            w = item.widget()
            if w:
                w.setParent(None)

    def _on_finished(self, results: list) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Тестирование завершено")
        self.progress_bar.setValue(100)
        self.main_window.set_busy(False)

        if not results:
            no_res = QLabel("Нет результатов (тест был отменён до первой стратегии).")
            no_res.setStyleSheet(f"color: {TEXT_SECONDARY};")
            self.results_layout.insertWidget(0, no_res)
            return

        state = load_state()
        state.last_test_results = [
            {
                "strategy": r.strategy.file_name,
                "success": r.success_count,
                "total": r.total_checks,
                "avg_latency_ms": r.avg_latency_ms,
            }
            for r in results
        ]
        save_state(state)

        for rank, result in enumerate(results, start=1):
            self.results_layout.insertWidget(rank - 1, self._build_result_row(rank, result))

        self.main_window.home_page.reload_strategies()

    def _build_result_row(self, rank: int, result) -> QWidget:
        card = Card()
        row = QHBoxLayout()

        best = rank == 1 and result.success_count > 0
        prefix = "🏆 " if best else f"#{rank}  "
        name_label = QLabel(f"{prefix}{result.strategy.name}")
        name_label.setStyleSheet("font-weight: 600;" + (f" color: {SUCCESS};" if best else ""))
        row.addWidget(name_label)
        row.addStretch(1)

        latency = f"{result.avg_latency_ms:.0f} мс" if result.avg_latency_ms else "—"
        info_label = QLabel(f"{result.success_count}/{result.total_checks} проверок · {latency}")
        info_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(info_label)

        apply_btn = QPushButton("Применить")
        apply_btn.setObjectName("secondaryButton")
        apply_btn.clicked.connect(lambda: self._apply_strategy(result.strategy))
        row.addWidget(apply_btn)

        card.body.addLayout(row)
        return card

    def _apply_strategy(self, strategy: Strategy) -> None:
        state = load_state()
        state.favorite_strategy = strategy.file_name
        save_state(state)
        self.main_window.start_strategy(strategy)
        self.main_window.go_to("home")

    def _on_error(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Ошибка")
        self.main_window.set_busy(False)
        QMessageBox.warning(self, "Ошибка автотеста", message)


# --------------------------------------------------------------------------- #
# Обновление
# --------------------------------------------------------------------------- #
class UpdatePage(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.main_window = main_window
        self.install_worker: InstallWorker | None = None
        self.fetch_releases_worker: FetchReleasesWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Обновление")
        title.setObjectName("pageTitle")
        subtitle = QLabel(f"Источник: {GITHUB_RELEASES_PAGE}")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        card = Card()
        self.installed_label = QLabel("Установленная версия: —")
        self.latest_label = QLabel("Последняя версия: —")
        card.body.addWidget(self.installed_label)
        card.body.addWidget(self.latest_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        card.body.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self.progress_label.setVisible(False)
        card.body.addWidget(self.progress_label)

        btn_row = QHBoxLayout()
        self.check_button = QPushButton("Проверить обновления")
        self.check_button.setObjectName("secondaryButton")
        self.check_button.clicked.connect(self.check_updates)
        self.choose_version_button = QPushButton("Выбрать версию...")
        self.choose_version_button.setObjectName("secondaryButton")
        self.choose_version_button.clicked.connect(self.choose_version)
        self.update_button = QPushButton("Скачать и установить одной кнопкой")
        self.update_button.setObjectName("primaryButton")
        self.update_button.clicked.connect(lambda: self.run_update(None))
        btn_row.addWidget(self.check_button)
        btn_row.addWidget(self.choose_version_button)
        btn_row.addWidget(self.update_button)
        btn_row.addStretch(1)
        card.body.addLayout(btn_row)
        root.addWidget(card)

        note = QLabel(
            "При обновлении текущая работающая стратегия будет остановлена, "
            "файлы zapret заменены на последнюю версию, а ваши пользовательские "
            "списки доменов (list-general-user.txt и т.п.) сохранятся."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_SECONDARY};")
        root.addWidget(note)
        root.addStretch(1)

    def check_updates(self) -> None:
        self.check_button.setEnabled(False)
        self.installed_label.setText("Установленная версия: проверка...")
        self.main_window.set_busy(True, "Проверяю обновления...")
        QTimer.singleShot(50, self._do_check)

    def _do_check(self) -> None:
        result: UpdateCheckResult = check_for_updates()
        self.check_button.setEnabled(True)
        self.main_window.set_busy(False)

        self.installed_label.setText(
            f"Установленная версия: {result.installed_version or 'не установлена'}"
        )
        if result.error:
            self.latest_label.setText(f"Не удалось проверить: {result.error}")
            return

        self.latest_label.setText(f"Последняя версия: {result.latest.tag_name}")
        if result.update_available:
            self.update_button.setText(f"Обновить до {result.latest.tag_name}")
        else:
            self.update_button.setText("У вас последняя версия (переустановить)")

    def choose_version(self) -> None:
        self.choose_version_button.setEnabled(False)
        self.main_window.set_busy(True, "Загружаю список версий...")

        self.fetch_releases_worker = FetchReleasesWorker()
        self.fetch_releases_worker.finished_ok.connect(self._on_versions_fetched)
        self.fetch_releases_worker.finished_error.connect(self._on_versions_error)
        self.fetch_releases_worker.start()

    def _on_versions_fetched(self, releases: list) -> None:
        self.choose_version_button.setEnabled(True)
        self.main_window.set_busy(False)

        if not releases:
            QMessageBox.information(self, "Нет версий", "Не удалось получить список версий.")
            return

        dialog, layout = _make_frameless_dialog(self, "Выберите версию zapret", 480, 520)

        hint = QLabel("Можно поставить как самую новую, так и любую из старых версий.")
        hint.setStyleSheet(f"color: {TEXT_SECONDARY};")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        col = QVBoxLayout(container)
        col.setSpacing(8)

        current_version = load_state().installed_version

        for i, release in enumerate(releases):
            row_card = Card()
            row = QHBoxLayout()

            label_text = release.tag_name
            if i == 0:
                label_text += "  (последняя)"
            if release.tag_name == current_version:
                label_text += "  ✓ установлена"
            name_label = QLabel(label_text)
            name_label.setStyleSheet("font-weight: 600;")
            row.addWidget(name_label)

            date_label = QLabel(release.published_at[:10])
            date_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            row.addWidget(date_label)
            row.addStretch(1)

            install_btn = QPushButton("Установить")
            install_btn.setObjectName("secondaryButton")
            install_btn.clicked.connect(
                lambda _checked, r=release: (dialog.accept(), self.run_update(r))
            )
            row.addWidget(install_btn)

            row_card.body.addLayout(row)
            col.addWidget(row_card)

        col.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        dialog.exec()

    def _on_versions_error(self, message: str) -> None:
        self.choose_version_button.setEnabled(True)
        self.main_window.set_busy(False)
        QMessageBox.warning(self, "Ошибка", message)

    def run_update(self, release: ReleaseInfo | None) -> None:
        if process_manager.IS_WINDOWS and process_manager.is_running():
            process_manager.stop_all()

        self.update_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.choose_version_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress_bar.setValue(0)
        label = release.tag_name if release else "последнюю версию"
        self.main_window.set_busy(True, f"Устанавливаю {label}...")

        self.install_worker = InstallWorker(release)
        self.install_worker.progress.connect(self._on_progress)
        self.install_worker.finished_ok.connect(self._on_finished)
        self.install_worker.finished_error.connect(self._on_error)
        self.install_worker.start()

    def _on_progress(self, msg: str, frac: float) -> None:
        self.progress_label.setText(msg)
        self.progress_bar.setValue(int(frac * 100))

    def _on_finished(self, release: ReleaseInfo) -> None:
        state = load_state()
        state.installed_version = release.tag_name
        save_state(state)

        self.update_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.choose_version_button.setEnabled(True)
        self.installed_label.setText(f"Установленная версия: {release.tag_name}")
        self.latest_label.setText(f"Последняя версия: {release.tag_name}")
        self.update_button.setText("У вас последняя версия (переустановить)")
        self.main_window.set_busy(False)
        self.main_window.notify_installed()
        QMessageBox.information(self, "Готово", f"zapret установлен, версия {release.tag_name}.")

    def _on_error(self, message: str) -> None:
        self.update_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.choose_version_button.setEnabled(True)
        self.progress_label.setText("Ошибка")
        self.main_window.set_busy(False)
        QMessageBox.warning(self, "Ошибка обновления", message)


# --------------------------------------------------------------------------- #
# Настройки
# --------------------------------------------------------------------------- #
class SettingsPage(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.main_window = main_window

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Настройки")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        update_card = Card()
        update_title = QLabel("ОБНОВЛЕНИЕ ZAPRETDRUM")
        update_title.setObjectName("sectionLabel")
        update_card.body.addWidget(update_title)

        self.app_version_label = QLabel(f"Текущая версия: {get_app_version()}")
        update_card.body.addWidget(self.app_version_label)

        self.app_update_status_label = QLabel("")
        self.app_update_status_label.setWordWrap(True)
        self.app_update_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        update_card.body.addWidget(self.app_update_status_label)

        self.app_update_progress = QProgressBar()
        self.app_update_progress.setRange(0, 100)
        self.app_update_progress.setVisible(False)
        update_card.body.addWidget(self.app_update_progress)

        app_update_btn_row = QHBoxLayout()
        self.check_app_update_btn = QPushButton("Проверить обновления ZapretDrum")
        self.check_app_update_btn.setObjectName("secondaryButton")
        self.check_app_update_btn.clicked.connect(self._check_app_update)
        self.install_app_update_btn = QPushButton("Обновить ZapretDrum")
        self.install_app_update_btn.setObjectName("primaryButton")
        self.install_app_update_btn.setEnabled(False)
        self.install_app_update_btn.clicked.connect(self._install_app_update)
        app_update_btn_row.addWidget(self.check_app_update_btn)
        app_update_btn_row.addWidget(self.install_app_update_btn)
        app_update_btn_row.addStretch(1)
        update_card.body.addLayout(app_update_btn_row)
        root.addWidget(update_card)

        self._pending_app_release = None
        self.check_app_update_worker = None
        self.download_app_update_worker = None

        card = Card()
        card.body.addWidget(QLabel(f"Папка данных приложения:\n{APP_DATA_DIR}"))
        open_btn = QPushButton("Открыть папку")
        open_btn.setObjectName("secondaryButton")
        open_btn.clicked.connect(lambda: _open_folder(APP_DATA_DIR))
        card.body.addWidget(open_btn)
        root.addWidget(card)

        admin_card = Card()
        admin_text = "Права администратора: "
        admin_text += "есть ✅" if _is_admin() else "нет ⚠️ (нужны для управления winws.exe)"
        admin_card.body.addWidget(QLabel(admin_text))
        root.addWidget(admin_card)

        danger_card = Card()
        danger_card.body.addWidget(QLabel("Опасная зона"))
        reinstall_btn = QPushButton("Переустановить zapret с нуля")
        reinstall_btn.setObjectName("dangerButton")
        reinstall_btn.clicked.connect(self._reinstall)
        danger_card.body.addWidget(reinstall_btn)

        delete_zapret_btn = QPushButton("🗑  Удалить zapret полностью")
        delete_zapret_btn.setObjectName("dangerButton")
        delete_zapret_btn.setToolTip(
            "Удаляет скачанный zapret (и службу автозапуска, если она установлена), "
            "но само приложение ZapretDrum остаётся - можно будет установить zapret заново."
        )
        delete_zapret_btn.clicked.connect(self._delete_zapret_completely)
        danger_card.body.addWidget(delete_zapret_btn)

        uninstall_btn = QPushButton("🗑  Удалить программу полностью")
        uninstall_btn.setObjectName("dangerButton")
        uninstall_btn.setToolTip(
            "Останавливает обход, удаляет службу Windows (если установлена), "
            "запускает деинсталлятор и предлагает стереть скачанный zapret и настройки."
        )
        uninstall_btn.clicked.connect(self._uninstall)
        danger_card.body.addWidget(uninstall_btn)
        root.addWidget(danger_card)

        root.addStretch(1)

    def _check_app_update(self) -> None:
        self.check_app_update_btn.setEnabled(False)
        self.install_app_update_btn.setEnabled(False)
        self.app_update_status_label.setText("Проверяю обновления...")
        self.main_window.set_busy(True, "Проверяю обновления ZapretDrum...")

        self.check_app_update_worker = CheckAppUpdateWorker()
        self.check_app_update_worker.finished_ok.connect(self._on_app_update_checked)
        self.check_app_update_worker.finished_error.connect(self._on_app_update_error)
        self.check_app_update_worker.start()

    def _on_app_update_checked(self, release) -> None:
        self.check_app_update_btn.setEnabled(True)
        self.main_window.set_busy(False)

        if release is None:
            self._pending_app_release = None
            self.install_app_update_btn.setEnabled(False)
            self.app_update_status_label.setText("У вас последняя версия.")
            return

        self._pending_app_release = release
        self.install_app_update_btn.setEnabled(True)
        self.app_update_status_label.setText(
            f"Доступна новая версия: {release.version} (сейчас {get_app_version()})"
        )

    def _on_app_update_error(self, message: str) -> None:
        self.check_app_update_btn.setEnabled(True)
        self.main_window.set_busy(False)
        self.app_update_status_label.setText("Ошибка проверки.")
        QMessageBox.warning(self, "Ошибка", message)

    def _install_app_update(self) -> None:
        if self._pending_app_release is None:
            return

        confirm = _confirm(
            self, "Обновить ZapretDrum?",
            f"Будет скачана и установлена версия {self._pending_app_release.version}. "
            f"Приложение закроется на несколько секунд и само откроется заново после "
            f"установки.\n\nПродолжить?",
        )
        if not confirm:
            return

        self.check_app_update_btn.setEnabled(False)
        self.install_app_update_btn.setEnabled(False)
        self.app_update_progress.setVisible(True)
        self.app_update_progress.setValue(0)
        self.main_window.set_busy(True, "Скачиваю обновление ZapretDrum...")

        self.download_app_update_worker = DownloadAppUpdateWorker(self._pending_app_release)
        self.download_app_update_worker.progress.connect(self._on_app_update_progress)
        self.download_app_update_worker.finished_ok.connect(self._on_app_update_downloaded)
        self.download_app_update_worker.finished_error.connect(self._on_app_update_error)
        self.download_app_update_worker.start()

    def _on_app_update_progress(self, msg: str, frac: float) -> None:
        self.app_update_status_label.setText(msg)
        self.app_update_progress.setValue(int(frac * 100))

    def _on_app_update_downloaded(self) -> None:
        # Установщик уже запущен в тихом режиме - закрываем приложение,
        # чтобы он мог перезаписать файлы. Сам себя он перезапустит.
        QApplication.instance().quit()

    def _reinstall(self) -> None:
        confirm = _confirm(
            self,
            "Переустановить zapret?",
            "Текущая установка будет удалена и скачана заново. Продолжить?",
        )
        if confirm:
            import shutil

            if process_manager.IS_WINDOWS and process_manager.is_running():
                process_manager.stop_all()
            shutil.rmtree(ZAPRET_DIR, ignore_errors=True)
            self.main_window.go_to("update")

    def _delete_zapret_completely(self) -> None:
        confirm = _confirm(
            self,
            "Удалить zapret полностью?",
            f"Будут удалены все файлы zapret ({ZAPRET_DIR}), включая ваши "
            f"пользовательские списки доменов. Если установлена служба "
            f"автозапуска - она тоже будет удалена. Само приложение ZapretDrum "
            f"останется - можно будет установить zapret заново в любой момент.\n\n"
            f"Продолжить?",
        )
        if not confirm:
            return

        if process_manager.IS_WINDOWS and process_manager.is_running():
            process_manager.stop_all()

        if process_manager.IS_WINDOWS and service_manager.get_service_status() != "not_installed":
            self.main_window.set_busy(True, "Удаляю службу перед удалением zapret...")
            self._delete_service_worker = RemoveServiceWorker()
            self._delete_service_worker.finished_ok.connect(lambda *_: self._finish_delete_zapret())
            self._delete_service_worker.finished_error.connect(lambda *_: self._finish_delete_zapret())
            self._delete_service_worker.start()
        else:
            self._finish_delete_zapret()

    def _finish_delete_zapret(self) -> None:
        import shutil

        self.main_window.set_busy(False)
        shutil.rmtree(ZAPRET_DIR, ignore_errors=True)
        QMessageBox.information(self, "Готово", "zapret удалён.")
        self.main_window.notify_installed()
        self.main_window.go_to("home")

    def _uninstall(self) -> None:
        if not process_manager.IS_WINDOWS:
            QMessageBox.warning(self, "Только Windows", "Удаление доступно только на Windows.")
            return

        uninstaller = _find_uninstaller()
        if uninstaller is None:
            QMessageBox.information(
                self, "Установщик не найден",
                "Похоже, приложение запущено не из установленной через инсталлятор "
                "версии (например, как отдельный ZapretDrum.exe без установки).\n\n"
                "Чтобы удалить программу вручную:\n"
                "1. Остановите обход на главной странице\n"
                "2. Если ставили автозапуск - нажмите \"Удалить службу\" на главной\n"
                "3. Удалите файл ZapretDrum.exe и, при желании, папку\n"
                f"{APP_DATA_DIR}",
            )
            return

        confirm = _confirm(
            self, "Удалить программу?",
            "Сейчас остановится обход блокировок (если запущен), запустится "
            "деинсталлятор, и это приложение закроется. Деинсталлятор также "
            "удалит службу автозапуска, если она была установлена, и спросит "
            "про удаление скачанного zapret и настроек.\n\nПродолжить?",
        )
        if not confirm:
            return

        if process_manager.is_running():
            process_manager.stop_all()

        subprocess.Popen([str(uninstaller)])
        QApplication.instance().quit()


# --------------------------------------------------------------------------- #
# Домены - редактирование пользовательских списков без похода в папки
# --------------------------------------------------------------------------- #
class DomainListSection(QWidget):
    """Одна карточка: заголовок, поле добавления и список текущих записей
    с кнопками удаления - для одного из трёх пользовательских файлов zapret."""

    def __init__(self, user_list: user_lists.UserList, parent: QWidget | None = None):
        super().__init__(parent)
        self.user_list = user_list
        self.rows_layout: QVBoxLayout

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = Card()
        title = QLabel(user_list.title)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        card.body.addWidget(title)

        desc = QLabel(user_list.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        card.body.addWidget(desc)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(user_list.placeholder)
        self.input.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Добавить")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self._on_add)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(add_btn)
        card.body.addLayout(input_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(170)
        container = QWidget()
        self.rows_layout = QVBoxLayout(container)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch(1)
        scroll.setWidget(container)
        card.body.addWidget(scroll)

        self.empty_label = QLabel("Список пуст")
        self.empty_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self.empty_label.setVisible(False)
        card.body.addWidget(self.empty_label)

        root.addWidget(card)
        self.reload()

    def reload(self) -> None:
        for i in reversed(range(self.rows_layout.count() - 1)):
            item = self.rows_layout.itemAt(i)
            w = item.widget()
            if w:
                w.setParent(None)

        entries = user_lists.read_entries(self.user_list)
        self.empty_label.setVisible(len(entries) == 0)

        for value in entries:
            row = QWidget()
            row.setObjectName("strategyRow")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 6, 8, 6)
            label = QLabel(value)
            label.setStyleSheet("font-size: 12px;")
            row_layout.addWidget(label)
            row_layout.addStretch(1)
            remove_btn = QPushButton("Удалить")
            remove_btn.setObjectName("dangerButtonSmall")
            remove_btn.clicked.connect(lambda _checked, v=value: self._on_remove(v))
            row_layout.addWidget(remove_btn)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)

    def _on_add(self) -> None:
        ok, error = user_lists.add_entry(self.user_list, self.input.text())
        if ok:
            self.input.clear()
            self.reload()
        else:
            QMessageBox.information(self, "Не удалось добавить", error)

    def _on_remove(self, value: str) -> None:
        confirm = _confirm(
            self, "Удалить из списка?",
            f'Вы действительно хотите удалить "{value}"?',
            ok_text="Удалить", cancel_text="Отмена", danger=True,
        )
        if not confirm:
            return
        user_lists.remove_entry(self.user_list, value)
        self.reload()


class DomainsPage(QWidget):
    def __init__(self, main_window: "MainWindow"):
        super().__init__()
        self.main_window = main_window
        self.sections: list[DomainListSection] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(14)

        title = QLabel("Домены")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Здесь можно вручную указать, какие сайты обходить, а какие не трогать - "
            "прямо в приложении, без поиска и редактирования файлов в папке."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        note = QLabel(
            "⚠ Изменения подействуют при следующем запуске обхода - если он уже "
            "включён, выключите и включите заново на «Главной», чтобы применить."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        root.addWidget(note)

        self.install_card = Card()
        install_label = QLabel("zapret ещё не установлен - сначала установите его на странице «Обновление».")
        install_label.setWordWrap(True)
        self.install_card.body.addWidget(install_label)
        root.addWidget(self.install_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        col = QVBoxLayout(container)
        col.setSpacing(14)

        for user_list in user_lists.USER_LISTS:
            section = DomainListSection(user_list)
            col.addWidget(section)
            self.sections.append(section)

        col.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    def reload(self) -> None:
        installed = is_installed()
        self.install_card.setVisible(not installed)
        for section in self.sections:
            section.setVisible(installed)
            if installed:
                section.reload()


def _find_uninstaller() -> Path | None:
    """
    Ищет unins000.exe рядом с текущим запущенным .exe - его создаёт Inno
    Setup при установке. Если приложение запущено не из установленной
    (через инсталлятор) копии - вернёт None.
    """
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / "unins000.exe"
    return candidate if candidate.exists() else None


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Главное окно
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZapretDrum — обход блокировок Discord/YouTube")
        self.resize(1120, 680)
        self.setStyleSheet(STYLESHEET)

        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Убираем системную рамку - свой заголовок рисуем сами (MainTitleBar).
        # Перетаскивание - вручную мышью за заголовок; изменение размера -
        # через уголок ResizeGrip в углу. Оба варианта - чистый Qt, без
        # обращений к нативному API Windows.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.start_worker: StartStrategyWorker | None = None
        self.stop_worker: StopWorker | None = None

        root = QWidget()
        root.setObjectName("root")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(root)
        outer_layout = QVBoxLayout(root)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.title_bar = MainTitleBar(
            self, "ZapretDrum — обход блокировок Discord/YouTube",
            icon_path=icon_path if icon_path.exists() else None,
        )
        outer_layout.addWidget(self.title_bar)

        content = QWidget()
        root_layout = QHBoxLayout(content)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        outer_layout.addWidget(content, 1)

        # --- сайдбар с подписями ---
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 16, 12, 16)
        side_layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 4, 4, 0)
        brand_row.setSpacing(8)
        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            brand_icon_label = QLabel()
            brand_icon_label.setPixmap(
                QIcon(str(icon_path)).pixmap(26, 26)
            )
            brand_row.addWidget(brand_icon_label)
        brand = QLabel("ZapretDrum")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        side_layout.addLayout(brand_row)
        side_layout.addSpacing(14)

        self.nav_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("home", "🏠", "Главная"),
            ("domains", "🌐", "Домены"),
            ("autotest", "🎯", "Автоподбор"),
            ("update", "⬇️", "Обновление"),
            ("settings", "⚙️", "Настройки"),
        ]
        for key, icon, label in nav_items:
            btn = nav_button(icon, label)
            btn.clicked.connect(lambda _checked, k=key: self.go_to(k))
            side_layout.addWidget(btn)
            self.nav_buttons[key] = btn

        side_layout.addStretch(1)

        self.version_btn = QPushButton(f"v{get_app_version()}")
        self.version_btn.setObjectName("sidebarFooterLink")
        self.version_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.version_btn.setToolTip("Что нового в ZapretDrum")
        self.version_btn.clicked.connect(self._show_changelog)
        side_layout.addWidget(self.version_btn)

        self.author_btn = QPushButton("By Dramster")
        self.author_btn.setObjectName("sidebarFooterLink")
        self.author_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.author_btn.setToolTip("Нашли баг? Напишите разработчику в Telegram")
        self.author_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DEVELOPER_TELEGRAM_URL))
        )
        side_layout.addWidget(self.author_btn)

        root_layout.addWidget(sidebar)

        # --- страницы ---
        self.stack = QStackedWidget()
        self.home_page = HomePage(self)
        self.domains_page = DomainsPage(self)
        self.autotest_page = AutoTestPage(self)
        self.update_page = UpdatePage(self)
        self.settings_page = SettingsPage(self)

        self.pages = {
            "home": self.home_page,
            "domains": self.domains_page,
            "autotest": self.autotest_page,
            "update": self.update_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        root_layout.addWidget(self.stack, 1)

        # уголок для изменения размера окна мышью (без рамки своего resize
        # по краю нет - это единственный способ вручную растянуть окно)
        self.resize_grip = ResizeGrip(self, parent=root)
        self.resize_grip.raise_()

        # Своё разворачивание на весь экран - через геометрию, а не через
        # showMaximized()/isMaximized(). У безрамочных окон в Windows
        # системное состояние "развёрнуто" ненадёжно переживает цикл
        # свернуть-в-трей/восстановить, из-за чего кнопка разворота могла
        # переставать работать. Так мы полностью сами решаем, что считать
        # "развёрнутым", и это не зависит от капризов ОС.
        self.is_custom_maximized = False
        self._normal_geometry = None

        self.go_to("home")
        self.home_page.reload_strategies()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start(2000)
        self._refresh_status()

        if not is_installed():
            self.go_to("update")

    # ------------------------------------------------------------------ #
    def go_to(self, key: str, auto_start: bool = False) -> None:
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "autotest" and auto_start:
            self.autotest_page.start_test()
        if key == "domains":
            self.domains_page.reload()

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.statusBar().showMessage(message if busy else "", 0)

    def _show_changelog(self) -> None:
        self.version_btn.setEnabled(False)
        self.set_busy(True, "Загружаю список изменений...")
        self._changelog_worker = FetchChangelogWorker()
        self._changelog_worker.finished_ok.connect(self._on_changelog_fetched)
        self._changelog_worker.finished_error.connect(self._on_changelog_error)
        self._changelog_worker.start()

    def _on_changelog_fetched(self, entries: list) -> None:
        self.version_btn.setEnabled(True)
        self.set_busy(False)
        _show_changelog_dialog(self, entries)

    def _on_changelog_error(self, message: str) -> None:
        self.version_btn.setEnabled(True)
        self.set_busy(False)
        _show_changelog_dialog(self, [])

    def notify_installed(self) -> None:
        self.home_page.reload_strategies()
        self.domains_page.reload()
        self._refresh_status()

    # ------------------------------------------------------------------ #
    def start_strategy(self, strategy: Strategy) -> None:
        if not process_manager.IS_WINDOWS:
            QMessageBox.warning(
                self, "Только Windows",
                "Запуск zapret возможен только на Windows (winws.exe, драйвер WinDivert)."
            )
            return

        self.set_busy(True, f"Запускаю {strategy.name}...")
        self.start_worker = StartStrategyWorker(strategy)
        self.start_worker.finished_ok.connect(self._on_start_ok)
        self.start_worker.finished_error.connect(self._on_worker_error)
        self.start_worker.start()

    def _on_start_ok(self, file_name: str) -> None:
        state = load_state()
        state.last_strategy = file_name
        save_state(state)
        self.set_busy(False)
        self._refresh_status()

    def stop_strategy(self) -> None:
        if not process_manager.IS_WINDOWS:
            return
        self.set_busy(True, "Останавливаю...")
        self.stop_worker = StopWorker()
        self.stop_worker.finished_ok.connect(lambda: (self.set_busy(False), self._refresh_status()))
        self.stop_worker.finished_error.connect(self._on_worker_error)
        self.stop_worker.start()

    def _on_worker_error(self, message: str) -> None:
        self.set_busy(False)
        self.home_page.power_button.set_busy(False)
        QMessageBox.warning(self, "Ошибка", message)

    # ------------------------------------------------------------------ #
    def _refresh_status(self) -> None:
        running = process_manager.is_running() if process_manager.IS_WINDOWS else False
        current = load_state().last_strategy if running else None
        self.home_page.refresh(running, current)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "resize_grip"):
            root = self.centralWidget()
            self.resize_grip.move(
                root.width() - self.resize_grip.width() - 2,
                root.height() - self.resize_grip.height() - 2,
            )

    def toggle_maximize(self) -> None:
        """Разворачивает/восстанавливает окно вручную через геометрию -
        полностью своя логика, без showMaximized()/showNormal()/isMaximized()."""
        from PyQt6.QtWidgets import QApplication

        if self.is_custom_maximized:
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self.is_custom_maximized = False
        else:
            self._normal_geometry = self.geometry()
            screen = self.screen() or QApplication.primaryScreen()
            self.setGeometry(screen.availableGeometry())
            self.is_custom_maximized = True

        self.title_bar.update_maximize_icon(self.is_custom_maximized)
        self.resize_grip.setVisible(not self.is_custom_maximized)

        root = self.centralWidget()
        root.setProperty("zdMaximized", self.is_custom_maximized)
        root.style().unpolish(root)
        root.style().polish(root)
