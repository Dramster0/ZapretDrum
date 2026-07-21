"""
Поиск доступных стратегий (general*.bat и подобных) в папке zapret.

Разработчик Flowseal время от времени переименовывает/добавляет файлы,
поэтому вместо жёстко прошитого списка мы сканируем директорию и
отфильтровываем служебные .bat (service.bat, uninstall_service.bat и т.п.)
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from core.paths import ZAPRET_DIR, NON_STRATEGY_BAT_HINTS


@dataclass
class Strategy:
    name: str          # человекочитаемое имя, например "General (ALT11)"
    file_name: str      # имя файла, например "general (ALT11).bat"
    path: Path

    @property
    def id(self) -> str:
        return self.file_name


def _is_strategy_file(path: Path) -> bool:
    lower = path.name.lower()
    if not lower.endswith(".bat"):
        return False
    if any(hint in lower for hint in NON_STRATEGY_BAT_HINTS):
        return False
    return True


def _pretty_name(file_name: str) -> str:
    name = file_name[:-4]  # убрать .bat
    name = name.replace("_", " ").strip()
    # "general (ALT11)" -> "General (ALT11)"
    name = name[:1].upper() + name[1:]
    return name


def _natural_compare(a: str, b: str) -> int:
    """
    Посимвольное сравнение "как в проводнике Windows": цифры сравниваются
    как число, только когда цифра есть ОДНОВРЕМЕННО в обеих строках на
    этой позиции. Иначе (например ')' против '2') - сравниваются как
    обычные символы. Это важно: "general (ALT).bat" должен идти раньше
    "general (ALT2).bat", а не наоборот.
    """
    ia = ib = 0
    la, lb = len(a), len(b)
    while ia < la and ib < lb:
        ca, cb = a[ia], b[ib]
        if ca.isdigit() and cb.isdigit():
            starta = ia
            while ia < la and a[ia].isdigit():
                ia += 1
            startb = ib
            while ib < lb and b[ib].isdigit():
                ib += 1
            na, nb = int(a[starta:ia]), int(b[startb:ib])
            if na != nb:
                return -1 if na < nb else 1
        else:
            if ca != cb:
                return -1 if ca < cb else 1
            ia += 1
            ib += 1
    remaining_a, remaining_b = la - ia, lb - ib
    if remaining_a != remaining_b:
        return -1 if remaining_a < remaining_b else 1
    return 0


def _natural_sort_key(file_name: str):
    return functools.cmp_to_key(_natural_compare)(file_name.lower())


def discover_strategies() -> list[Strategy]:
    if not ZAPRET_DIR.exists():
        return []

    strategies = []
    for path in ZAPRET_DIR.iterdir():
        if path.is_file() and _is_strategy_file(path):
            strategies.append(
                Strategy(name=_pretty_name(path.name), file_name=path.name, path=path)
            )

    strategies.sort(key=lambda s: _natural_sort_key(s.file_name))
    return strategies


def find_strategy(file_name: str) -> Strategy | None:
    for s in discover_strategies():
        if s.file_name == file_name:
            return s
    return None
