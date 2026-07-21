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


def _relaunch_as_admin_windows() -> bool:
    """Возвращает True, если удалось запросить повышение прав (и старый процесс можно закрывать)."""
    import ctypes

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()  # type: ignore[attr-defined]
    except Exception:
        is_admin = False

    if is_admin:
        return False

    params = " ".join(f'"{arg}"' for arg in sys.argv)
    try:
        ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", sys.executable, params, None, 1
        )
        return True
    except Exception:
        # Пользователь отменил UAC-запрос или что-то пошло не так -
        # продолжаем без прав администратора (часть функций будет недоступна).
        return False


def main() -> None:
    if sys.platform == "win32":
        if _relaunch_as_admin_windows():
            sys.exit(0)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from ui.main_window import MainWindow
    from ui.theme import STYLESHEET
    from core.paths import resource_path

    app = QApplication(sys.argv)
    app.setApplicationName("ZapretDrum")
    # Стиль на уровне приложения, а не только окна - иначе диалоги
    # (QDialog для лога службы, выбора версии и т.д.) остаются в
    # системной светлой теме, т.к. это отдельные top-level окна.
    app.setStyleSheet(STYLESHEET)

    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
