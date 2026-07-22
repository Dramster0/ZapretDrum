"""
Обнаружение уже установленных (не через ZapretDrum) копий
zapret-discord-youtube и tg-ws-proxy на компьютере пользователя.

У обеих программ нет фиксированного места установки - люди обычно просто
распаковывают/скачивают их куда попало (рабочий стол, загрузки, C:\\zapret,
C:\\tg-ws-proxy и т.п.). У zapret ещё бывает служба Windows, поставленная
вручную через штатный service.bat - служба называется так же, как и та,
что ставит сам ZapretDrum ("zapret") - поэтому если у пользователя такая
служба уже есть, кнопка "Установить как службу" в приложении не сработает
(служба с этим именем уже занята), плюс на диске будут висеть два
независимых набора файлов.

Модуль только НАХОДИТ такие вещи (detect/detect_tg) - ничего не удаляет и
не останавливает сам. Решение и подтверждение - на пользователе, через
диалог в UI; удаление делает отдельная функция (resolve/resolve_tg).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from core.paths import ZAPRET_DIR, TG_DIR

IS_WINDOWS = sys.platform == "win32"

# Имена служб, которые создаёт штатный service.bat из состава
# zapret-discord-youtube (то же самое, что core.service_manager.SERVICE_NAME
# и что чистит наш собственный installer/setup.iss при удалении).
KNOWN_SERVICE_NAMES = ("zapret", "WinDivert", "WinDivert14")

# Куда чаще всего люди вручную распаковывают zapret - проверяем сам путь
# и один уровень вложенных папок, без рекурсивного обхода всего диска.
_CANDIDATE_ROOTS = (
    "~/Desktop",
    "~/Downloads",
    "C:/zapret",
    "C:/Program Files/zapret",
    "C:/Program Files (x86)/zapret",
)


@dataclass
class FoundProcess:
    pid: int
    exe_path: str


@dataclass
class FoundService:
    name: str
    binary_path: str


@dataclass
class ConflictReport:
    processes: list[FoundProcess] = field(default_factory=list)
    services: list[FoundService] = field(default_factory=list)
    folders: list[Path] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.processes or self.services or self.folders)


def _own_dir() -> Path | None:
    try:
        return ZAPRET_DIR.resolve()
    except Exception:
        return None


def _is_foreign(path: Path) -> bool:
    """True, если path не находится внутри папки zapret, которой управляет сам ZapretDrum."""
    own = _own_dir()
    if own is None:
        return True
    try:
        path.resolve().relative_to(own)
        return False
    except (ValueError, OSError):
        return True


def _find_processes() -> list[FoundProcess]:
    found = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name != "winws.exe":
                continue
            exe = proc.info.get("exe") or ""
            if exe and not _is_foreign(Path(exe)):
                continue  # это наш собственный winws.exe, не чужой
            found.append(FoundProcess(pid=proc.info["pid"], exe_path=exe or "?"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _parse_exe_from_image_path(image_path: str) -> Path | None:
    """ImagePath в реестре обычно вида `"C:\\zapret\\winws.exe" -c ...` (с
    аргументами через пробел) - вытаскиваем сам путь к exe."""
    s = image_path.strip()
    if not s:
        return None
    if s.startswith('"'):
        end = s.find('"', 1)
        return Path(s[1:end]) if end != -1 else None
    return Path(s.split()[0])


def _service_binary_path(name: str) -> str | None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, rf"System\CurrentControlSet\Services\{name}"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ImagePath")
            return str(value)
    except Exception:
        return None


def _find_services() -> list[FoundService]:
    found = []
    for name in KNOWN_SERVICE_NAMES:
        try:
            result = subprocess.run(
                ["sc", "query", name],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
        except Exception:
            continue
        out = (result.stdout or "") + (result.stderr or "")
        if "does not exist" in out.lower():
            continue

        binary_path = _service_binary_path(name) or "?"
        if binary_path != "?":
            exe = _parse_exe_from_image_path(binary_path)
            if exe is not None and not _is_foreign(exe):
                continue  # это наша собственная служба (поставлена самим ZapretDrum), не чужая

        found.append(FoundService(name=name, binary_path=binary_path))
    return found


def _looks_like_zapret_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    if (folder / "winws.exe").exists():
        return True
    try:
        for child in folder.iterdir():
            if child.is_dir() and (child / "winws.exe").exists():
                return True
    except OSError:
        pass
    return False


def _find_folders(processes: list[FoundProcess], services: list[FoundService]) -> list[Path]:
    candidates: set[Path] = set()

    for proc in processes:
        if proc.exe_path and proc.exe_path != "?":
            try:
                candidates.add(Path(proc.exe_path).resolve().parent)
            except OSError:
                pass

    for svc in services:
        if svc.binary_path and svc.binary_path != "?":
            exe = _parse_exe_from_image_path(svc.binary_path)
            if exe and exe.suffix.lower() == ".exe":
                try:
                    candidates.add(exe.resolve().parent)
                except OSError:
                    pass

    for root_str in _CANDIDATE_ROOTS:
        root = Path(root_str).expanduser()
        if _looks_like_zapret_folder(root):
            candidates.add(root.resolve())
        try:
            if root.is_dir():
                for child in root.iterdir():
                    if (
                        child.is_dir()
                        and "zapret" in child.name.lower()
                        and _looks_like_zapret_folder(child)
                    ):
                        candidates.add(child.resolve())
        except OSError:
            pass

    return sorted(c for c in candidates if _is_foreign(c))


def detect() -> ConflictReport:
    """Собирает найденные признаки чужой установки zapret. Ничего не меняет."""
    if not IS_WINDOWS:
        return ConflictReport()

    processes = _find_processes()
    services = _find_services()
    folders = _find_folders(processes, services)
    return ConflictReport(processes=processes, services=services, folders=folders)


def resolve(report: ConflictReport, delete_folders: bool = True) -> list[str]:
    """
    Устраняет найденное: останавливает чужие процессы winws.exe,
    останавливает и удаляет конфликтующие службы, и (если
    delete_folders=True) удаляет найденные папки с файлами. Не бросает
    исключения - возвращает построчный лог того, что получилось и что
    нет, для показа пользователю.
    """
    if not IS_WINDOWS:
        return []

    log: list[str] = []

    for proc in report.processes:
        try:
            p = psutil.Process(proc.pid)
            p.terminate()
            try:
                p.wait(timeout=5)
            except psutil.TimeoutExpired:
                p.kill()
            log.append(f"Процесс winws.exe (PID {proc.pid}) остановлен.")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            log.append(f"Не удалось остановить процесс PID {proc.pid}: {exc}")

    for svc in report.services:
        try:
            subprocess.run(
                ["net", "stop", svc.name],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            subprocess.run(
                ["sc", "delete", svc.name],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            log.append(f'Служба "{svc.name}" удалена.')
        except Exception as exc:  # noqa: BLE001
            log.append(f'Не удалось удалить службу "{svc.name}": {exc}')

    if delete_folders:
        for folder in report.folders:
            try:
                shutil.rmtree(folder)
                log.append(f"Папка удалена: {folder}")
            except Exception as exc:  # noqa: BLE001
                log.append(f"Не удалось удалить папку {folder}: {exc}")

    return log


# --------------------------------------------------------------------------- #
# tg-ws-proxy - то же самое, но проще: это одиночный exe без службы Windows
# (трей-приложение), поэтому здесь только процесс и папки, без служб.
# --------------------------------------------------------------------------- #

# Совпадает с именами exe-ассетов, которые публикует Flowseal/tg-ws-proxy
# (TgWsProxy_windows.exe, TgWsProxy_windows_7_64bit.exe и т.п.) - сверяем
# по префиксу без учёта регистра, чтобы не зависеть от конкретной сборки.
_TG_PROCESS_NAME_PREFIX = "tgwsproxy"

_TG_CANDIDATE_ROOTS = (
    "~/Desktop",
    "~/Downloads",
    "C:/tg-ws-proxy",
    "C:/Program Files/tg-ws-proxy",
    "C:/Program Files (x86)/tg-ws-proxy",
)


@dataclass
class TgConflictReport:
    processes: list[FoundProcess] = field(default_factory=list)
    folders: list[Path] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.processes or self.folders)


def _own_tg_dir() -> Path | None:
    try:
        return TG_DIR.resolve()
    except Exception:
        return None


def _is_foreign_to(path: Path, own: Path | None) -> bool:
    if own is None:
        return True
    try:
        path.resolve().relative_to(own)
        return False
    except (ValueError, OSError):
        return True


def _find_tg_processes() -> list[FoundProcess]:
    found = []
    own = _own_tg_dir()
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if not name.startswith(_TG_PROCESS_NAME_PREFIX):
                continue
            exe = proc.info.get("exe") or ""
            if exe and not _is_foreign_to(Path(exe), own):
                continue  # это наш собственный tg-ws-proxy, не чужой
            found.append(FoundProcess(pid=proc.info["pid"], exe_path=exe or "?"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _looks_like_tg_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    try:
        for item in folder.iterdir():
            if item.is_file() and item.name.lower().startswith(_TG_PROCESS_NAME_PREFIX):
                return True
    except OSError:
        pass
    return False


def _find_tg_folders(processes: list[FoundProcess]) -> list[Path]:
    own = _own_tg_dir()
    candidates: set[Path] = set()

    for proc in processes:
        if proc.exe_path and proc.exe_path != "?":
            try:
                candidates.add(Path(proc.exe_path).resolve().parent)
            except OSError:
                pass

    for root_str in _TG_CANDIDATE_ROOTS:
        root = Path(root_str).expanduser()
        if _looks_like_tg_folder(root):
            candidates.add(root.resolve())
        try:
            if root.is_dir():
                for child in root.iterdir():
                    if (
                        child.is_dir()
                        and ("tg" in child.name.lower() or "proxy" in child.name.lower())
                        and _looks_like_tg_folder(child)
                    ):
                        candidates.add(child.resolve())
        except OSError:
            pass

    return sorted(c for c in candidates if _is_foreign_to(c, own))


def detect_tg() -> TgConflictReport:
    """Собирает найденные признаки чужой (не через ZapretDrum) установки tg-ws-proxy."""
    if not IS_WINDOWS:
        return TgConflictReport()

    processes = _find_tg_processes()
    folders = _find_tg_folders(processes)
    return TgConflictReport(processes=processes, folders=folders)


def resolve_tg(report: TgConflictReport, delete_folders: bool = True) -> list[str]:
    """Останавливает чужие процессы tg-ws-proxy и (если delete_folders=True)
    удаляет найденные папки с файлами. Не бросает исключения - возвращает
    построчный лог для показа пользователю."""
    if not IS_WINDOWS:
        return []

    log: list[str] = []

    for proc in report.processes:
        try:
            p = psutil.Process(proc.pid)
            p.terminate()
            try:
                p.wait(timeout=5)
            except psutil.TimeoutExpired:
                p.kill()
            log.append(f"Процесс tg-ws-proxy (PID {proc.pid}) остановлен.")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            log.append(f"Не удалось остановить процесс PID {proc.pid}: {exc}")

    if delete_folders:
        for folder in report.folders:
            try:
                shutil.rmtree(folder)
                log.append(f"Папка удалена: {folder}")
            except Exception as exc:  # noqa: BLE001
                log.append(f"Не удалось удалить папку {folder}: {exc}")

    return log
