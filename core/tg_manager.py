"""
Управление процессом tg-ws-proxy (запуск/остановка/статус) и его
автозапуском вместе с Windows.

tg-ws-proxy - это не консольная стратегия вроде winws.exe, а трей-приложение
со своей иконкой и меню. Поэтому:
  - "запуск" - это просто Popen самого exe с флагом --portable (чтобы все
    настройки и секрет прокси хранились рядом с exe, в TG_DIR, а не
    расползались по %APPDATA%);
  - автозапуск делаем НЕ через службу Windows (как для zapret), а через
    личную папку автозагрузки пользователя (`shell:startup`) - потому что
    служба Windows выполняется в отдельной сессии без доступа к рабочему
    столу пользователя и не смогла бы показать иконку в трее. Это тот же
    способ, которым в системную автозагрузку добавляют себя большинство
    обычных трей-программ (мессенджеры, лаунчеры и т.п.).

Автозапуск оформлен через маленький .vbs-скрипт, а не .lnk-ярлык: так не
нужна дополнительная библиотека (pywin32/winshell) только ради создания
ярлыка, а WScript.Shell.Run с последним параметром False запускает процесс
полностью скрыто, без мелькания окна консоли.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import psutil

from core.paths import TG_DIR, TG_EXE_PATH, TG_EXE_NAME, TG_AUTOSTART_SCRIPT_NAME, windows_startup_folder

IS_WINDOWS = sys.platform == "win32"


class TgManagerError(RuntimeError):
    pass


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise TgManagerError(
            "tg-ws-proxy в этой вкладке поддерживается только на Windows."
        )


def is_installed() -> bool:
    return TG_EXE_PATH.exists()


def _matches(proc: psutil.Process) -> bool:
    try:
        name = (proc.info.get("name") or "").lower()
        if name != TG_EXE_NAME.lower():
            return False
        exe = proc.info.get("exe") or ""
        if exe:
            try:
                return Path(exe).resolve().parent == TG_DIR.resolve()
            except OSError:
                return True
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def is_running() -> bool:
    for proc in psutil.process_iter(["name", "exe"]):
        if _matches(proc):
            return True
    return False


def start() -> None:
    _require_windows()
    if not TG_EXE_PATH.exists():
        raise TgManagerError("tg-ws-proxy не установлен - сначала скачайте его.")
    if is_running():
        return

    creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    subprocess.Popen(
        [str(TG_EXE_PATH), "--portable"],
        cwd=str(TG_DIR),
        creationflags=creationflags,
    )


def stop(timeout: float = 5.0) -> None:
    _require_windows()

    procs = [p for p in psutil.process_iter(["name", "exe"]) if _matches(p)]
    for p in procs:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def _autostart_script_path() -> Path:
    return windows_startup_folder() / TG_AUTOSTART_SCRIPT_NAME


def is_autostart_enabled() -> bool:
    return _autostart_script_path().exists()


def enable_autostart() -> None:
    _require_windows()
    if not TG_EXE_PATH.exists():
        raise TgManagerError("Сначала установите tg-ws-proxy на странице «Обновление».")

    script = _autostart_script_path()
    script.parent.mkdir(parents=True, exist_ok=True)
    # On Error Resume Next + проверка FileExists - на случай, если к моменту
    # следующего входа в Windows exe вдруг пропадёт (антивирус, ручное
    # удаление, что угодно): без этого пользователь при каждом входе в
    # систему видел бы пугающее окно "Windows Script Host: Системе не
    # удаётся найти указанный путь" вместо тихого "просто не запустилось".
    content = (
        "On Error Resume Next\r\n"
        f'Dim exePath : exePath = "{TG_EXE_PATH}"\r\n'
        'Dim fso : Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        "If fso.FileExists(exePath) Then\r\n"
        '    Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'    WshShell.CurrentDirectory = "{TG_DIR}"\r\n'
        '    WshShell.Run Chr(34) & exePath & Chr(34) & " --portable", 0, False\r\n'
        "End If\r\n"
    )
    script.write_text(content, encoding="utf-8")


def disable_autostart() -> None:
    script = _autostart_script_path()
    if script.exists():
        script.unlink()


def delete_completely() -> None:
    """
    Полное удаление tg-ws-proxy: останавливает процесс (если запущен),
    выключает автозапуск и стирает всю папку TG_DIR (сам exe и его
    portable-данные - настройки, секрет прокси, логи). Само приложение
    ZapretDrum при этом не трогается - можно будет установить tg-ws-proxy
    заново с вкладки «Telegram».
    """
    _require_windows()

    if is_running():
        stop()
    disable_autostart()

    if TG_DIR.exists():
        shutil.rmtree(TG_DIR, ignore_errors=True)
