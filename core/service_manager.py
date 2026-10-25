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
import ctypes
from ctypes import wintypes
from typing import Callable, Optional
from pathlib import Path

from core.paths import ZAPRET_DIR
from core.strategies import Strategy

SERVICE_NAME = "zapret"
IS_WINDOWS = sys.platform == "win32"


def service_belongs_to_install(name: str) -> bool:
    """Never stop/delete a shared driver or service owned by another install."""
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"System\CurrentControlSet\Services\{name}") as key:
            command = str(winreg.QueryValueEx(key, "ImagePath")[0]).strip()
        path = command.split('"')[1] if command.startswith('"') else command.split()[0]
        if path.startswith("\\??\\"):
            path = path[4:]
        return Path(path).resolve().is_relative_to(ZAPRET_DIR.resolve())
    except (OSError, ValueError, IndexError):
        return False

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
    for name in ("zapret", "WinDivert", "WinDivert14"):
        result = subprocess.run(["sc", "query", name], capture_output=True,
                                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0 and not service_belongs_to_install(name):
            raise ServiceError(f"Служба {name} принадлежит другой установке. Сначала устраните конфликт.")

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
        success = service_belongs_to_install(SERVICE_NAME) and get_service_status() == "running"
        return success, full_log
    finally:
        batch.close()


def remove_service(log_cb: LogCB = None) -> tuple[bool, str]:
    """Remove only services whose executable belongs to this installation."""
    _require_windows()
    lines = []
    success = True
    for name in ("zapret", "WinDivert", "WinDivert14"):
        query = subprocess.run(["sc", "query", name], capture_output=True,
                               timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if query.returncode == 1060:
            continue
        if query.returncode != 0 or not service_belongs_to_install(name):
            lines.append(f"Служба {name} пропущена: принадлежность не подтверждена.")
            if name == "zapret":
                success = False
            continue
        subprocess.run(["sc", "stop", name], capture_output=True,
                       timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        result = subprocess.run(["sc", "delete", name], capture_output=True,
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        ok = result.returncode in (0, 1060, 1072)
        success = success and ok
        lines.append(f"{name}: " + ("удалена или отмечена для удаления Windows" if ok else f"ошибка {result.returncode}"))
        if log_cb:
            log_cb(lines[-1])
    return success, "\n".join(lines)


class _ServiceStatus(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in (
        "service_type", "current_state", "controls_accepted", "win32_exit_code",
        "service_exit_code", "checkpoint", "wait_hint",
    )]


def _query_service_state() -> int:
    """Query status only: psutil.win_service_get also reads configuration,
    which can fail with Windows error 1734 for a long zapret command line.
    Explicit handle types are required on 64-bit Windows.
    """
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenSCManagerW.restype = wintypes.HANDLE
    api.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenServiceW.restype = wintypes.HANDLE
    api.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ServiceStatus)]
    api.QueryServiceStatus.restype = wintypes.BOOL
    api.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    api.CloseServiceHandle.restype = wintypes.BOOL
    manager = api.OpenSCManagerW(None, None, 0x0001)  # SC_MANAGER_CONNECT
    if not manager:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        service = api.OpenServiceW(manager, SERVICE_NAME, 0x0004)  # SERVICE_QUERY_STATUS
        if not service:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            status = _ServiceStatus()
            if not api.QueryServiceStatus(service, ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            return status.current_state
        finally:
            api.CloseServiceHandle(service)
    finally:
        api.CloseServiceHandle(manager)


def get_service_status_details() -> tuple[str, str]:
    """Keep absent, transitional and unreadable states distinct."""
    if not IS_WINDOWS:
        return "not_installed", ""
    try:
        state = _query_service_state()
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1060:  # ERROR_SERVICE_DOES_NOT_EXIST
            return "not_installed", ""
        if getattr(exc, "winerror", None) == 5:
            return "unknown", "Windows отказала в чтении состояния службы (код 5). Запустите ZapretDrum от имени администратора."
        return "unknown", f"Ошибка чтения состояния службы Windows: {exc}"
    states = {1: "stopped", 2: "start_pending", 3: "stop_pending", 4: "running",
              5: "continue_pending", 6: "pause_pending", 7: "paused"}
    if state not in states:
        return "unknown", f"Windows вернула неизвестное состояние службы: {state}."
    return states[state], ""


def get_service_status() -> str:
    return get_service_status_details()[0]


def set_owned_service_running(running: bool) -> None:
    """Change only our service and wait for the actual state."""
    _require_windows()
    if not service_belongs_to_install(SERVICE_NAME):
        raise ServiceError("Принадлежность службы zapret не подтверждена. Откройте диагностику.")
    target = "running" if running else "stopped"
    if get_service_status() == target:
        return
    result = subprocess.run(["sc", "start" if running else "stop", SERVICE_NAME],
                            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode not in (0, 1056 if running else 1062):
        raise ServiceError(f"Не удалось изменить состояние службы zapret (код {result.returncode}).")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state, error = get_service_status_details()
        if state == target:
            return
        if state == "unknown":
            raise ServiceError("Команда отправлена, но результат не удалось проверить. " + error)
        time.sleep(0.2)
    raise ServiceError("Служба zapret не перешла в ожидаемое состояние: " + target)


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
