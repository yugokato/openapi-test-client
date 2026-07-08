import ast
import difflib
import subprocess

from common_libs.ansi_colors import ColorCodes, color
from common_libs.logging import get_logger

logger = get_logger(__name__)
TAB = " " * 4


def format_code(code: str, remove_unused_imports: bool = True) -> str:
    """Format code string

    The following will be performed
    - Check syntax error
    - Run ruff (as alternative to autoflake, isort, and black)
    """
    parse_code(code)
    return run_ruff(code, remove_unused_imports=remove_unused_imports)


def parse_code(code: str) -> None:
    """Parse code and check syntax errors"""
    try:
        ast.parse(code)
    except Exception:
        logger.error(f"Failed to parse code:\n{code}")
        raise


def diff_code(code1: str, code2: str, fromfile: str = "before", tofile: str = "after") -> None:
    """Diff code"""
    for line in difflib.unified_diff(code1.split("\n"), code2.split("\n"), fromfile=fromfile, tofile=tofile):
        if line.startswith("+"):
            color_code = ColorCodes.GREEN
        elif line.startswith("-"):
            color_code = ColorCodes.RED
        else:
            color_code = ColorCodes.DEFAULT
        print(TAB + color(line.rstrip(), color_code=color_code))  # noqa: T201
    print()  # noqa: T201


def run_ruff(code: str, remove_unused_imports: bool = True) -> str:
    """Run 'ruff check' and 'ruff format' commands as a pipeline

    # TODO: Switch to use ruff public APIs once supported (https://github.com/astral-sh/ruff/issues/659)
    """
    select_rules = ["I"]
    if remove_unused_imports:
        select_rules.append("F401")

    ruff_check = subprocess.Popen(
        ["ruff", "check", f"--select={','.join(select_rules)}", "--fix", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    ruff_format = subprocess.Popen(
        ["ruff", "format", "-"],
        stdin=ruff_check.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )

    # Close parent's copy so ruff_format sees EOF correctly (and can SIGPIPE if it exits)
    ruff_check.stdout.close()

    # Use communicate to avoid deadlocks
    _, check_stderr = ruff_check.communicate(input=code)
    formatted_code, format_stderr = ruff_format.communicate()

    if ruff_check.returncode:
        raise RuntimeError(f"ruff check failed:\n{check_stderr}")
    if ruff_format.returncode:
        raise RuntimeError(f"ruff format failed:\n{format_stderr}")

    assert formatted_code
    return formatted_code
