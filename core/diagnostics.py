"""Build an explicit, shareable report without reading proxy secrets or lists."""
from datetime import datetime
import platform

import requests

from core import diagnostic_log, process_manager, service_manager, recovery
from core.app_version import get_app_version
from core.paths import ZAPRET_DIR, TG_EXE_PATH, APPUPDATE_API_LATEST_RELEASE, DOWNLOAD_TMP_DIR
from core.state import load_state, STATE_BACKUP, recovery_notice


def build_report(check_network: bool = False) -> str:
    state = load_state()
    processes = process_manager.inspect_processes()
    service, service_error = service_manager.get_service_status_details()
    owner = service_manager.service_belongs_to_install("zapret")
    backup = recovery.latest_backup()
    lines = ["Диагностика ZapretDrum", "Дата: " + datetime.now().astimezone().isoformat(timespec="seconds"),
             "Версия приложения: " + get_app_version(), "Система: " + platform.system() + " " + platform.release(), "",
             "Компоненты:",
             "winws.exe: " + ("на месте" if (ZAPRET_DIR / "bin/winws.exe").is_file() else "отсутствует"),
             "service.bat: " + ("на месте" if (ZAPRET_DIR / "service.bat").is_file() else "отсутствует"),
             "Версия zapret по настройкам: " + (state.installed_version or "неизвестна"),
             "tg-ws-proxy: " + ("установлен" if TG_EXE_PATH.is_file() else "не установлен"),
             "Версия tg-ws-proxy по настройкам: " + (state.tg_installed_version or "неизвестна"), "",
             "Процессы winws: своих — %s, сторонних — %s, путь недоступен — %s" %
             (len(processes["own"]), processes["foreign"], processes["unknown"]),
             "Подтверждённая стратегия обычного запуска: " + (processes["strategy"] or "не определена"),
             "Состояние службы zapret: " + service,
             service_error,
             "Принадлежность службы: " + ("наша установка" if owner else "не подтверждена / служба отсутствует"), "",
             "Копия настроек: " + ("есть" if STATE_BACKUP.is_file() else "пока нет"),
             "Копия zapret: " + (backup.version + " от " + backup.created_at if backup else "пока нет"),
             recovery_notice(), recovery.pending_notice(), ""]
    if check_network:
        try:
            with requests.get(APPUPDATE_API_LATEST_RELEASE, headers={"User-Agent": "ZapretDrum"}, timeout=(5, 5)) as response:
                lines.append("GitHub API: HTTP " + str(response.status_code))
        except requests.RequestException as exc:
            lines.append("GitHub API: ошибка соединения (" + type(exc).__name__ + ")")
    else:
        lines.append("GitHub API: сеть не проверялась. Нажмите «Проверить доступ к GitHub» для запроса.")
    lines += ["", "Проверка файлов и процессов не подтверждает доступность Discord/YouTube.",
              "", "Последние события:", diagnostic_log.recent_log()]
    try:
        logs = list(DOWNLOAD_TMP_DIR.glob("app-update-*/update-helper.log"))
        if logs:
            path = max(logs, key=lambda candidate: candidate.stat().st_mtime)
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 8000))
                lines += ["", "Последний журнал помощника обновления:", stream.read().decode("utf-8-sig", errors="replace")]
    except OSError:
        lines.append("Журнал помощника обновления недоступен.")
    return diagnostic_log.redact("\n".join(lines))
