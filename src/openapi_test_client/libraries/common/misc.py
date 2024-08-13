import importlib.util
import inspect
import keyword
import os
import re
from collections.abc import Collection, Mapping
from functools import wraps
from importlib.abc import InspectLoader
from pathlib import Path
from types import ModuleType
from typing import Any


def clean_obj_name(name: str) -> str:
    """Convert the name to a legal Python object name

    - Illegal values will be converted to "_" (multiple illegal values in a row will be converted to single "_")
    - If the name starts with a number, "_" will be added at the beginning

    :param name: The original value
    """
    pattern_illegal_chars = r"\W+|^(?=\d)"
    has_illegal_chars = re.search(pattern_illegal_chars, name)
    is_reserved_name = keyword.iskeyword(name)
    if has_illegal_chars:
        name = re.sub(pattern_illegal_chars, "_", name)
    elif is_reserved_name:
        name = f"_{name}"

    return name


def camel_to_snake(camel_case_str: str) -> str:
    """Convert camel format to snake format

    :param camel_case_str: Camel case string value
    """
    snake_str = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", camel_case_str)
    return snake_str.lower()


def generate_class_name(base_name: str, suffix: str = None) -> str:
    """Generate a class name from the given value

    eg. A class name "MyClass" will be generated from "my class"

    :param base_name: A value to be used as part of the class name
    :param suffix: Suffix to add to the class name
    """
    class_name = f'{camel_to_snake(base_name).title().replace("_", "")}'
    if suffix:
        class_name += suffix
    return re.sub(r"[^a-zA-Z0-9]+", "", class_name)


def get_module_name_by_file_path(file_path: Path) -> str:
    """Get the module name for the given file

    :param file_path: A file path to resolve as a module name
    """
    from openapi_test_client import _PACKAGE_DIR, get_package_dir, is_external_project

    package_dir = get_package_dir()
    if file_path.is_relative_to(package_dir):
        file_path_from_package_dir = str(file_path.relative_to(package_dir.parent))
    else:
        assert is_external_project()
        # Accessing the package file from an external location
        file_path_from_package_dir = _PACKAGE_DIR.name + str(file_path).rsplit(_PACKAGE_DIR.name)[-1]
    return file_path_from_package_dir.replace(os.sep, ".").replace(".py", "")


def import_module_from_file_path(file_path: Path) -> ModuleType:
    """Import module from the given file path

    :param file_path: A file path to import as a module
    """
    module_name = get_module_name_by_file_path(file_path)
    module = importlib.import_module(module_name)
    return module


def import_module_with_new_code(new_code: str, path_or_obj: Path | Any) -> ModuleType:
    """Import module from updated code

    :param new_code: New code of the module
    :param path_or_obj: A module file path or an object in the target module
    """
    if isinstance(path_or_obj, Path):
        path = path_or_obj
    else:
        path = Path(inspect.getabsfile(path_or_obj))
    code = InspectLoader.source_to_code(new_code, path)
    mod = import_module_from_file_path(path)
    exec(code, mod.__dict__)
    return mod
