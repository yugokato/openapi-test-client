"""Unit tests for OpenAPIRequestValidator in validation.py"""

from __future__ import annotations

import pytest
from common_libs.clients.rest_client import RestResponse
from httpx import Client
from pytest_mock import MockerFixture

from openapi_test_client.libraries.openapi import endpoint
from openapi_test_client.libraries.openapi.base import OpenAPIBase, OpenAPIClient
from openapi_test_client.libraries.openapi.types import Unset
from openapi_test_client.libraries.openapi.validation import OpenAPIRequestValidator

pytestmark = [pytest.mark.unittest]


@pytest.fixture
def validator() -> OpenAPIRequestValidator:
    """A fresh OpenAPIRequestValidator instance"""
    return OpenAPIRequestValidator()


class TestOpenAPIRequestValidatorValidationMode:
    """Tests for OpenAPIRequestValidator.is_validation_mode()"""

    def test_returns_false_by_default(
        self, monkeypatch: pytest.MonkeyPatch, validator: OpenAPIRequestValidator
    ) -> None:
        """Test that is_validation_mode() returns False when VALIDATION_MODE env var is not set"""
        monkeypatch.delenv("VALIDATION_MODE", raising=False)
        assert validator.is_validation_mode() is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1"])
    def test_returns_true_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, validator: OpenAPIRequestValidator, value: str
    ) -> None:
        """Test that is_validation_mode() returns True for truthy VALIDATION_MODE values"""
        monkeypatch.setenv("VALIDATION_MODE", value)
        assert validator.is_validation_mode() is True

    def test_returns_false_when_set_to_false(
        self, monkeypatch: pytest.MonkeyPatch, validator: OpenAPIRequestValidator
    ) -> None:
        """Test that is_validation_mode() returns False when VALIDATION_MODE=false"""
        monkeypatch.setenv("VALIDATION_MODE", "false")
        assert validator.is_validation_mode() is False


class TestOpenAPIRequestValidatorValidate:
    """Tests for OpenAPIRequestValidator.validate()"""

    @pytest.fixture
    def _endpoint(self, mocker: MockerFixture, api_client: OpenAPIClient) -> object:
        """An Endpoint object for a typed API function (name: str required)"""
        mocker.patch.object(Client, "request")

        class ItemsAPI(OpenAPIBase):
            TAGs = ("Items",)
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = Unset) -> RestResponse: ...

        instance = ItemsAPI(api_client)
        return instance.create_item.endpoint

    def test_validate_passes_with_correct_params(
        self, monkeypatch: pytest.MonkeyPatch, validator: OpenAPIRequestValidator, _endpoint: object
    ) -> None:
        """Test that validate() does not raise when params match the expected types"""
        monkeypatch.setenv("VALIDATION_MODE", "true")
        validator.validate(_endpoint, (), {"name": "alice"})

    def test_validate_raises_on_type_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, validator: OpenAPIRequestValidator, _endpoint: object
    ) -> None:
        """Test that validate() raises ValueError with 'Request parameter validation failed' on type mismatch"""
        monkeypatch.setenv("VALIDATION_MODE", "true")
        with pytest.raises(ValueError, match="Request parameter validation failed"):
            validator.validate(_endpoint, (), {"name": 123})
