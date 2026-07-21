"""
Управление пользовательскими списками доменов/подсетей zapret.

Сам zapret поддерживает три "пользовательских" файла в lists/ (создаются
автоматически при первом запуске стратегии, если их ещё нет):

  - list-general-user.txt   - домены, которые нужно ДОБАВИТЬ к обходу
  - list-exclude-user.txt   - домены, которые нужно ИСКЛЮЧИТЬ из обхода
  - ipset-exclude-user.txt  - подсети (IP/CIDR), исключаемые из обхода

Формат простой текстовый: одна запись на строку, пустые строки и строки,
начинающиеся с '#', игнорируются как комментарии (значит, обрабатывать их
безопасно - мы такие строки просто не трогаем и не показываем на удаление).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.paths import ZAPRET_DIR


@dataclass(frozen=True)
class UserList:
    key: str
    title: str
    file_name: str          # путь относительно ZAPRET_DIR
    placeholder: str
    description: str
    is_domain: bool = True   # False - для IP/CIDR (другая валидация)


USER_LISTS: list[UserList] = [
    UserList(
        key="general",
        title="✅  Разблокировать ещё один сайт",
        file_name="lists/list-general-user.txt",
        placeholder="например: rutracker.org",
        description=(
            "Если какой-то сайт не открывается (кроме Discord и YouTube - для них "
            "обход уже настроен по умолчанию), впишите его адрес сюда, и приложение "
            "будет пытаться разблокировать его тоже. Достаточно просто адреса сайта, "
            "без https:// и слэшей в конце."
        ),
    ),
    UserList(
        key="exclude",
        title="🚫  Не трогать этот сайт",
        file_name="lists/list-exclude-user.txt",
        placeholder="например: sberbank.ru",
        description=(
            "Если из-за обхода блокировок какой-то сайт наоборот стал работать хуже "
            "или странно себя вести - впишите его сюда, чтобы приложение его больше "
            "не трогало вообще."
        ),
    ),
    UserList(
        key="ipset_exclude",
        title="⚙️  Не трогать эту подсеть (для опытных)",
        file_name="lists/ipset-exclude-user.txt",
        placeholder="например: 192.168.1.0/24",
        description=(
            "То же самое, что и выше, но не по адресу сайта, а по диапазону "
            "IP-адресов. Обычному пользователю это не нужно - используйте, только "
            "если точно знаете, что делаете."
        ),
        is_domain=False,
    ),
]


def _path_for(user_list: UserList) -> Path:
    return ZAPRET_DIR / user_list.file_name


def read_entries(user_list: UserList) -> list[str]:
    path = _path_for(user_list)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def _write_entries(user_list: UserList, entries: list[str]) -> None:
    path = _path_for(user_list)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(entries)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def add_entry(user_list: UserList, raw_value: str) -> tuple[bool, str]:
    """Возвращает (успех, сообщение_об_ошибке)."""
    value = raw_value.strip()
    if not value:
        return False, "Сначала введите адрес сайта."

    if user_list.is_domain:
        value = value.replace("https://", "").replace("http://", "")
        value = value.strip("/ ").split("/")[0]
        if not value or " " in value or "." not in value:
            return False, "Похоже, это не адрес сайта. Введите просто, например, discord.com - без https:// и лишнего."
    else:
        if " " in value:
            return False, "Введите IP-адрес или подсеть в формате CIDR, например 192.168.1.0/24."

    entries = read_entries(user_list)
    if value.lower() in (e.lower() for e in entries):
        return False, "Этот адрес уже есть в списке."

    entries.append(value)
    _write_entries(user_list, entries)
    return True, ""


def remove_entry(user_list: UserList, value: str) -> None:
    entries = [e for e in read_entries(user_list) if e != value]
    _write_entries(user_list, entries)
