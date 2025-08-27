import os
import sys
import logging
import contextvars
import colorama
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from app.config.app_config import settings

# Prefixes to hide/mute entirely
IGNORED_LOGGER_PREFIXES = ("litellm", "LiteLLM")

# ContextVar to hold the current request’s ID
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    """
    Injects request_id from our ContextVar into every LogRecord.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def console_filter(record: logging.LogRecord) -> bool:
    """
    Hide records from specified logger name prefixes.
    """
    return not record.name.startswith(IGNORED_LOGGER_PREFIXES)


class ColorizingFormatter(logging.Formatter):
    """
    Applies ANSI colors to the levelname.
    """
    LEVEL_COLORS = {
        'DEBUG':    colorama.Fore.CYAN,
        'INFO':     colorama.Fore.GREEN,
        'WARNING':  colorama.Fore.YELLOW,
        'ERROR':    colorama.Fore.RED,
        'CRITICAL': colorama.Style.BRIGHT + colorama.Fore.RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        orig = record.levelname
        color = self.LEVEL_COLORS.get(orig, "")
        reset = colorama.Style.RESET_ALL
        # inject colored levelname
        record.levelname = f"{color}{orig}{reset}"
        formatted = super().format(record)
        record.levelname = orig  # restore for any other handlers
        return formatted


def setup_logging() -> None:
    """
    Configure stdlib logging once (idempotent). Reads LOG_LEVEL from settings.
    Installs:
      - console handler (stdout) with colors + request_id + prefix filter
      - daily-rotating file handler (2d retention) with request_id
      - clears handlers on uvicorn/fastapi so they propagate to root
      - mutes any logger whose name starts with IGNORED_LOGGER_PREFIXES
    """
    if os.environ.get("SETUP_LOGGING_COMPLETE"):
        return
    os.environ["SETUP_LOGGING_COMPLETE"] = "True"

    # initialize ANSI support (Windows, etc)
    colorama.init()

    # determine level
    lvl = settings.LOG_LEVEL.upper()
    if lvl not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        lvl = "INFO"

    # prepare log file path
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"app_{ts}.log")

    # common formatter settings
    fmt = (
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
        "[%(request_id)s] %(name)s:%(lineno)d - %(message)s"
    )
    datefmt = "%Y-%m-%d %H:%M:%S"

    # filters
    req_filter = RequestIdFilter()

    # 1) Console handler (with color)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(lvl)
    ch.setFormatter(ColorizingFormatter(fmt=fmt, datefmt=datefmt))
    ch.addFilter(console_filter)
    ch.addFilter(req_filter)

    # 2) File handler (rotate at midnight, retain 2 days)
    fh = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        backupCount=2,
        encoding="utf-8",
    )
    fh.setLevel(lvl)
    fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    fh.addFilter(req_filter)

    # 3) Root logger
    root = logging.getLogger()
    root.setLevel(lvl)
    root.handlers.clear()
    root.addHandler(ch)
    root.addHandler(fh)

    # 4) Let uvicorn/fastapi propagate to root (no local handlers)
    for pkg in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(pkg)
        lg.handlers.clear()
        lg.propagate = True
        lg.setLevel(lvl)

    # 5) Mute any logger whose name starts with our ignored prefixes
    manager = logging.root.manager
    for prefix in IGNORED_LOGGER_PREFIXES:
        # base logger
        base = logging.getLogger(prefix)
        base.setLevel(logging.WARNING)
        base.propagate = False
        base.handlers.clear()

        # child loggers
        for name, logger_obj in manager.loggerDict.items():
            if name.startswith(prefix) and isinstance(logger_obj, logging.Logger):
                logger_obj.setLevel(logging.WARNING)
                logger_obj.propagate = False
                logger_obj.handlers.clear()