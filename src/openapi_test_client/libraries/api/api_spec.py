import copy
import json
import re
from functools import lru_cache, reduce
from typing import TYPE_CHECKING, Any, Optional

import requests
import yaml

from openapi_test_client.libraries.common.constants import VALID_METHODS
from openapi_test_client.libraries.common.logging import get_logger

if TYPE_CHECKING:
    from openapi_test_client.clients import APIClientType
    from openapi_test_client.libraries.api import Endpoint


logger = get_logger(__name__)


class OpenAPISpec:
    """Class to handle OpenAPI specs"""

    def __init__(self, api_client: "APIClientType", doc_path: str):
        self.api_client = api_client
        self.doc_path = doc_path
        self._spec = None

    @lru_cache
    def get_api_spec(self, url: str = None) -> Optional[dict[str, Any]]:
        """Return OpenAPI spec"""
        if self._spec is None:
            if url:
                doc_path = url.rsplit("/", 1)
            else:
                url = f"{self.api_client.base_url}/{self.doc_path}"
                doc_path = self.doc_path

            if not doc_path.endswith((".json", ".yaml", ".yml")):
                raise ValueError(f"OpenAPI spec file must be JSON or YAML. Not '{doc_path}'")

            try:
                r = requests.get(url)
                r.raise_for_status()
                if doc_path.endswith((".yaml", ".yml")):
                    api_spec = yaml.safe_load(r.content.decode("utf-8"))
                else:
                    api_spec = r.json()

                if "openapi" not in api_spec.keys():
                    raise NotImplementedError(
                        f"Invalid OpenAPI spec: 'openapi' field doesn't exist in the root object: "
                        f"{list(api_spec.keys())}"
                    )
                elif not (open_api_version := api_spec["openapi"]).startswith("3."):
                    raise NotImplementedError(f"Unsupported OpenAPI version: {open_api_version}")
            except Exception as e:
                logger.error(f"Unable to get API specs from {url}\n{type(e).__name__}: {e}")
            else:
                adjusted_spec = copy.deepcopy(api_spec)
                if self._has_reference(adjusted_spec):
                    adjusted_spec = self._resolve_schemas(adjusted_spec)
                adjusted_spec = self._adjust_spec(adjusted_spec)
                endpoint_tags = self._collect_endpoint_tags(adjusted_spec)
                if tags := adjusted_spec.get("tags"):
                    if undefined_endpoint_tags := set(endpoint_tags).difference(set([t["name"] for t in tags])):
                        logger.warning(
                            f'One ore more endpoint tags are not defined at the top-level "tags": '
                            f"{undefined_endpoint_tags}"
                        )
                else:
                    # We need the top-level "tags" but it is either not defined or empty.
                    # Collect all tags defined at the endpoint level and use them. If no tags are defined,
                    # "default" tag will be added
                    adjusted_spec["tags"] = [{"name": t} for t in endpoint_tags]
                    assert adjusted_spec["tags"]
                self._spec = adjusted_spec
                return self._spec
        else:
            logger.warning("API spec is not available")

    def get_endpoint_usage(self, endpoint: "Endpoint") -> Optional[str]:
        """Return usage of the endpoint

        :param endpoint: Endpoint object
        """
        if self.get_api_spec():
            method = endpoint.method
            path = endpoint.path
            try:
                ep_doc = self._spec["paths"][path][method]
            except KeyError:
                err = f"{method.upper()} {path} does not exist in the OpenAPI spec"
                raise ValueError(err)
            summary = ep_doc.get("summary")
            parameters = ep_doc.get("parameters")
            request_body = ep_doc.get("requestBody")
            usage = f"- Method: {method.upper()}\n" f"- Path: {path}\n- Summary: {summary}\n"
            if parameters:
                usage += f"- Parameters: {json.dumps(parameters, indent=4)}\n"
            if request_body:
                usage += f"- Request Body: {json.dumps(request_body, indent=4)}\n"
            return usage

    def _has_reference(self, api_spec: dict[str, Any]) -> bool:
        return "'$ref':" in str(api_spec)

    def _resolve_schemas(self, api_spec: dict[str, Any]) -> dict[str, Any]:
        """Resolve '$ref' and overwrite the spec data"""
        ref_pattern = re.compile(r"#?/([^/]+)")

        def resolve_recursive(reference, schemas_seen: list[str] = None):
            if not schemas_seen:
                schemas_seen = []
            if isinstance(reference, dict):
                for k, v in copy.deepcopy(reference).items():
                    new_reference = reference[k]
                    if k == "$ref":
                        ref_keys = re.findall(ref_pattern, new_reference)
                        assert ref_keys
                        schema = "/".join(ref_keys)
                        if schema in schemas_seen:
                            logger.warning(
                                f"WARNING: Detected recursive schema definition. This is not supported: {schema}"
                            )
                        else:
                            schemas_seen.append(schema)
                        try:
                            resolved_value = reduce(lambda d, k: d[k], ref_keys, api_spec)
                            del reference[k]
                        except KeyError as e:
                            logger.warning(f"SKIPPED: Unable to resolve '$ref' for '{new_reference}' (KeyError: {e})")
                        else:
                            if self._has_reference(resolved_value):
                                resolved_value = resolve_recursive(resolved_value, schemas_seen=schemas_seen)
                            if isinstance(resolved_value, dict):
                                reference.update(resolved_value)
                            else:
                                reference = resolved_value
                    else:
                        resolve_recursive(new_reference, schemas_seen=schemas_seen)
            elif isinstance(reference, list):
                for item in reference:
                    resolve_recursive(item, schemas_seen=schemas_seen)
            return reference

        paths = api_spec["paths"]
        for path in paths:
            resolve_recursive(paths[path])
        return api_spec

    def _adjust_spec(self, api_spec: dict[str, Any]) -> dict[str, Any]:
        """Adjust the shape of the API specs for our library to work better"""

        def adjust_path_params(path_obj: dict[str, Any]):
            """Move the path level "parameters" obj to under each path method level"""
            if "parameters" in path_obj:
                for key in path_obj:
                    if key in VALID_METHODS:
                        current_path_parameters = path_obj[key].get("parameters", [])
                        new_path_parameters = path_obj["parameters"] + current_path_parameters
                        path_obj[key]["parameters"] = new_path_parameters
                del path_obj["parameters"]

        def adjust_recursive(
            reference: Any, is_property: bool = None, required_params: tuple[str] = ()
        ) -> dict[str, Any]:
            """Adjust specs

            - Remove additionalProperties under `properties` obj (We don't support it)
            - Set `required` boolean flag to under each obj property for parameters defined as required at schema-level
            """
            if isinstance(reference, dict):
                for k, v in copy.deepcopy(reference).items():
                    new_reference = reference[k]
                    if k == "additionalProperties":
                        if (
                            isinstance(v, dict)
                            and all(k_ in v.keys() for k_ in ["properties", "type"])
                            and v["type"] == "object"
                        ):
                            reference.update(v)
                            del reference["additionalProperties"]
                    elif isinstance(new_reference, dict):
                        if is_property is None and "properties" in new_reference:
                            is_property = True

                        if (required := new_reference.get("required")) and isinstance(required, list):
                            # Track the required param list for parsing inner objects
                            required_params = tuple(required)
                        elif all(
                            [
                                required_params,
                                is_property,
                                k in required_params,
                                "type" in new_reference,
                                "required" not in new_reference,
                            ]
                        ):
                            new_reference["required"] = True
                    adjust_recursive(new_reference, is_property=is_property, required_params=required_params)
            elif isinstance(reference, list):
                for item in reference:
                    adjust_recursive(item)
            return reference

        paths = api_spec["paths"]
        for _, path_obj in paths.items():
            adjust_path_params(path_obj)
            try:
                adjust_recursive(path_obj)
            except RecursionError:
                logger.warning(f"SKIPPED: Unable to process the path object with recursive object(s):\n{path_obj}")
            except Exception as e:
                logger.warning(
                    f"SKIPPED: Encountered an error while processing the path object:\n"
                    f"{path_obj}\n({type(e).__name__}: {e})"
                )
                logger.exception(e)
        return api_spec

    def _adjust_path_parameters(self, api_spec: dict[str, Any]):
        """Move the path level "parameters" obj to under each path method level so that our library works better"""
        paths = api_spec["paths"]
        for path in paths:
            path_obj = paths[path]
            if "parameters" in path_obj:
                for key in path_obj:
                    if key in VALID_METHODS:
                        current_path_parameters = path_obj[key].get("parameters", [])
                        new_path_parameters = path_obj["parameters"] + current_path_parameters
                        path_obj[key]["parameters"] = new_path_parameters
                del path_obj["parameters"]
        return api_spec

    def _collect_endpoint_tags(self, resolved_api_spec: dict[str, Any]) -> list[str]:
        tags = []

        def collect(obj):
            if isinstance(obj, dict):
                if "tags" in obj:
                    tags.extend(obj["tags"])
                else:
                    for k, v in obj.items():
                        collect(obj[k])

        collect(resolved_api_spec["paths"])
        if not tags:
            tags.append("default")
        return list(set(tags))
