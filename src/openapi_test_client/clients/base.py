from __future__ import annotations

import importlib
import inspect
import json
from typing import Any, TypeVar

from common_libs.clients.rest_client import RestClient
from common_libs.logging import get_logger

from openapi_test_client import DEFAULT_ENV, get_config_dir
from openapi_test_client.libraries.api.api_spec import OpenAPISpec
from openapi_test_client.libraries.common.misc import get_module_name_by_file_path

logger = get_logger(__name__)

T = TypeVar("T", bound="OpenAPIClient")


class OpenAPIClient:
    """Base class for all clients"""

    def __init__(self, app_name: str, doc: str, env: str = DEFAULT_ENV, rest_client: RestClient = None):
        if app_name.lower() in ["open", "base"]:
            raise ValueError(f"app_name '{app_name}' is reserved for internal usage. Please use a different value")

        self.app_name = app_name
        self.env = env

        if rest_client:
            self.rest_client = rest_client
            self._base_url = rest_client.url_base
        else:
            url_cfg = get_config_dir() / "urls.json"
            urls = json.loads(url_cfg.read_text())
            try:
                self._base_url = urls[self.env][self.app_name]
            except KeyError:
                raise NotImplementedError(
                    f"Please add base URL for app '{self.app_name}' (env={self.env}) in {url_cfg}"
                )
            self.rest_client = RestClient(self.base_url)

        self.api_spec = OpenAPISpec(self, doc)

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, url: str) -> None:
        self._base_url = url

    @classmethod
    def get_client(cls: type[T], app_name: str, **init_options: Any) -> T:
        """Get API client for the app

        :param app_name: App name
        :param init_options: Options passed to the client initialization
        """
        from openapi_test_client.libraries.api.api_client_generator import get_client_dir

        client_file = get_client_dir(app_name) / f"{app_name}_client.py"
        if not client_file.exists():
            raise RuntimeError(f"API client for {app_name} ({client_file}) does not exist")

        client_module_name = get_module_name_by_file_path(client_file)
        mod = importlib.import_module(client_module_name)
        client_classes: list[type[T]] = [
            x
            for x in mod.__dict__.values()
            if inspect.isclass(x) and issubclass(x, OpenAPIClient) and x is not OpenAPIClient
        ]
        if len(client_classes) != 1:
            raise RuntimeError(f"Unable to locate the API client for {app_name} from {mod}")

        APIClientClass = client_classes[0]
        return APIClientClass(**init_options)
