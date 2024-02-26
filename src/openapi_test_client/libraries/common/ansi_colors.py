import re
from typing import Any

PATTERN_COLOR_CODE = r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"


class ColorCodes:
    DEFAULT = "\x1b[0m"
    DEFAULT2 = "\x1b[m"
    BLACK = "\x1b[30m"
    WHITE = "\x1b[97m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    MAGENTA = "\x1b[35m"
    CYAN = "\x1b[36m"
    DARK_GREY = "\x1b[90m"
    LIGHT_RED = "\x1b[91m"
    LIGHT_GREEN = "\x1b[92m"
    LIGHT_YELLOW = "\x1b[93m"
    LIGHT_BLUE = "\x1b[94m"
    LIGHT_MAGENTA = "\x1b[95m"
    LIGHT_CYAN = "\x1b[96m"

    # text styles
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def color(
    string: Any,
    color_code: str = ColorCodes.GREEN,
    bold: bool = False,
    underline: bool = False,
    escape: bool = False,
):
    """Add ANSI color code to string

    :param string: Original string to color
    :param color_code: ANSI color code
    :param bold: Bold string
    :param underline: Underline string
    :param escape: Escape each ansi color code (need for terminal prompt)
    """
    if not isinstance(string, str):
        string = str(string)

    colored_str = string
    if bold:
        colored_str = ColorCodes.BOLD + colored_str
    if underline:
        colored_str = ColorCodes.UNDERLINE + colored_str
    if color_code:
        colored_str = color_code + colored_str
    if bold or color_code:
        colored_str += ColorCodes.DEFAULT
    if escape:
        colored_str = escape_color_code(colored_str)
    return colored_str


def remove_color_code(string: str) -> str:
    """Remove ANSI color code"""
    return re.sub(PATTERN_COLOR_CODE, "", string)


def escape_color_code(string: str) -> str:
    """Escape each ANSI color code with "\x01" and "\x02".

    This is needed for the terminal history with arrow keys to work properly
    https://github.com/python/cpython/issues/64558
    """
    return re.sub(f"({PATTERN_COLOR_CODE})", "\x01" + r"\1" + "\x02", string)
