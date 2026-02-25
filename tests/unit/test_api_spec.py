"""Unit tests for OpenAPISpec in api_spec.py"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_mock import MockerFixture

from openapi_test_client.clients.base import OpenAPIClient
from openapi_test_client.libraries.api.api_spec import OpenAPISpec

pytestmark = [pytest.mark.unittest]

# A minimal valid OpenAPI 3.x spec for testing
VALID_SPEC_JSON: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Test API", "version": "0.1.0"},
    "tags": [{"name": "Test"}],
    "paths": {
        "/v1/foo": {
            "get": {
                "tags": ["Test"],
                "summary": "Get foo",
                "parameters": [{"name": "id", "in": "query", "schema": {"type": "string"}}],
                "responses": {},
            }
        }
    },
}

VALID_SPEC_YAML = """\
openapi: "3.1.0"
info:
  title: Test API
  version: "0.1.0"
tags:
  - name: Test
paths:
  /v1/foo:
    get:
      tags:
        - Test
      summary: Get foo
      responses: {}
"""

# Spec used in get_endpoint_usage tests
USAGE_SPEC: dict[str, Any] = {
    "openapi": "3.1.0",
    "tags": [{"name": "Test"}],
    "paths": {
        "/v1/items": {
            "post": {
                "tags": ["Test"],
                "summary": "Create item",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                            }
                        }
                    }
                },
                "responses": {},
            }
        },
        "/v1/items/{item_id}": {
            "get": {
                "tags": ["Test"],
                "summary": "Get item",
                "parameters": [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {},
            }
        },
    },
}


class TestGetApiSpec:
    """Tests for OpenAPISpec.get_api_spec()"""

    @pytest.fixture
    def mock_httpx(self, mocker: MockerFixture) -> Callable[..., MagicMock]:
        mock_httpx_get = mocker.patch("httpx.get")

        def _make_mock_response(
            doc_path: str,
            spec_dict: dict[str, Any] | None = None,
            spec_text: str | None = None,
            json_error: bool = False,
            http_error: Exception | None = None,
        ) -> MagicMock:
            """Create a mock httpx response."""
            mock_resp = mocker.MagicMock()
            mock_resp.url = f"https://example.com/{doc_path}"
            if http_error:
                mock_resp.raise_for_status.side_effect = http_error
            else:
                mock_resp.raise_for_status.return_value = None
            if json_error:
                mock_resp.json.side_effect = json.JSONDecodeError("not json", "", 0)
            elif spec_dict is not None:
                mock_resp.json.return_value = spec_dict
            mock_resp.text = spec_text or ""
            mock_httpx_get.return_value = mock_resp
            return mock_httpx_get

        return _make_mock_response

    @pytest.fixture
    def openapi_spec_factory(self) -> Callable[..., OpenAPISpec]:
        """Create a fresh OpenAPISpec instance (fresh lru_cache) with a stub api_client."""

        def create_spec(ext: str | None = ".json") -> OpenAPISpec:
            doc_path = f"openapi{ext}"
            api_client = OpenAPIClient("test", doc_path, base_url="https://example.com/api")
            return OpenAPISpec(api_client, doc_path)

        return create_spec

    def test_get_api_spec_json(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """Fetching a .json doc_path parses the response as JSON."""
        spec = openapi_spec_factory(".json")
        mock_get = mock_httpx(spec.doc_path, spec_dict=copy.deepcopy(VALID_SPEC_JSON))
        result = spec.get_api_spec()
        mock_get.assert_called_once()
        assert result is not None
        assert "openapi" in result
        assert "paths" in result

    @pytest.mark.parametrize("ext", [".yaml", ".yml"])
    def test_get_api_spec_yaml(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec], ext: str
    ) -> None:
        """Fetching a .yaml/.yml doc_path parses the response as YAML."""
        spec = openapi_spec_factory(ext)
        mock_get = mock_httpx(spec.doc_path, spec_text=VALID_SPEC_YAML)
        result = spec.get_api_spec()
        mock_get.assert_called_once()
        assert result is not None
        assert result["openapi"] == "3.1.0"

    def test_get_api_spec_no_extension_json(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """A doc_path with no extension auto-detects JSON when response is valid JSON."""
        spec = openapi_spec_factory(None)
        mock_get = mock_httpx(spec.doc_path, spec_dict=copy.deepcopy(VALID_SPEC_JSON))
        result = spec.get_api_spec()
        mock_get.assert_called_once()
        assert result is not None
        assert result["openapi"] == "3.1.0"

    def test_get_api_spec_no_extension_yaml(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """A doc_path with no extension falls back to YAML when JSON parse fails."""
        spec = openapi_spec_factory(None)
        mock_get = mock_httpx(spec.doc_path, spec_text=copy.deepcopy(VALID_SPEC_YAML), json_error=True)
        result = spec.get_api_spec()
        mock_get.assert_called_once()
        assert result is not None
        assert result["openapi"] == "3.1.0"

    def test_get_api_spec_no_extension_invalid(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """A doc_path with no extension that is neither valid JSON nor YAML raises RuntimeError."""
        # Empty text → yaml.safe_load returns None; json raises JSONDecodeError
        spec = openapi_spec_factory(None)
        mock_get = mock_httpx(spec.doc_path, spec_text="", json_error=True)
        with pytest.raises(RuntimeError, match="Unable to load OpenAPI spec data"):
            spec.get_api_spec()
        mock_get.assert_called_once()

    def test_get_api_spec_invalid_extension(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """A doc_path with an unsupported extension (e.g., .txt) raises ValueError."""
        spec = openapi_spec_factory(".txt")
        mock_get = mock_httpx(spec.doc_path)
        with pytest.raises(ValueError, match="OpenAPI spec file must be JSON or YAML"):
            spec.get_api_spec()
        mock_get.assert_not_called()

    def test_get_api_spec_missing_openapi_field(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """A spec without the 'openapi' root field raises NotImplementedError."""
        spec = openapi_spec_factory()
        mock_get = mock_httpx(spec.doc_path, spec_dict={"info": {"title": "No version field"}})
        with pytest.raises(NotImplementedError, match="'openapi' field doesn't exist"):
            spec.get_api_spec()
        mock_get.assert_called_once()

    def test_get_api_spec_unsupported_version(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """A spec with an OpenAPI version that doesn't start with '3.' raises NotImplementedError."""
        spec = openapi_spec_factory()
        mock_get = mock_httpx(spec.doc_path, spec_dict={"openapi": "2.0", "info": {"title": "Old API"}, "paths": {}})
        with pytest.raises(NotImplementedError, match="Unsupported OpenAPI version"):
            spec.get_api_spec()
        mock_get.assert_called_once()

    def test_get_api_spec_http_error(
        self,
        mocker: MockerFixture,
        mock_httpx: Callable[..., MagicMock],
        openapi_spec_factory: Callable[..., OpenAPISpec],
    ) -> None:
        """An HTTP error raised by httpx propagates out of get_api_spec."""
        spec = openapi_spec_factory()
        mock_get = mock_httpx(
            spec.doc_path,
            http_error=httpx.HTTPStatusError("404", request=mocker.MagicMock(), response=mocker.MagicMock()),
        )
        with pytest.raises(httpx.HTTPStatusError):
            spec.get_api_spec()
        mock_get.assert_called_once()

    def test_get_api_spec_with_explicit_url(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """When an explicit URL is given, httpx.get is called with that URL, not base_url+doc_path."""
        spec = openapi_spec_factory()
        mock_get = mock_httpx(spec.doc_path, spec_dict=copy.deepcopy(VALID_SPEC_JSON))
        explicit_url = "https://other-host.com/v2/openapi.json"
        result = spec.get_api_spec(url=explicit_url)
        mock_get.assert_called_once_with(explicit_url)
        assert result is not None

    def test_get_api_spec_caching(
        self, mock_httpx: Callable[..., MagicMock], openapi_spec_factory: Callable[..., OpenAPISpec]
    ) -> None:
        """Calling get_api_spec() a second time returns the cached result without re-fetching."""
        spec = openapi_spec_factory()
        mock_get = mock_httpx(spec.doc_path, spec_dict=copy.deepcopy(VALID_SPEC_JSON))
        result1 = spec.get_api_spec()
        result2 = spec.get_api_spec()
        assert result1 is result2
        mock_get.assert_called_once()
        assert mock_get.call_count == 1


class TestParseSpec:
    """Tests for OpenAPISpec.parse() static method"""

    def test_deep_copies_input(self) -> None:
        """parse() does not mutate the original input dict."""
        original = copy.deepcopy(VALID_SPEC_JSON)
        original_before = copy.deepcopy(original)
        OpenAPISpec.parse(original)
        assert original == original_before

    def test_resolves_refs(self) -> None:
        """parse() resolves $ref entries inline."""
        spec_with_ref = {
            "openapi": "3.1.0",
            "tags": [{"name": "Test"}],
            "paths": {
                "/v1/foo": {
                    "post": {
                        "tags": ["Test"],
                        "requestBody": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Foo"}}}
                        },
                        "responses": {},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Foo": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                    }
                }
            },
        }

        result = OpenAPISpec.parse(spec_with_ref)
        schema = result["paths"]["/v1/foo"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema.get("type") == "object"
        assert schema.get("__schema_name__") == "Foo"

    def test_collects_tags(self) -> None:
        """parse() preserves top-level tags when they are defined."""
        result = OpenAPISpec.parse(copy.deepcopy(VALID_SPEC_JSON))
        assert result["tags"] == [{"name": "Test"}]

    def test_default_tag_when_none(self) -> None:
        """parse() adds a 'default' tag when no top-level tags are defined."""
        spec = {
            "openapi": "3.1.0",
            "paths": {"/v1/foo": {"get": {"responses": {}}}},
        }
        result = OpenAPISpec.parse(spec)
        assert result["tags"] == [{"name": "default"}]


class TestResolveSchemas:
    """Tests for OpenAPISpec._resolve_schemas() static method"""

    def test_simple_ref(self) -> None:
        """A simple $ref is resolved inline and __schema_name__ is added."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "post": {
                        "requestBody": {"schema": {"$ref": "#/components/schemas/Foo"}},
                        "responses": {},
                    }
                }
            },
            "components": {"schemas": {"Foo": {"type": "object", "properties": {"id": {"type": "integer"}}}}},
        }
        result = OpenAPISpec._resolve_schemas(spec)
        schema = result["paths"]["/v1/foo"]["post"]["requestBody"]["schema"]
        assert schema.get("type") == "object"
        assert schema.get("__schema_name__") == "Foo"
        assert "properties" in schema

    def test_nested_ref(self) -> None:
        """Nested $refs are resolved recursively. The outer schema name should be preserved"""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "post": {
                        "requestBody": {"schema": {"$ref": "#/components/schemas/Outer"}},
                        "responses": {},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Outer": {
                        "type": "object",
                        "properties": {"inner": {"$ref": "#/components/schemas/Inner"}},
                    },
                    "Inner": {"type": "string"},
                }
            },
        }

        result = OpenAPISpec._resolve_schemas(spec)
        schema = result["paths"]["/v1/foo"]["post"]["requestBody"]["schema"]
        assert schema.get("type") == "object"
        inner_schema = schema["properties"]["inner"]
        assert inner_schema.get("type") == "string"
        assert schema.get("__schema_name__") == "Outer"

    def test_circular_ref(self) -> None:
        """A circular $ref is handled without infinite recursion. The circular $ref is removed to break the cycle"""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/nodes": {
                    "get": {
                        "requestBody": {"schema": {"$ref": "#/components/schemas/Node"}},
                        "responses": {},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "child": {"$ref": "#/components/schemas/Node"}},
                    }
                }
            },
        }

        result = OpenAPISpec._resolve_schemas(spec)

        # The outer Node is resolved normally
        schema = result["paths"]["/v1/nodes"]["get"]["requestBody"]["schema"]
        assert schema.get("type") == "object"
        assert schema.get("__schema_name__") == "Node"

        # The circular $ref in child is removed to break the cycle (no infinite recursion)
        child = schema["properties"]["child"]
        assert isinstance(child, dict)
        assert "$ref" not in child

    def test_invalid_ref_value(self) -> None:
        """A $ref with a non-string value raises RuntimeError."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "get": {
                        "requestBody": {"schema": {"$ref": 12345}},
                        "responses": {},
                    }
                }
            },
        }

        with pytest.raises(RuntimeError, match="Detected invalid \\$ref value"):
            OpenAPISpec._resolve_schemas(spec)

    def test_unresolvable_ref(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unresolvable $ref logs a warning and continues gracefully."""

        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "get": {
                        "requestBody": {"schema": {"$ref": "#/components/schemas/Missing"}},
                        "responses": {},
                    }
                }
            },
            "components": {"schemas": {}},
        }

        with caplog.at_level(logging.WARNING):
            result = OpenAPISpec._resolve_schemas(spec)

        assert "SKIPPED: Unable to resolve '$ref'" in caplog.text
        # The schema entry should still exist but without a type
        assert result is not None

    def test_no_refs(self) -> None:
        """A spec without any $refs is returned unchanged (structurally)."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "get": {
                        "requestBody": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}},
                        "responses": {},
                    }
                }
            }
        }
        original = copy.deepcopy(spec)
        result = OpenAPISpec._resolve_schemas(spec)
        assert result["paths"] == original["paths"]


class TestAdjustSpec:
    """Tests for OpenAPISpec._adjust_spec() static method"""

    def test_path_level_params_moved_to_methods(self) -> None:
        """Path-level 'parameters' are copied into each HTTP method and then removed."""
        params = [{"name": "id", "in": "path", "required": True}]
        spec: dict[str, Any] = {
            "paths": {
                "/v1/items/{id}": {
                    "parameters": params,
                    "get": {"tags": ["Test"], "responses": {}},
                    "delete": {"tags": ["Test"], "responses": {}},
                }
            }
        }

        result = OpenAPISpec._adjust_spec(spec)

        path_obj = result["paths"]["/v1/items/{id}"]
        assert "parameters" not in path_obj
        assert path_obj["get"]["parameters"] == params
        assert path_obj["delete"]["parameters"] == params

    def test_additional_properties_absorbed(self) -> None:
        """additionalProperties with type=object and properties is absorbed into the parent."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "additionalProperties": {
                                            "type": "object",
                                            "properties": {"key": {"type": "string"}},
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {},
                    }
                }
            }
        }

        result = OpenAPISpec._adjust_spec(spec)

        schema = result["paths"]["/v1/foo"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert "additionalProperties" not in schema
        assert schema.get("type") == "object"
        assert "properties" in schema

    def test_required_boolean_set_on_properties(self) -> None:
        """Properties listed in the 'required' array get required=True set on their schema object."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "required": ["name"],
                                    }
                                }
                            }
                        },
                        "responses": {},
                    }
                }
            }
        }

        result = OpenAPISpec._adjust_spec(spec)
        props = result["paths"]["/v1/foo"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
        assert props["name"].get("required") is True
        assert "required" not in props["email"]


class TestCollectEndpointTags:
    """Tests for OpenAPISpec._collect_endpoint_tags() static method"""

    def test_collects_and_deduplicates_tags(self) -> None:
        """Tags from all endpoints are collected and deduplicated."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "get": {"tags": ["Alpha"], "responses": {}},
                    "post": {"tags": ["Alpha"], "responses": {}},
                },
                "/v1/bar": {
                    "get": {"tags": ["Beta"], "responses": {}},
                },
            }
        }
        tags = OpenAPISpec._collect_endpoint_tags(spec)
        assert set(tags) == {"Alpha", "Beta"}

    def test_defaults_to_default_tag(self) -> None:
        """When no endpoints define tags, a single 'default' tag is returned."""
        spec: dict[str, Any] = {
            "paths": {
                "/v1/foo": {
                    "get": {"responses": {}},
                }
            }
        }
        tags = OpenAPISpec._collect_endpoint_tags(spec)
        assert tags == ["default"]
