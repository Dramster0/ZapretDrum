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

В автозагрузке лежит обычный ярлык (.lnk), а НЕ скрипт. Раньше здесь был
.vbs-скрипт, который сам вызывал WshShell.Run на exe при каждом входе в
систему - и выяснилось, что это в точности тот паттерн, который правило
защиты Windows Attack Surface Reduction "Блокировать запуск исполняемого
содержимого из VBScript/JavaScript" блокирует по умолчанию во многих
конфигурациях - часто без всякого видимого предупреждения (просто "ничего
не происходит"). Обычный .lnk-ярлык под это правило не подпадает - это
ровно то, как оформляют автозапуск подавляющее большинство обычных
трей-программ, и Windows такому запуску доверяет.

Сам .lnk создаётся через одноразовый VBS-помощник (запускается один раз, в
момент нажатия "Включить автозапуск", и сразу удаляется) - он не запускает
tg-ws-proxy, а только вызывает штатный метод WScript.Shell.CreateShortcut,
поэтому под то же самое правило ASR не попадает (там нет запуска exe).
Это позволяет обойтись без дополнительной библиотеки (pywin32/winshell)
для работы с .lnk-файлами.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import psutil

from core.paths import TG_DIR, TG_EXE_PATH, TG_EXE_NAME, TG_AUTOSTART_SHORTCUT_NAME, windows_startup_folder

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


def _autostart_shortcut_path() -> Path:
    return windows_startup_folder() / TG_AUTOSTART_SHORTCUT_NAME


def _legacy_autostart_script_path() -> Path:
    """Путь старого .vbs-варианта автозапуска (версии до фикса ASR) - чтобы
    можно было подчистить его при переходе на .lnk-ярлык."""
    return windows_startup_folder() / "ZapretDrum-TgWsProxy.vbs"


def is_autostart_enabled() -> bool:
    # Важно: проверяем ОБА варианта. Если бы тут смотрели только на новый
    # .lnk, приложение считало бы автозапуск выключенным, даже если на
    # самом деле в автозагрузке всё ещё лежит старый (нерабочий) .vbs -
    # из-за этого кнопка "Выключить автозапуск" становилась бы неактивной,
    # и убрать битый старый файл через интерфейс было бы невозможно.
    return _autostart_shortcut_path().exists() or _legacy_autostart_script_path().exists()


def _create_shortcut() -> None:
    """Общая часть создания .lnk - используется и enable_autostart(), и
    автоматической миграцией со старого .vbs."""
    shortcut_path = _autostart_shortcut_path()
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    helper_script = TG_DIR / "_create_shortcut_helper.vbs"
    helper_content = (
        # On Error Resume Next - если Shortcut.Save вдруг не удастся (мало
        # ли по какой причине), скрипт просто тихо завершится, а не
        # покажет своё модальное окно ошибки, которое зависло бы и не
        # дало wscript.exe завершиться - именно это и привело к таймауту
        # и краху приложения ниже.
        "On Error Resume Next\r\n"
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'Set Shortcut = WshShell.CreateShortcut("{shortcut_path}")\r\n'
        f'Shortcut.TargetPath = "{TG_EXE_PATH}"\r\n'
        'Shortcut.Arguments = "--portable"\r\n'
        f'Shortcut.WorkingDirectory = "{TG_DIR}"\r\n'
        "Shortcut.WindowStyle = 7\r\n"
        "Shortcut.Save\r\n"
    )
    # ВАЖНО: Windows Script Host не распознаёт обычный UTF-8 (без BOM) как
    # Unicode - он читает файл как будто он в системной ANSI-кодировке
    # (например, CP1251 на русской Windows), из-за чего любые кириллические
    # символы в пути (например, "C:\Users\Руслан\...") превращаются в
    # нечитаемую кашу, и путь перестаёт существовать. WSH корректно
    # распознаёт Unicode-скрипты только по BOM UTF-16LE - поэтому пишем
    # именно так, а не как обычный текстовый файл.
    helper_script.write_text(helper_content, encoding="utf-16")
    try:
        # Даже если wscript.exe всё-таки зависнет (например, из-за старой
        # версии скрипта без On Error Resume Next, или по любой другой
        # причине) - ловим TimeoutExpired и любые другие ошибки запуска
        # сами, чтобы это никогда не роняло всё приложение необработанным
        # исключением, как это произошло раньше.
        subprocess.run(
            ["wscript.exe", str(helper_script)],
            timeout=10,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        )
    except subprocess.TimeoutExpired:
        pass
    except OSError:
        pass
    finally:
        helper_script.unlink(missing_ok=True)

    if not shortcut_path.exists():
        raise TgManagerError(
            "Не удалось создать ярлык автозагрузки. Попробуйте добавить папку "
            "tg-ws-proxy в исключения антивируса и повторить."
        )


def migrate_legacy_autostart() -> None:
    """
    Автоматически заменяет старый .vbs-автозапуск (версии до фикса ASR) на
    новый .lnk-ярлык - без участия пользователя. Вызывается при каждом
    открытии вкладки «Telegram», ничего не делает, если старого файла нет
    (безопасно вызывать многократно). Это чинит ситуацию, когда у
    пользователя автозапуск уже был включён ДО обновления: раньше ему
    пришлось бы самому сообразить нажать "Выключить" и "Включить" заново,
    хотя интерфейс из-за старого бага даже не показывал, что автозапуск
    вообще на что-то включён.
    """
    if not IS_WINDOWS:
        return
    legacy = _legacy_autostart_script_path()
    if not legacy.exists():
        return

    legacy.unlink()
    if TG_EXE_PATH.exists():
        try:
            _create_shortcut()
        except Exception:  # noqa: BLE001
            # Эта функция запускается сама, без участия пользователя, при
            # каждом открытии вкладки - она не должна суметь уронить
            # приложение вообще ни при каких обстоятельствах. Если не
            # получилось - пользователь всё равно увидит актуальный
            # статус на вкладке и сможет включить автозапуск вручную.
            pass


def enable_autostart() -> None:
    _require_windows()
    if not TG_EXE_PATH.exists():
        raise TgManagerError("Сначала установите tg-ws-proxy на странице «Обновление».")

    # На случай, если остался старый .vbs-скрипт от прошлой версии -
    # убираем его, чтобы не осталось двух конфликтующих записей автозапуска.
    legacy = _legacy_autostart_script_path()
    if legacy.exists():
        legacy.unlink()

    _create_shortcut()


def disable_autostart() -> None:
    shortcut_path = _autostart_shortcut_path()
    if shortcut_path.exists():
        shortcut_path.unlink()

    legacy = _legacy_autostart_script_path()
    if legacy.exists():
        legacy.unlink()


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
