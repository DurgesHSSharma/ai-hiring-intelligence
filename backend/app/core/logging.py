"""Structured logging setup. No module in this codebase uses print()."""
import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Install one stdout handler on the root logger (idempotent) and set its level.

    Safe to call more than once: the handler is attached only the first time,
    later calls just adjust the level once the real APP_ENV is known.
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        root.addHandler(handler)
    root.setLevel(level)
