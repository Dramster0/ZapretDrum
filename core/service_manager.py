"""
Установка / удаление стратегии как службы Windows (автозапуск).

zapret поставляется с готовым service.bat, который сам умеет создавать
службу через стандартный `sc create` (без сторонних утилит вроде NSSM).
Вместо того чтобы заново реализовывать разбор аргументов winws.exe
(там нетривиальная логика с кавычками, переносами строк и подстановкой
переменных - легко сломать и получить неработающий обход блокировок),
мы просто управляем тем же самым service.bat через его интерактивное
меню, подавая ответы в stdin - как будто пользователь сам вводит их
с клавиатуры.

Если формат меню в будущей версии service.bat изменится настолько, что
наши текстовые маркеры перестанут находиться, операция просто вернёт
success=False с полным логом - без угадываний и без риска сломать
рабочую стратегию.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

from core.paths import ZAPRET_DIR
from core.strategies import Strategy

SERVICE_NAME = "zapret"
IS_WINDOWS = sys.platform == "win32"

_MARK_MENU = ("Enter choice", "Select option")  # текст меню менялся между версиями service.bat
_MARK_FILE_INDEX = ("Input file index", "Input option")  # тоже менялся
_MARK_PAUSE = "Press any key"

LogCB = Optional[Callable[[str], None]]


class ServiceError(RuntimeError):
    pass


class _InteractiveBatch:
    """Тонкая обёртка над интерактивным cmd-процессом: пишем в stdin,
    читаем сырой вывод байт за байтом (чтобы не зависнуть на строке-приглашении
    без перевода строки, как это делает `set /p`)."""

    def __init__(self, args: list[str], cwd):
        self.proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        )
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while True:
            try:
                chunk = self.proc.stdout.read(1)  # type: ignore[union-attr]
            except Exception:
                break
            if not chunk:
                break
            with self._lock:
                self._buf.extend(chunk)

    def text(self) -> str:
        with self._lock:
            # cp866/cp437 - типичные кодировки консоли Windows; нам важны
            # только ASCII-маркеры, поэтому errors="ignore" достаточно.
            return bytes(self._buf).decode("cp866", errors="ignore")

    def wait_for(self, marker: str | tuple[str, ...], timeout: float = 15.0) -> bool:
        markers = (marker,) if isinstance(marker, str) else marker
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.text()
            if any(m in text for m in markers):
                return True
            time.sleep(0.05)
        return False

    def send(self, line: str) -> None:
        try:
            self.proc.stdin.write((line + "\r\n").encode("utf-8", errors="ignore"))  # type: ignore[union-attr]
            self.proc.stdin.flush()  # type: ignore[union-attr]
        except Exception:
            pass

    def close(self, timeout: float = 5.0) -> None:
        try:
            self.proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


_FILE_LINE_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")


def _find_file_index(listing_text: str, file_name: str) -> int | None:
    target = file_name.strip().lower()
    for line in listing_text.splitlines():
        m = _FILE_LINE_RE.match(line)
        if m and m.group(2).strip().lower() == target:
            return int(m.group(1))
    return None


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise ServiceError("Управление службой доступно только на Windows.")


def install_as_service(strategy: Strategy, log_cb: LogCB = None) -> tuple[bool, str]:
    """
    Устанавливает выбранную стратегию как службу Windows (автозапуск при
    старте системы) через встроенное меню service.bat -> "Install Service".
    Возвращает (успех, полный_текстовый_лог).
    """
    _require_windows()
    if not (ZAPRET_DIR / "service.bat").exists():
        raise ServiceError("Файл service.bat не найден - переустановите zapret.")

    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    # "admin" первым аргументом - чтобы service.bat не пытался сам себя
    # перезапустить через новый UAC-запрос (наш процесс уже с правами админа).
    batch = _InteractiveBatch(["cmd.exe", "/c", "service.bat", "admin"], cwd=ZAPRET_DIR)
    try:
        log("Открываю service.bat...")
        if not batch.wait_for(_MARK_MENU, timeout=15):
            return False, batch.text() + "\n\n[Не дождались главного меню service.bat]"

        log("Выбираю \"Install Service\"...")
        batch.send("1")
        if not batch.wait_for(_MARK_FILE_INDEX, timeout=15):
            return False, batch.text() + "\n\n[Не дождались списка стратегий]"

        index = _find_file_index(batch.text(), strategy.file_name)
        if index is None:
            batch.send("")  # пустой ввод -> service.bat сам завершится
            return False, batch.text() + f'\n\n[Не нашёл "{strategy.file_name}" в списке service.bat]'

        log(f"Устанавливаю службу для {strategy.name}...")
        batch.send(str(index))

        batch.wait_for(_MARK_PAUSE, timeout=25)
        batch.send("")  # проходим "Press any key to continue"

        batch.wait_for(_MARK_MENU, timeout=10)
        batch.send("0")  # Exit

        batch.close()
        full_log = batch.text()
        success = ("CreateService SUCCESS" in full_log) or ("StartService SUCCESS" in full_log)
        return success, full_log
    finally:
        batch.close()


def remove_service(log_cb: LogCB = None) -> tuple[bool, str]:
    """Удаляет службу zapret (и связанные службы WinDivert) через меню service.bat."""
    _require_windows()
    if not (ZAPRET_DIR / "service.bat").exists():
        raise ServiceError("Файл service.bat не найден - переустановите zapret.")

    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    batch = _InteractiveBatch(["cmd.exe", "/c", "service.bat", "admin"], cwd=ZAPRET_DIR)
    try:
        log("Открываю service.bat...")
        if not batch.wait_for(_MARK_MENU, timeout=15):
            return False, batch.text() + "\n\n[Не дождались главного меню service.bat]"

        log("Выбираю \"Remove Services\"...")
        batch.send("2")

        batch.wait_for(_MARK_PAUSE, timeout=15)
        batch.send("")

        batch.wait_for(_MARK_MENU, timeout=10)
        batch.send("0")

        batch.close()
        return True, batch.text()
    finally:
        batch.close()


def get_service_status() -> str:
    """Возвращает 'running' | 'stopped' | 'not_installed'."""
    if not IS_WINDOWS:
        return "not_installed"
    try:
        result = subprocess.run(
            ["sc", "query", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        )
    except Exception:
        return "not_installed"

    out = (result.stdout or "") + (result.stderr or "")
    if "does not exist" in out.lower():
        return "not_installed"
    if "RUNNING" in out:
        return "running"
    if "STOPPED" in out:
        return "stopped"
    return "not_installed"


def get_installed_service_strategy_name() -> str | None:
    """
    Пытается прочитать из реестра имя стратегии, установленной как служба
    (не все версии service.bat пишут это значение - тогда просто вернём None).
    """
    if not IS_WINDOWS:
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"System\CurrentControlSet\Services\zapret"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "zapret-discord-youtube")
            return str(value)
    except Exception:
        return None
