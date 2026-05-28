"""Unit tests for the validate kwarg on API function calls (OpenAPIBase)."""

import os
from typing import Any

import pytest
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.ext import ResponseExt
from httpx import AsyncClient, Client
from pytest_mock import MockerFixture

import openapi_test_client.libraries.core.utils.endpoint_call as endpoint_call_util
from openapi_test_client.libraries.openapi import endpoint
from openapi_test_client.libraries.openapi.base import OpenAPIBase, OpenAPIClient
from openapi_test_client.libraries.openapi.types import File, Unset
from openapi_test_client.libraries.openapi.utils.pydantic_model import in_validation_mode

pytestmark = [pytest.mark.unittest]


def _mock_response(mocker: MockerFixture, *, is_async: bool = False) -> Any:
    """Patch httpx Client.request (or AsyncClient.request) to return a 200 mock."""
    cls = AsyncClient if is_async else Client
    mock_response = mocker.MagicMock(spec=ResponseExt)
    mock_response.status_code = 200
    mocker.patch.object(cls, "request", return_value=mock_response)


@pytest.fixture
def openapi_api_class(api_client: OpenAPIClient) -> type[OpenAPIBase]:
    """An API class based on OpenAPIBase with one endpoint that has a typed parameter."""

    class TestOpenAPI(OpenAPIBase):
        TAGs = ("Test",)
        app_name = api_client.app_name

        @endpoint.post("/v1/resource")
        def create_resource(self, name: str) -> RestResponse: ...

    return TestOpenAPI


@pytest.fixture
def openapi_api_class_async(api_client_async: OpenAPIClient) -> type[OpenAPIBase]:
    """An API class based on OpenAPIBase (async) with one endpoint that has a typed parameter."""

    class TestOpenAPI(OpenAPIBase):
        TAGs = ("Test",)
        app_name = api_client_async.app_name

        @endpoint.get("/v1/resource")
        def list_resources(self, role: str) -> RestResponse: ...

    return TestOpenAPI


class TestValidateKwargOnCall:
    """Tests for the validate kwarg on synchronous API function calls"""

    def test_validate_true_raises_on_invalid_params(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate=True raises ValueError when an invalid param type is passed"""
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            instance.create_resource(name=123, validate=True)

    def test_validate_false_does_not_raise_on_invalid_params(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate=False (default) does not raise even for invalid param types"""
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        r = instance.create_resource(name=123, validate=False)
        assert r.ok

    def test_validate_not_sent_as_request_param(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate= kwarg does not appear in the outgoing HTTP request body"""
        captured: dict[str, Any] = {}

        def capture_request(*args: Any, **kwargs: Any) -> ResponseExt:
            captured.update(kwargs)
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(Client, "request", side_effect=capture_request)
        instance = openapi_api_class(api_client)
        instance.create_resource(name="foo", validate=True)

        # validate= must never reach the HTTP layer
        request_content = str(captured)
        assert "validate" not in request_content

    def test_validate_true_with_valid_params_succeeds(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate=True with valid params makes a successful request"""
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        r = instance.create_resource(name="valid-name", validate=True)
        assert r.ok

    def test_validate_false_disables_validation_when_env_is_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client: OpenAPIClient,
        openapi_api_class: type[OpenAPIBase],
    ) -> None:
        """Test that validate=False forces validation off even when VALIDATION_MODE env var is set.

        This is a regression test for the split-core refactor. Before the fix, passing validate=False
        when VALIDATION_MODE was set had no effect — pre_request_hook still read the env var as True
        and raised a validation error. validate=False must now explicitly suppress validation.
        """
        monkeypatch.setenv("VALIDATION_MODE", "true")
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        # name=123 is a type mismatch, but validate=False should suppress the validation
        r = instance.create_resource(name=123, validate=False)
        assert r.ok

    def test_validate_none_inherits_validation_mode_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client: OpenAPIClient,
        openapi_api_class: type[OpenAPIBase],
    ) -> None:
        """Test that omitting validate (None) inherits the VALIDATION_MODE env var state"""
        monkeypatch.setenv("VALIDATION_MODE", "true")
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            instance.create_resource(name=123)  # validate omitted → inherits env → validation active

    def test_validate_kwarg_nesting_safety(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate=True inside an in_validation_mode() block does not corrupt outer state"""
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        with in_validation_mode():
            assert os.environ.get("VALIDATION_MODE") is not None
            # Nested validate=True should not delete the outer env var on exit
            instance.create_resource(name="foo", validate=True)
            assert os.environ.get("VALIDATION_MODE") is not None, "validate=True removed the outer VALIDATION_MODE"

        assert os.environ.get("VALIDATION_MODE") is None, "in_validation_mode() did not clean up after itself"


class TestValidateKwargOnStream:
    """Tests for the validate kwarg on synchronous streaming calls"""

    def test_stream_validate_false_disables_validation_when_env_is_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client: OpenAPIClient,
        openapi_api_class: type[OpenAPIBase],
    ) -> None:
        """Test that stream validate=False forces validation off even when VALIDATION_MODE env var is set"""
        monkeypatch.setenv("VALIDATION_MODE", "true")

        def mock_stream(*args: Any, **kwargs: Any) -> Any:
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            mock_response.is_closed = True
            return mocker.MagicMock(__enter__=lambda s: mock_response, __exit__=lambda s, *a: None)

        mocker.patch.object(Client, "stream", side_effect=mock_stream)
        instance = openapi_api_class(api_client)

        with instance.create_resource.stream(name=123, validate=False):
            pass  # should not raise

    def test_stream_validate_none_inherits_validation_mode_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client: OpenAPIClient,
        openapi_api_class: type[OpenAPIBase],
    ) -> None:
        """Test that omitting validate on stream() inherits the VALIDATION_MODE env var state"""
        monkeypatch.setenv("VALIDATION_MODE", "true")

        def mock_stream(*args: Any, **kwargs: Any) -> Any:
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            mock_response.is_closed = True
            return mocker.MagicMock(__enter__=lambda s: mock_response, __exit__=lambda s, *a: None)

        mocker.patch.object(Client, "stream", side_effect=mock_stream)
        instance = openapi_api_class(api_client)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            with instance.create_resource.stream(name=123):  # validate omitted → inherits env
                pass

    def test_stream_validate_true_raises_on_invalid_params(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate=True raises ValueError when an invalid param type is passed to stream()"""
        _mock_response(mocker)
        instance = openapi_api_class(api_client)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            with instance.create_resource.stream(name=123, validate=True):
                pass

    def test_stream_validate_false_does_not_raise_on_invalid_params(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that stream validate=False (default) does not raise for invalid param types"""

        def mock_stream(*args: Any, **kwargs: Any) -> Any:
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            mock_response.is_closed = True
            return mocker.MagicMock(__enter__=lambda s: mock_response, __exit__=lambda s, *a: None)

        mocker.patch.object(Client, "stream", side_effect=mock_stream)
        instance = openapi_api_class(api_client)

        with instance.create_resource.stream(name=123, validate=False):
            pass  # should not raise

    def test_stream_validate_not_sent_as_request_param(
        self, mocker: MockerFixture, api_client: OpenAPIClient, openapi_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that validate= kwarg does not appear in the outgoing streaming HTTP request"""
        captured: dict[str, Any] = {}

        def capture_stream(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            mock_response.is_closed = True
            return mocker.MagicMock(__enter__=lambda s: mock_response, __exit__=lambda s, *a: None)

        mocker.patch.object(Client, "stream", side_effect=capture_stream)
        instance = openapi_api_class(api_client)

        with instance.create_resource.stream(name="foo", validate=True):
            pass

        request_content = str(captured)
        assert "validate" not in request_content


class TestValidateKwargOnAsyncCall:
    """Tests for the validate kwarg on async API function calls"""

    async def test_async_validate_false_disables_validation_when_env_is_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client_async: OpenAPIClient,
        openapi_api_class_async: type[OpenAPIBase],
    ) -> None:
        """Test that async validate=False forces validation off even when VALIDATION_MODE env var is set"""
        monkeypatch.setenv("VALIDATION_MODE", "true")
        _mock_response(mocker, is_async=True)
        instance = openapi_api_class_async(api_client_async)

        r = await instance.list_resources(role=42, validate=False)
        assert r.ok

    async def test_async_validate_none_inherits_validation_mode_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client_async: OpenAPIClient,
        openapi_api_class_async: type[OpenAPIBase],
    ) -> None:
        """Test that omitting validate on async calls inherits the VALIDATION_MODE env var state"""
        monkeypatch.setenv("VALIDATION_MODE", "true")
        _mock_response(mocker, is_async=True)
        instance = openapi_api_class_async(api_client_async)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            await instance.list_resources(role=42)  # validate omitted → inherits env → validation active

    async def test_async_validate_true_raises_on_invalid_params(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, openapi_api_class_async: type[OpenAPIBase]
    ) -> None:
        """Test that validate=True raises ValueError on invalid params in async mode"""
        _mock_response(mocker, is_async=True)
        instance = openapi_api_class_async(api_client_async)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            await instance.list_resources(role=42, validate=True)

    async def test_async_validate_false_does_not_raise(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, openapi_api_class_async: type[OpenAPIBase]
    ) -> None:
        """Test that async validate=False does not raise even for invalid params"""
        _mock_response(mocker, is_async=True)
        instance = openapi_api_class_async(api_client_async)

        r = await instance.list_resources(role=42, validate=False)
        assert r.ok

    async def test_async_validate_not_sent_as_request_param(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, openapi_api_class_async: type[OpenAPIBase]
    ) -> None:
        """Test that validate= kwarg does not appear in the outgoing async HTTP request"""
        captured: dict[str, Any] = {}

        async def capture_request(*args: Any, **kwargs: Any) -> ResponseExt:
            captured.update(kwargs)
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(AsyncClient, "request", side_effect=capture_request)
        instance = openapi_api_class_async(api_client_async)

        await instance.list_resources(role="admin", validate=True)

        request_content = str(captured)
        assert "validate" not in request_content


class TestValidateKwargOnAsyncStream:
    """Tests for the validate kwarg on async streaming calls"""

    async def test_async_stream_validate_false_disables_validation_when_env_is_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client_async: OpenAPIClient,
        openapi_api_class_async: type[OpenAPIBase],
    ) -> None:
        """Test that async stream validate=False forces validation off even when VALIDATION_MODE env var is set"""
        monkeypatch.setenv("VALIDATION_MODE", "true")

        def mock_stream(*args: Any, **kwargs: Any) -> Any:
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            mock_response.is_closed = True

            async def aenter(s: Any) -> Any:
                return mock_response

            async def aexit(s: Any, *a: Any) -> None:
                pass

            cm = mocker.MagicMock()
            cm.__aenter__ = aenter
            cm.__aexit__ = aexit
            return cm

        mocker.patch.object(AsyncClient, "stream", side_effect=mock_stream)
        instance = openapi_api_class_async(api_client_async)

        async with instance.list_resources.stream(role=42, validate=False):
            pass  # should not raise

    async def test_async_stream_validate_none_inherits_validation_mode_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
        api_client_async: OpenAPIClient,
        openapi_api_class_async: type[OpenAPIBase],
    ) -> None:
        """Test that omitting validate on async stream() inherits the VALIDATION_MODE env var state"""
        monkeypatch.setenv("VALIDATION_MODE", "true")
        _mock_response(mocker, is_async=True)
        instance = openapi_api_class_async(api_client_async)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            async with instance.list_resources.stream(role=42):  # validate omitted → inherits env
                pass

    async def test_async_stream_validate_true_raises_on_invalid_params(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, openapi_api_class_async: type[OpenAPIBase]
    ) -> None:
        """Test that validate=True raises ValueError for invalid params on async stream()"""
        _mock_response(mocker, is_async=True)
        instance = openapi_api_class_async(api_client_async)

        with pytest.raises(ValueError, match="Request parameter validation failed"):
            async with instance.list_resources.stream(role=42, validate=True):
                pass

    async def test_async_stream_validate_false_does_not_raise(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, openapi_api_class_async: type[OpenAPIBase]
    ) -> None:
        """Test that async stream validate=False does not raise for invalid params"""

        def mock_stream(*args: Any, **kwargs: Any) -> Any:
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            mock_response.is_closed = True

            async def aenter(s: Any) -> Any:
                return mock_response

            async def aexit(s: Any, *a: Any) -> None:
                pass

            cm = mocker.MagicMock()
            cm.__aenter__ = aenter
            cm.__aexit__ = aexit
            return cm

        mocker.patch.object(AsyncClient, "stream", side_effect=mock_stream)
        instance = openapi_api_class_async(api_client_async)

        async with instance.list_resources.stream(role=42, validate=False):
            pass  # should not raise


class TestValidationNormalizerFileIntegrity:
    """Tests that the validation normalizer does not corrupt File/bytes parameters."""

    @pytest.fixture
    def upload_api_class(self, api_client: OpenAPIClient) -> type[OpenAPIBase]:
        """An API class with one file-upload endpoint."""

        class UploadAPI(OpenAPIBase):
            TAGs = ("Upload",)
            app_name = api_client.app_name

            @endpoint.post("/v1/upload")
            def upload_file(self, *, attachment: File = Unset) -> RestResponse: ...

        return UploadAPI

    def test_file_param_survives_validation_normalizer(
        self, mocker: MockerFixture, api_client: OpenAPIClient, upload_api_class: type[OpenAPIBase]
    ) -> None:
        """Test that a File param is still a File instance when it reaches generate_rest_func_params
        in validation mode.

        Before the fix, the normalizer would JSON-roundtrip the File to a plain dict, causing the
        file-routing logic downstream to misroute it as a regular body parameter instead of a
        multipart file upload.
        """
        _mock_response(mocker)
        spy_generate = mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
        )

        the_file = File(filename="test.txt", content=b"hello world", content_type="text/plain")
        instance = upload_api_class(api_client)

        with in_validation_mode(True):
            instance.upload_file(attachment=the_file)

        endpoint_params = spy_generate.call_args.args[1]
        assert "attachment" in endpoint_params, "File param was lost before generate_rest_func_params"
        received = endpoint_params["attachment"]
        assert isinstance(received, File), (
            f"File param must still be a File instance after validation normalizer, got {type(received).__name__}. "
            "The normalizer must not JSON-roundtrip File values."
        )
        assert received.content == b"hello world", "File content must be intact (not base64-encoded)"

    def test_bytes_param_survives_validation_normalizer(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that a raw bytes param is not corrupted by the validation normalizer."""
        _mock_response(mocker)
        spy_generate = mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
        )

        class BinaryAPI(OpenAPIBase):
            TAGs = ("Binary",)
            app_name = api_client.app_name

            @endpoint.post("/v1/data")
            def upload_data(self, *, data: bytes = Unset) -> RestResponse: ...

        raw_bytes = b"\x00\x01\x02\x03"
        instance = BinaryAPI(api_client)

        with in_validation_mode(True):
            instance.upload_data(data=raw_bytes)

        endpoint_params = spy_generate.call_args.args[1]
        assert "data" in endpoint_params, "bytes param was lost before generate_rest_func_params"
        received = endpoint_params["data"]
        assert isinstance(received, bytes), (
            f"bytes param must remain bytes after validation normalizer, got {type(received).__name__}"
        )
        assert received == raw_bytes, "bytes content must be intact"
