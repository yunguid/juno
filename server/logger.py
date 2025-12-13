"""Logging configuration for Juno"""
import logging
import sys

# ANSI colors
COLORS = {
    'DEBUG': '\033[36m',     # Cyan
    'INFO': '\033[32m',      # Green
    'WARNING': '\033[33m',   # Yellow
    'ERROR': '\033[31m',     # Red
    'RESET': '\033[0m',
    'BOLD': '\033[1m',
    'DIM': '\033[2m',
}


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        color = COLORS.get(record.levelname, COLORS['RESET'])
        reset = COLORS['RESET']
        dim = COLORS['DIM']

        # Format: [TIME] LEVEL | logger | message
        time_str = self.formatTime(record, "%H:%M:%S")

        return (
            f"{dim}[{time_str}]{reset} "
            f"{color}{record.levelname:7}{reset} "
            f"{dim}|{reset} {record.name:12} {dim}|{reset} "
            f"{record.getMessage()}"
        )


def setup_logging(level: str = "INFO"):
    """Set up colored logging for the application"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())

    # Root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.handlers = [handler]

    # Quiet down noisy libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module"""
    return logging.getLogger(name)
