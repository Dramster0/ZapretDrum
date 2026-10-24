"""
Самообновление ZapretDrum (не путать с core.installer, который обновляет
zapret - внешний инструмент).

Идея: у вас есть свой GitHub-репозиторий (APPUPDATE_GITHUB_OWNER/REPO в
core/paths.py), куда GitHub Actions автоматически публикует
ZapretDrum-Setup.exe при каждом новом теге версии (см.
.github/workflows/release.yml). Приложение проверяет там последний релиз,
и если версия новее текущей - предлагает скачать и поставить обновление
одной кнопкой, без похода в браузер.

Технически: скачивается Setup.exe, затем отдельный помощник дожидается
закрытия приложения и запускает установщик в тихом режиме (/VERYSILENT).
"""
from __future__ import annotations

import os
import json
import hashlib
import tempfile
import time
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
import psutil

from core.app_version import get_app_version, is_newer
from core.diagnostic_log import logger
from core.paths import (
    APPUPDATE_API_LATEST_RELEASE,
    APPUPDATE_API_ALL_RELEASES,
    DOWNLOAD_TMP_DIR,
    APP_DATA_DIR,
    ensure_dirs,
)

IS_WINDOWS = sys.platform == "win32"

ProgressCB = Optional[Callable[[str, float], None]]


class AppUpdateError(RuntimeError):
    pass


@dataclass
class AppReleaseInfo:
    tag_name: str
    version: str            # tag_name без ведущей 'v'
    setup_url: str
    setup_name: str
    notes: str
    published_at: str = ""
    size: int = 0
    digest: str = ""


def _headers() -> dict:
    return {"User-Agent": "ZapretDrum", "Accept": "application/vnd.github+json"}


@dataclass
class ChangelogEntry:
    version: str
    published_at: str   # ISO-строка вида '2026-07-04T18:48:00Z'
    notes: str


def fetch_changelog(limit: int = 15) -> list[ChangelogEntry]:
    """
    Список последних релизов ZapretDrum (версия + дата + текст релиза) -
    для окна "Что нового?". Не бросает исключение при сетевой ошибке -
    просто возвращает пустой список, чтобы окно могло показать
    заглушку вместо падения.
    """
    try:
        resp = requests.get(
            APPUPDATE_API_ALL_RELEASES,
            headers=_headers(),
            params={"per_page": min(limit, 100)},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    entries = []
    for item in resp.json():
        entries.append(
            ChangelogEntry(
                version=item.get("tag_name", "").lstrip("vV") or "?",
                published_at=item.get("published_at", "") or "",
                notes=(item.get("body", "") or "").strip(),
            )
        )
    return entries


def check_for_app_update() -> AppReleaseInfo | None:
    """
    Возвращает информацию о новом релизе ZapretDrum, если он новее текущей
    версии, иначе None. Бросает AppUpdateError при сетевых проблемах.
    """
    try:
        resp = requests.get(APPUPDATE_API_LATEST_RELEASE, headers=_headers(), timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AppUpdateError(f"Не удалось проверить обновления ZapretDrum: {exc}") from exc

    data = resp.json()
    tag_name = data.get("tag_name", "")
    version = tag_name.lstrip("vV")
    if not is_newer(version, get_app_version()):
        return None
    assets = data.get("assets", [])
    setup_asset = next(
        (a for a in assets if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower()),
        None,
    )
    if setup_asset is None:
        raise AppUpdateError("В последнем релизе ZapretDrum не найден установщик (.exe).")

    return AppReleaseInfo(
        tag_name=tag_name,
        version=version,
        setup_url=setup_asset["browser_download_url"],
        setup_name=setup_asset["name"],
        notes=data.get("body", "") or "",
        published_at=data.get("published_at", "") or "",
        size=int(setup_asset.get("size") or 0),
        digest=setup_asset.get("digest") or "",
    )


def download_update_installer(
    release: AppReleaseInfo, progress_cb: ProgressCB = None
) -> Path:
    """
    Скачивает установщик обновления. Запуск откладывается до закрытия
    приложения, чтобы установщик не пытался заменить работающий .exe.
    """
    if not IS_WINDOWS:
        raise AppUpdateError("Самообновление доступно только на Windows.")

    ensure_dirs()
    job_dir = Path(tempfile.mkdtemp(prefix="app-update-", dir=DOWNLOAD_TMP_DIR))
    setup_path = job_dir / "ZapretDrum-Setup.exe"
    partial = setup_path.with_suffix(".part")

    def report(msg: str, frac: float) -> None:
        if progress_cb:
            progress_cb(msg, frac)

    report("Скачиваю установщик...", 0.05)
    try:
        with requests.get(release.setup_url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or None
            written = 0
            digest = hashlib.sha256()
            with open(partial, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if total:
                        report("Скачиваю установщик...", min(written / total, 1.0))
            if not written or (release.size and written != release.size):
                raise AppUpdateError("Установщик скачан не полностью. Повторите скачивание.")
            if release.digest.startswith("sha256:") and digest.hexdigest() != release.digest[7:]:
                raise AppUpdateError("Контрольная сумма установщика не совпадает с релизом.")
            with partial.open("rb") as f:
                if f.read(2) != b"MZ":
                    raise AppUpdateError("Вместо установщика получен неподходящий файл.")
            partial.replace(setup_path)
    except (requests.RequestException, OSError) as exc:
        raise AppUpdateError(f"Не удалось скачать установщик: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)

    report("Установщик скачан. Подготавливаю обновление...", 1.0)
    return setup_path


def launch_installer_after_app_exit(setup_path: Path, expected_version: str) -> None:
    """Запускает скрытый помощник, который дождётся закрытия приложения,
    а затем запустит установщик в тихом режиме."""
    if not IS_WINDOWS:
        raise AppUpdateError("Самообновление доступно только на Windows.")

    target_dir = installed_app_directory()
    logger.info("Передача установщику ZapretDrum версии %s", expected_version)
    helper_path = setup_path.parent / "install.ps1"
    log_path = setup_path.parent / "installer.log"
    helper_log = setup_path.parent / "update-helper.log"
    exit_ready = setup_path.parent / "exit.ready"
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    # PyInstaller onefile has a bootloader parent using the same executable.
    processes = [psutil.Process(os.getpid())]
    parent = processes[0].parent()
    if parent and Path(parent.exe()).resolve() == Path(sys.executable).resolve():
        processes.append(parent)
    waits = "\n".join(
        f"Wait-AppProcess -ProcessId {p.pid} -Started {p.create_time():.3f} "
        f"-ExpectedPath {literal(Path(p.exe()).resolve())}"
        for p in processes
    )
    script = f"""$ErrorActionPreference = 'Stop'
$epoch = [DateTime]::SpecifyKind([DateTime]'1970-01-01', [DateTimeKind]::Utc)
$statusPath = {literal(UPDATE_STATUS)}
$helperLog = {literal(helper_log)}
$exitReady = {literal(exit_ready)}
$status = @{{state='waiting'; version={literal(expected_version)}; log={literal(log_path)}; helper_log=$helperLog; helper_pid=$PID; helper_started=0; forced_pids=@(); message=''}}
function Write-HelperLog([string]$Message) {{
    Add-Content -LiteralPath $helperLog -Value ((Get-Date -Format o) + ' ' + $Message) -Encoding UTF8
}}
function Save-Status {{
    $status | ConvertTo-Json | Set-Content -LiteralPath ($statusPath + '.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($statusPath + '.tmp') -Destination $statusPath -Force
}}
function Wait-AppProcess([int]$ProcessId, [double]$Started, [string]$ExpectedPath) {{
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) {{ return }}
    try {{
        # Keep a handle to this instance; never kill by executable name or PID alone.
        $null = $process.Handle
        if ($process.HasExited) {{ return }}
        $actualStarted = ($process.StartTime.ToUniversalTime() - $epoch).TotalSeconds
        if ([Math]::Abs($actualStarted - $Started) -ge 2) {{ return }}
        if (-not [string]::Equals($process.Path, $ExpectedPath, [StringComparison]::OrdinalIgnoreCase)) {{
            throw ('Не удалось подтвердить путь процесса ' + $ProcessId)
        }}
        Write-HelperLog ('Waiting for ZapretDrum PID ' + $ProcessId)
        if (-not $process.WaitForExit(30000)) {{
            Write-HelperLog ('Shutdown timed out; terminating verified PID ' + $ProcessId)
            $process.Kill()
            if (-not $process.WaitForExit(10000)) {{
                throw ('Не удалось завершить ZapretDrum, PID ' + $ProcessId)
            }}
            $status.forced_pids += $ProcessId
            Save-Status
        }}
        Write-HelperLog ('ZapretDrum PID ' + $ProcessId + ' exited')
    }} catch {{
        # The app may have exited between Get-Process and opening its handle.
        if (-not $process.HasExited) {{ throw }}
    }} finally {{
        $process.Dispose()
    }}
}}
try {{
    $status.helper_started = ((Get-Process -Id $PID).StartTime.ToUniversalTime() - $epoch).TotalSeconds
    Write-HelperLog 'Update helper started'
    Save-Status
    # Do not terminate the app unless it has acknowledged the helper and
    # committed to exit, after all managed operations have finished.
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not (Test-Path -LiteralPath $exitReady)) {{
        if ([DateTime]::UtcNow -ge $deadline) {{ throw 'Приложение не подтвердило выход для обновления.' }}
        Start-Sleep -Milliseconds 100
    }}
    Write-HelperLog 'App committed to exit'
    {waits}
    $status.state = 'installing'
    Save-Status
    Write-HelperLog 'Starting installer'
    $installer = Start-Process -FilePath {literal(setup_path)} -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', {literal('/DIR="' + str(target_dir) + '"')}, {literal('/LOG="' + str(log_path) + '"')}) -WindowStyle Hidden -PassThru -Wait
    if ($installer.ExitCode -ne 0) {{ throw ('Установщик завершился с кодом ' + $installer.ExitCode) }}
    $status.state = 'installed'
    Save-Status
    Write-HelperLog 'Installation completed'
}} catch {{
    $status.state = 'failed'
    $status.message = $_.Exception.Message
    Save-Status
    Write-HelperLog $status.message
    exit 1
}}
"""
    try:
        exit_ready.unlink(missing_ok=True)
        helper_path.write_text(script, encoding="utf-8-sig")
        UPDATE_STATUS.write_text(json.dumps({
            "state": "waiting", "version": expected_version, "log": str(log_path),
            "helper_log": str(helper_log),
            "helper_pid": os.getpid(), "helper_started": psutil.Process().create_time(),
        }), encoding="utf-8")
        helper = subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden", "-File", str(helper_path),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=str(setup_path.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        # Do not exit until the helper has acknowledged ownership of the job.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if helper.poll() is not None:
                raise AppUpdateError(f"Помощник обновления завершился до начала установки (код {helper.returncode}).")
            try:
                status = json.loads(UPDATE_STATUS.read_text(encoding="utf-8-sig"))
                ready = (status.get("helper_pid") == helper.pid
                         and status.get("state") == "waiting")
            except (OSError, ValueError):
                ready = False
            if ready:
                exit_ready.write_text("exit requested\n", encoding="ascii")
                logger.info("Помощник принял обновление; запрошен полный выход")
                return
            time.sleep(0.1)
        helper.terminate()
        helper.wait(timeout=5)
        raise AppUpdateError("Помощник обновления не ответил. Приложение останется открытым; повторите попытку.")
    except OSError as exc:
        UPDATE_STATUS.unlink(missing_ok=True)
        raise AppUpdateError(f"Не удалось запустить установку обновления: {exc}") from exc


UPDATE_STATUS = APP_DATA_DIR / "app_update.json"


def installed_app_directory() -> Path:
    directory = Path(sys.executable).resolve().parent
    if not getattr(sys, "frozen", False) or not (directory / "unins000.exe").is_file():
        raise AppUpdateError(
            "Автообновление доступно для установленной версии ZapretDrum. "
            "Установите приложение через ZapretDrum-Setup.exe и запустите его через ярлык."
        )
    return directory


def startup_update_notice() -> tuple[bool, str] | None:
    """Return (must_exit, message); keep the installation result until read."""
    if not UPDATE_STATUS.exists():
        return None
    try:
        status = json.loads(UPDATE_STATUS.read_text(encoding="utf-8-sig"))
        if not isinstance(status, dict):
            raise ValueError("Invalid update status")
        if status.get("state") in ("waiting", "installing"):
            try:
                process = psutil.Process(int(status["helper_pid"]))
                alive = abs(process.create_time() - float(status["helper_started"])) < 2
            except (psutil.Error, KeyError, ValueError):
                alive = False
            if alive:
                return True, "Обновление ZapretDrum ещё выполняется. Откройте приложение после завершения установки."
        version = status.get("version", "?")
        if status.get("state") == "installed" and get_app_version() == version:
            message = f"ZapretDrum успешно обновлён до {version}."
        else:
            message = (f"Не удалось подтвердить обновление до {version}. Сейчас запущена версия {get_app_version()}.\n"
                       + status.get("message", "") + "\nЖурнал установки: " + status.get("log", str(UPDATE_STATUS)))
            if status.get("helper_log"):
                message += "\nЖурнал обновления: " + str(status["helper_log"])
        UPDATE_STATUS.unlink()
        logger.info("Результат самообновления: %s", message)
        return False, message
    except (OSError, ValueError, TypeError):
        return False, f"Не удалось прочитать результат обновления. Подробности: {UPDATE_STATUS}"
