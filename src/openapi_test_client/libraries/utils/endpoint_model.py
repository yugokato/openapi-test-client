"""OpenAPI spec-based endpoint model creation utilities."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import field
from typing import TYPE_CHECKING, Any, cast

from api_client_core.endpoints.utils.endpoint_model import add_body_or_query_param_field, build_endpoint_model
from api_client_core.types import EndpointModel as _CoreEndpointModel
from common_libs.logging import get_logger

import openapi_test_client.libraries.utils.param_model as param_model_util
import openapi_test_client.libraries.utils.param_type as param_type_util
from openapi_test_client.libraries.types import DataclassModelField, EndpointModel, File, ParamDef, Query, Unset

if TYPE_CHECKING:
    from api_client_core import EndpointFunc

logger = get_logger(__name__)


def create_endpoint_model_from_spec(
    endpoint_func: EndpointFunc[Any],
    api_spec: dict[str, Any],
) -> type[EndpointModel]:
    """Create an EndpointModel from the OpenAPI spec.

    :param endpoint_func: Endpoint function for the endpoint
    :param api_spec: OpenAPI spec dict
    """
    path_param_fields: list[DataclassModelField] = []
    body_or_query_param_fields: list[DataclassModelField] = []
    content_type = _parse_endpoint_model_from_spec(
        endpoint_func, api_spec, path_param_fields, body_or_query_param_fields
    )
    # Use the OpenAPI layer's richer alias_illegal_model_field_names, which also covers OpenAPI
    # annotation type names (Format, Constraint, ParamModel, ...) that core does not know about.
    return cast(
        type[EndpointModel],
        build_endpoint_model(
            endpoint_func,
            path_param_fields,
            body_or_query_param_fields,
            content_type,
            field_name_sanitizer=param_model_util.alias_illegal_model_field_names,
            # mypy treats EndpointModel as abstract here since it descends from a Protocol
            # (DataclassModel). The cast is safe since it's a plain concrete dataclass base.
            model_base=cast(type[_CoreEndpointModel], EndpointModel),
        ),
    )


def _parse_endpoint_model_from_spec(
    endpoint_func: EndpointFunc[Any],
    api_spec: dict[str, Any],
    path_param_fields: list[DataclassModelField],
    body_or_query_param_fields: list[DataclassModelField],
) -> str | None:
    """Parse endpoint model fields from the OpenAPI spec

    :param endpoint_func: Endpoint function for the endpoint
    :param api_spec: OpenAPI spec dict
    :param path_param_fields: List to populate with path parameter fields
    :param body_or_query_param_fields: List to populate with body/query parameter fields
    :returns: content_type if a request body was parsed, else None
    """
    method = endpoint_func.endpoint.method
    path = endpoint_func.endpoint.path
    operation_obj = api_spec["paths"][path][method]
    content_type = None

    if parameter_objects := operation_obj.get("parameters"):
        _parse_parameter_objects(method, parameter_objects, path_param_fields, body_or_query_param_fields)
    if request_body := operation_obj.get("requestBody"):
        try:
            content_type = _parse_request_body_object(request_body, body_or_query_param_fields)
        except Exception:
            logger.warning(f"Unable to parse the following requestBody obj:\n{request_body}")
            raise

    expected_path_params = re.findall(r"{([^}]+)}", path)
    documented_path_params = [x[0] for x in path_param_fields]
    if undocumented_path_params := [x for x in expected_path_params if x not in documented_path_params]:
        logger.warning(f"{method.upper()} {path}: Found undocumented path parameters: {undocumented_path_params}")
        # Some OpenAPI specs don't properly document path parameters at all, or path parameters could be documented
        # as incorrect "in" like "query". We fix this by adding the missing path parameters, and remove them from
        # body/query params if any
        path_param_fields.clear()
        path_param_fields.extend(
            DataclassModelField(x, str, field(metadata={"path": True})) for x in expected_path_params
        )
        body_or_query_param_fields[:] = [x for x in body_or_query_param_fields if x[0] not in expected_path_params]

    return content_type


def _parse_parameter_objects(
    method: str,
    parameter_objects: list[dict[str, Any]],
    path_param_fields: list[DataclassModelField],
    body_or_query_param_fields: list[DataclassModelField],
) -> None:
    """Parse parameter objects

    https://swagger.io/specification/#parameter-object
    """
    for param_obj in deepcopy(parameter_objects):
        # NOTE: param_obj will be empty here if its $ref wasn't successfully resolved. We will ignore these
        if param_obj:
            param_name = ""
            try:
                param_name = param_obj["name"]
                param_location = param_obj["in"]
                param_def = ParamDef.from_param_obj(param_obj)
                # In case path parameters are incorrectly documented as required: false, we force make them required as
                # path parameters will always be required for our client
                is_required = True if param_location == "path" else None
                param_type_annotation = param_type_util.resolve_type_annotation(
                    param_name, param_def, _is_required=is_required
                )
                if param_location in ["header", "cookies"]:
                    # We currently don't support these
                    continue
                elif param_location == "path":
                    if param_name not in [x[0] for x in path_param_fields]:
                        # Handle duplicates. Some API specs incorrectly document duplicated parameters
                        path_param_fields.append(
                            DataclassModelField(param_name, param_type_annotation, field(metadata={"path": True}))
                        )
                elif param_location == "query":
                    if method.upper() != "GET":
                        # Annotate query params for non GET endpoints
                        param_type_annotation = param_type_util.annotate_type(param_type_annotation, Query())

                    if "schema" in param_obj:
                        # defined as model. We unpack the model details
                        schema_obj = param_obj["schema"]
                        if "items" in schema_obj:
                            schema_obj = schema_obj["items"]

                        if "properties" in schema_obj:
                            properties = schema_obj["properties"]

                            for k, v in properties.items():
                                if "name" not in properties[k]:
                                    properties[k]["name"] = k
                                properties[k]["in"] = param_location

                            # Replace the param objects and parse it again
                            parameter_objects.clear()
                            parameter_objects.extend(properties.values())
                            _parse_parameter_objects(
                                method, parameter_objects, path_param_fields, body_or_query_param_fields
                            )
                        else:
                            add_body_or_query_param_field(
                                body_or_query_param_fields,
                                param_name,
                                param_type_annotation,
                                metadata=param_obj,
                                default=Unset,
                            )

                    else:
                        add_body_or_query_param_field(
                            body_or_query_param_fields,
                            param_name,
                            param_type_annotation,
                            metadata=param_obj,
                            default=Unset,
                        )
                else:
                    raise NotImplementedError(f"Unsupported param 'in': {param_location}")
            except Exception:
                logger.error(
                    "Encountered an error while processing a param object in 'parameters':\n"
                    f"- param name: {param_name}\n"
                    f"- param object: {param_obj}"
                )
                raise


def _parse_request_body_object(
    request_body_obj: dict[str, Any], body_or_query_param_fields: list[DataclassModelField]
) -> str | None:
    """Parse request body object

    https://swagger.io/specification/#request-body-object
    """
    contents = request_body_obj["content"].keys()
    # TODO: Support multiple content types
    content_type = next(iter(contents))

    def parse_schema_obj(obj: dict[str, Any]) -> list[dict[str, Any] | list[dict[str, Any]]] | None:
        # This part has some variations, and sometimes not consistent
        if not (properties := obj.get("properties", {})):
            schema_type = obj.get("type")
            if (
                # The top-level array object is an exceptional case where it needs to be sent as `json` using the raw
                # option.
                (obj.get("items") and schema_type == "array")
                or
                # Irregular case. This endpoint allows ANY parameters (our **kwargs will handle this)
                schema_type == "object"
            ):
                properties = {}
            elif "oneOf" in obj:
                return [parse_schema_obj(x) for x in obj["oneOf"]]
            elif "anyOf" in obj:
                return [parse_schema_obj(x) for x in obj["anyOf"]]
            elif "allOf" in obj:
                return [parse_schema_obj(x) for x in obj["allOf"]]
            elif not re.match(
                r"\*/\*|application/json.*|multipart/form-data|application/x-www-form-urlencoded", content_type
            ):
                # The API directly takes data that is not form-encoded (eg. send tar binary data)
                properties = {"data": schema_obj}
            elif obj == {}:
                # Empty schema
                properties = {}
            else:
                # An example from actual OpenAPI spec: {"content": {"application/json": {"schema": {"type": 'string"}}
                raise NotImplementedError(f"Unsupported schema obj:\n{json.dumps(obj, indent=4, default=str)}")

        for param_name in properties:
            param_obj = properties[param_name]
            try:
                param_def = ParamDef.from_param_obj(param_obj)
                if _is_file_param(content_type, param_def):
                    param_type: Any = File
                    if not param_def.is_required:
                        param_type = param_type | None
                    add_body_or_query_param_field(
                        body_or_query_param_fields, param_name, param_type, metadata=param_obj, default=Unset
                    )
                else:
                    existing_param_names = [x[0] for x in body_or_query_param_fields]
                    if param_name in existing_param_names:
                        duplicated_param_fields = [x for x in body_or_query_param_fields if x[0] == param_name]
                        param_type_annotations = []
                        for _, t, m in duplicated_param_fields:
                            param_type_annotations.append(t)
                        param_type_annotation = param_type_util.generate_union_type(param_type_annotations)
                        merged_param_field = DataclassModelField(
                            param_name,
                            param_type_annotation,
                            default=field(default=Unset, metadata=param_obj),
                        )
                        body_or_query_param_fields[existing_param_names.index(param_name)] = merged_param_field
                    else:
                        param_type_annotation = param_type_util.resolve_type_annotation(param_name, param_def)
                        add_body_or_query_param_field(
                            body_or_query_param_fields,
                            param_name,
                            param_type_annotation,
                            metadata=param_obj,
                            default=Unset,
                        )
            except Exception as e:
                logger.error(
                    "Encountered an error while processing the param object in 'requestBody':\n"
                    f"- error: {type(e).__name__}: {e}\n"
                    f"- param name: {param_name}\n"
                    f"- param object: {param_obj}"
                )
                raise

    schema_obj = request_body_obj["content"][content_type]["schema"]
    parse_schema_obj(schema_obj)

    return content_type


def _is_file_param(
    content_type: str,
    param_def: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType,
) -> bool:
    if content_type == "multipart/form-data":
        if isinstance(param_def, ParamDef):
            return param_def.format == "binary"
        elif isinstance(param_def, ParamDef.ParamGroup):
            return any(_is_file_param(content_type, p) for p in param_def)
        else:
            return False
    else:
        return False
