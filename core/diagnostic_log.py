"""Bounded local logs; reports never collect proxy configuration or user lists."""
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from core.paths import LOG_FILE

logger = logging.getLogger("zapretdrum")
log_error = ""


def redact(text: str) -> str:
    def safe_url(match):
        try:
            url = urlsplit(match[0])
            return url.scheme + "://" + (url.hostname or "hidden") + "/…"
        except ValueError:
            return "<адрес скрыт>"

    text = text.replace(str(Path.home()), "%USERPROFILE%")
    text = re.sub(r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+", "%USERPROFILE%", text)
    text = re.sub(r"https?://[^\s\"'<>]+|tg://[^\s\"'<>]+",
                  safe_url, text)
    text = re.sub(r"(?i)((?:secret|token|password|authorization)\s*[=:]\s*)[^\s,;]+", r"\1<скрыто>", text)
    text = re.sub(r"\b[0-9a-fA-F]{32,}\b", "<скрыто>", text)
    return text


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def setup_logging() -> None:
    global log_error
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except OSError as exc:
        log_error = "Журнал недоступен: " + type(exc).__name__
        logger.addHandler(logging.NullHandler())
    original_hook = sys.excepthook

    def exception_hook(kind, value, traceback):
        logger.error("Необработанная ошибка", exc_info=(kind, value, traceback))
        original_hook(kind, value, traceback)

    sys.excepthook = exception_hook


def recent_log() -> str:
    try:
        # Read only a bounded tail, even if an older version left a large file.
        with LOG_FILE.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 24000))
            return redact("\n".join(stream.read().decode("utf-8", errors="replace").splitlines()[-80:]))
    except OSError:
        return log_error or "Журнал пока пуст."
