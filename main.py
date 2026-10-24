"""
Точка входа ZapretDrum.

На Windows приложению нужны права администратора, чтобы:
  - устанавливать/останавливать драйвер WinDivert,
  - завершать процесс winws.exe.
Поэтому при обычном запуске без прав администратора мы перезапускаем
себя же через ShellExecuteW с verb="runas" (стандартный запрос UAC).
"""
from __future__ import annotations

import sys
import subprocess


def _relaunch_as_admin_windows() -> bool:
    """Возвращает True, если удалось запросить повышение прав (и старый процесс можно закрывать)."""
    import ctypes

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()  # type: ignore[attr-defined]
    except Exception:
        is_admin = False

    if is_admin:
        return False

    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    params = subprocess.list2cmdline(args)
    try:
        result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", sys.executable, params, None, 1
        )
        return result > 32
    except Exception:
        # Пользователь отменил UAC-запрос или что-то пошло не так -
        # продолжаем без прав администратора (часть функций будет недоступна).
        return False


def main() -> None:
    if sys.platform == "win32":
        if _relaunch_as_admin_windows():
            sys.exit(0)

    from core.diagnostic_log import setup_logging, logger
    from core.app_version import get_app_version
    setup_logging()
    logger.info("Запуск ZapretDrum %s", get_app_version())

    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtGui import QIcon
    from PyQt6.QtCore import QTimer
    from ui.main_window import MainWindow
    from ui.theme import STYLESHEET
    from core.paths import resource_path

    app = QApplication(sys.argv)
    app.setApplicationName("ZapretDrum")
    app.setQuitOnLastWindowClosed(False)
    # Стиль на уровне приложения, а не только окна - иначе диалоги
    # (QDialog для лога службы, выбора версии и т.д.) остаются в
    # системной светлой теме, т.к. это отдельные top-level окна.
    app.setStyleSheet(STYLESHEET)

    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    from ui.single_instance import SingleInstance
    instance = SingleInstance(app)
    if not instance.acquire():
        if instance.error:
            QMessageBox.information(None, "ZapretDrum", instance.error)
        return

    try:
        from core.app_updater import startup_update_notice
        notice = startup_update_notice()
        if notice and notice[0]:
            # A new onefile process also locks the executable. Do not keep it
            # alive indefinitely while the installer is replacing the app.
            box = QMessageBox(QMessageBox.Icon.Information, "Обновление ZapretDrum", notice[1])
            QTimer.singleShot(3000, box.accept)
            box.exec()
            return

        window = MainWindow()
        instance.activated.connect(window._restore_from_tray)
        window.show()
        if notice:
            QMessageBox.information(window, "Результат обновления", notice[1])
        from core.state import recovery_notice
        from core.recovery import pending_notice
        recovery_message = "\n\n".join(message for message in (recovery_notice(), pending_notice()) if message)
        if recovery_message:
            QMessageBox.warning(window, "Восстановление данных", recovery_message)

        sys.exit(app.exec())
    finally:
        instance.release()
        logger.info("Завершение ZapretDrum")


if __name__ == "__main__":
    main()
