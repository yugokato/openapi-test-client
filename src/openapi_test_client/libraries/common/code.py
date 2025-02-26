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


def parse_code(code: str):
    """Parse code and check syntax errors"""
    try:
        ast.parse(code)
    except Exception:
        logger.error(f"Failed to parse code:\n{code}")
        raise


def diff_code(code1: str, code2: str, fromfile: str = "before", tofile: str = "after"):
    """Diff code"""
    for line in difflib.unified_diff(code1.split("\n"), code2.split("\n"), fromfile=fromfile, tofile=tofile):
        if line.startswith("+"):
            color_code = ColorCodes.GREEN
        elif line.startswith("-"):
            color_code = ColorCodes.RED
        else:
            color_code = ColorCodes.DEFAULT
        print(TAB + color(line.rstrip(), color_code=color_code))


def run_ruff(code: str, remove_unused_imports: bool = True) -> str:
    """Run ruff check and ruff format"""
    # TODO: Switch to use ruff public APIs once supported (https://github.com/astral-sh/ruff/issues/659)
    return _run_ruff_format(_run_ruff_check(code, remove_unused_imports=remove_unused_imports))


def _run_ruff_check(code: str, remove_unused_imports: bool = True) -> str:
    selects = ["--select=I"]
    if remove_unused_imports:
        selects.append("--select=F401")
    proc = subprocess.run(
        ["ruff", "check", *selects, "--fix", "-"],
        input=code,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"Unexpected error occurred during ruff check\n{proc.stderr}")
    assert proc.stdout
    return proc.stdout


def _run_ruff_format(code: str) -> str:
    return subprocess.check_output(["ruff", "format", "-"], input=code, encoding="utf-8")
