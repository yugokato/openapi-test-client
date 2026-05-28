from __future__ import annotations

import importlib
import inspect
import json
from typing import Any, TypeVar

from common_libs.clients.rest_client import AsyncRestClient, RestClient

from openapi_test_client import DEFAULT_ENV, get_client_dir, get_config_dir
from openapi_test_client.libraries.core.base.api_client import APIClient
from openapi_test_client.libraries.openapi.api_spec import OpenAPISpec
from openapi_test_client.libraries.openapi.utils.modules import get_module_name_by_file_path

T = TypeVar("T", bound="APIClient")


class OpenAPIClient(APIClient):
    """OpenAPI-backed API test client. All OpenAPI-generated clients must inherit from this class"""

    def __init__(
        self,
        app_name: str,
        /,
        *,
        doc: str,
        env: str | None = None,
        base_url: str | None = None,
        rest_client: RestClient | AsyncRestClient | None = None,
        async_mode: bool = False,
        **kwargs: Any,
    ):
        """Initialize the OpenAPI client

        :param app_name: App name
        :param doc: Path or URL to the OpenAPI spec document
        :param env: Target environment
        :param base_url: Base URL for the API
        :param rest_client: Pre-configured REST client (mutually exclusive with base_url)
        :param async_mode: Enable async mode
        :param kwargs: Additional keyword arguments passed to the REST client constructor
        """
        if app_name.lower() in ["open", "base"]:
            raise ValueError(f"app_name '{app_name}' is reserved for internal usage. Please use a different value")

        if env is None:
            env = DEFAULT_ENV

        if base_url is None and rest_client is None:
            url_cfg = get_config_dir() / "urls.json"
            urls = json.loads(url_cfg.read_text())
            try:
                base_url = urls[env][app_name]
            except KeyError:
                raise NotImplementedError(
                    f"Please specify base_url or add one for app '{app_name}' (env={env}) in {url_cfg}"
                )

        super().__init__(
            app_name,
            env=env,
            base_url=base_url,
            rest_client=rest_client,
            async_mode=async_mode,
            **kwargs,
        )
        self.api_spec = OpenAPISpec(self, doc)

    @classmethod
    def get_client(cls: type[T], app_name: str, **init_options: Any) -> T:
        """Get API client for the app

        :param app_name: App name
        :param init_options: Options passed to the client initialization
        """
        client_file = get_client_dir(app_name) / f"{app_name}_client.py"
        if not client_file.exists():
            raise RuntimeError(f"API client for {app_name} ({client_file}) does not exist")

        client_module_name = get_module_name_by_file_path(client_file)
        mod = importlib.import_module(client_module_name)
        client_classes: list[type[T]] = [
            x
            for x in mod.__dict__.values()
            if inspect.isclass(x) and issubclass(x, cls) and x.__module__ == mod.__name__
        ]
        if len(client_classes) != 1:
            raise RuntimeError(f"Unable to locate the API client for {app_name} from {mod}")

        APIClientClass = client_classes[0]
        return APIClientClass(**init_options)  # type: ignore[call-arg]
