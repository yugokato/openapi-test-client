from api_client_core.endpoints.endpoint_factory import endpoint as _endpoint

__all__ = ["endpoint"]


class endpoint(_endpoint):
    """Thin typing overlay around the core `endpoint`.

    See the `endpoint_factory.pyi` stub for signatures. See the core `endpoint` class for behavior.
    """
