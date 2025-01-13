import ast
import difflib

import autoflake
import black
import isort
from common_libs.ansi_colors import ColorCodes, color
from common_libs.logging import get_logger

from openapi_test_client import _PROJECT_ROOT_DIR

logger = get_logger(__name__)
TAB = " " * 4


def format_code(code: str, remove_unused_imports: bool = True) -> str:
    """Format code string

    The following will be performed
    - Check syntax error
    - Run autoflake
    - Run isort
    - Run black
    """
    try:
        ast.parse(code)
    except Exception:
        logger.error(f"Failed to parse code:\n{code}")
        raise

    # Apply autoflake
    code = autoflake.fix_code(code, remove_all_unused_imports=remove_unused_imports)

    # Apply isort
    code = isort.api.sort_code_string(code, settings_path=_PROJECT_ROOT_DIR)

    # Apply black
    code = run_black(code)
    return code


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


def run_black(code: str) -> str:
    class _BlackCtx:
        def __init__(self, src):
            self.default_map = {}
            self.params = {"src": src}
            self.command = black.main

    ctx = _BlackCtx((_PROJECT_ROOT_DIR,))
    black.read_pyproject_toml(ctx, None, None)
    versions = ctx.default_map.get("target_version", set())
    mode = black.Mode(
        target_versions=set(black.TargetVersion[v.upper()] for v in versions),
        line_length=int(ctx.default_map.get("line_length", black.DEFAULT_LINE_LENGTH)),
        is_pyi=ctx.default_map.get("pyi", False),
        string_normalization=not ctx.default_map.get("skip_string_normalization", False),
    )
    try:
        code = black.format_file_contents(code, fast=True, mode=mode)
    except black.NothingChanged:
        pass

    return code
