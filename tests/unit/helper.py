from copy import deepcopy
from pathlib import Path
from typing import Any


def load_test_data(filename: str) -> str:
    """Load test data"""
    return (Path(__file__).parent / "data" / filename).read_text()


def get_defined_endpoints(api_spec: dict[str, Any]) -> list[str]:
    """Get API endpoints defined in the API spec"""
    path_objects = api_spec["paths"]
    endpoints = []
    for path, path_obj in path_objects.items():
        for method in path_obj:
            endpoints.append(f"{method.upper()} {path}")
    if not endpoints:
        raise ValueError("No endpoints are defined")
    return endpoints


def generate_updated_specs(
    openapi_specs: dict[str, Any], *, endpoint_param_to_add: str, model_param_to_delete: str
) -> dict[str, Any]:
    """Update OpenAPI specs

    :param openapi_specs: The original spec data
    :param endpoint_param_to_add: A new parameter to be added to each endpoint
    :param model_param_to_delete: An existing Metadata model parameter to delete
    """
    updated_openapi_specs = deepcopy(openapi_specs)
    param = {endpoint_param_to_add: {"type": "number"}}
    query_param = {"name": endpoint_param_to_add, "in": "query", "schema": {"type": "number"}}
    updated_openapi_specs["paths"]["/v1/something"]["post"]["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ].update(param)
    updated_openapi_specs["paths"]["/v1/something/{name}"]["get"]["parameters"].append(query_param)
    updated_openapi_specs["paths"]["/v1/something/{name}"]["delete"]["parameters"].append(query_param)
    del updated_openapi_specs["components"]["schemas"]["Metadata"]["properties"][model_param_to_delete]

    return updated_openapi_specs
