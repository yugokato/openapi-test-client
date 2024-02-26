import logging
import time
from logging import Logger, LogRecord, config
from pathlib import Path
from typing import Optional

import yaml

from openapi_test_client.libraries.common.ansi_colors import ColorCodes, color


def setup_logging(config_path: str | Path) -> None:
    """Setup logging

    :param config_path: File path to a logging config
    """
    with open(config_path) as f:
        log_cfg = yaml.safe_load(f)
    config.dictConfig(log_cfg)


def get_logger(name: str) -> Logger:
    """Return a logger for the specified name

    :param name: Logger name
    """
    pkg_name = __name__.split(".")[0]
    if not name.startswith(pkg_name):
        name = f"{pkg_name}.{name}"
    return logging.getLogger(name)


class ColoredStreamHandler(logging.StreamHandler):
    """Colored StreamHandler"""

    @classmethod
    def _get_color_code(cls, level: int) -> Optional[str]:
        if level >= logging.CRITICAL:
            return ColorCodes.RED
        elif level >= logging.ERROR:
            return ColorCodes.RED
        elif level >= logging.WARNING:
            return ColorCodes.YELLOW
        elif level >= logging.INFO:
            return None
        elif level >= logging.DEBUG:
            return ColorCodes.DARK_GREY
        else:
            return ColorCodes.DEFAULT

    def __init__(self, stream=None):
        logging.StreamHandler.__init__(self, stream)

    def format(self, record: LogRecord):
        """Add ANSI color code to record based on the level number"""
        color_code = self._get_color_code(record.levelno)
        msg = super().format(record)
        return color(msg, color_code=color_code)


class LogFormatter(logging.Formatter):
    def formatTime(self, record: LogRecord, datefmt: str = None):
        """Overrides the default behavior to support both %f and %z in datefmt

        eg. datefmt="%Y-%m-%dT%H:%M:%S.%f%z" will display the timestamp as 2022-01-01T11:22:33.444-0000
        """
        if datefmt:
            ct = self.converter(record.created)
            datefmt = datefmt.replace("%f", "%03d" % int(record.msecs))
            datefmt = datefmt.replace("%z", time.strftime("%z"))
            return time.strftime(datefmt, ct)
        else:
            return super().formatTime(record)
