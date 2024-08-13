import glob
import os
import sys
from pathlib import Path

from common_libs.logging import get_logger, setup_logging
from common_libs.utils import list_items

# For internal use only
_PROJECT_ROOT_DIR = Path(__file__).parent.parent.parent.resolve()
_PACKAGE_DIR = Path(__file__).parent.resolve()
_CONFIG_DIR = _PACKAGE_DIR / "cfg"


ENV_VAR_PACKAGE_DIR = "API_CLIENT_PACKAGE_DIR"
DEFAULT_ENV = os.environ.get("DEFAULT_ENV", "dev")


def is_external_project() -> bool:
    """Check if this library is current used from an external location"""
    return bool(os.environ.get(ENV_VAR_PACKAGE_DIR, "") or not Path.cwd().is_relative_to(_PROJECT_ROOT_DIR))


def find_external_package_dir(current_dir: Path = None, missing_ok: bool = False) -> Path:
    """Find an external package directory

    An external directory should have .api_test_client hidden file
    """
    filename = f".{_PACKAGE_DIR.name}"
    if not current_dir:
        current_dir = Path.cwd().resolve()

    if current_dir == Path(os.sep):
        # The package directory search from the root directory won't complete within a reasonable time.
        # We don't support this scenario
        raise NotImplementedError(
            f"Accessing the {__package__} library from the root directory ({os.sep}) is not supported. "
            f"Please create a project directory and start from there"
        )

    def search_parent_dirs(dir: Path):
        if (dir / filename).exists():
            return dir

        parent = dir.parent
        if parent == dir:
            return

        return search_parent_dirs(parent)

    def search_child_dirs(dir: Path):
        if hidden_files := glob.glob(f"**/{filename}", root_dir=dir, recursive=True):
            module_paths = [(dir / x).parent for x in hidden_files]
            if len(module_paths) > 1:
                raise RuntimeError(f"Detected multiple installation under {dir}:\n{list_items(module_paths)}")
            return module_paths[0]

    if package_dir := (search_parent_dirs(current_dir) or search_child_dirs(current_dir)):
        if str(package_dir) not in sys.path:
            # external modules need to be accessible for updating clients
            sys.path.insert(0, str(package_dir.parent))
        return package_dir
    else:
        if not missing_ok:
            raise FileNotFoundError


def get_package_dir() -> Path:
    """Return the API client package directory"""
    if is_external_project():
        if api_client_package_dir := os.environ.get(ENV_VAR_PACKAGE_DIR, ""):
            sys.path.append(str(Path(api_client_package_dir).parent))
            return Path(api_client_package_dir).resolve()
        else:
            try:
                return find_external_package_dir()
            except FileNotFoundError:
                # Initial script run from an external location. The directory hasn't been setup yet
                return _PACKAGE_DIR

    else:
        return _PACKAGE_DIR


def get_config_dir() -> Path:
    """Return the current config directory"""
    if is_external_project():
        return get_package_dir() / _CONFIG_DIR.name
    else:
        return _CONFIG_DIR


setup_logging(get_config_dir() / "logging.yaml")
logger = get_logger(__name__)
