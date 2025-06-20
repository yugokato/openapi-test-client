from __future__ import annotations

import inspect
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import MISSING, field, make_dataclass
from typing import TYPE_CHECKING, Any, cast

from common_libs.logging import get_logger

from openapi_test_client.libraries.api.api_functions.utils import param_model as param_model_util
from openapi_test_client.libraries.api.api_functions.utils import param_type as param_type_util
from openapi_test_client.libraries.api.types import DataclassModelField, EndpointModel, File, Kwargs, ParamDef, Unset

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import EndpointFunc


logger = get_logger(__name__)


def create_endpoint_model(endpoint_func: EndpointFunc, api_spec: dict[str, Any] | None = None) -> type[EndpointModel]:
    """Create a model class for the endpoint from either current function signature or Swagger API spec

    :param endpoint_func: Endpoint function for the endpoint
    :param api_spec: Create a model from the OpenAPI spec. Otherwise the model be created from the existing endpoint
                     function signatures
    """
    path_param_fields: list[DataclassModelField] = []
    body_or_query_param_fields: list[DataclassModelField] = []
    model_name = f"{type(endpoint_func).__name__.replace('EndpointFunc', EndpointModel.__name__)}"
    content_type = None
    if api_spec:
        # Generate model fields from the OpenAPI spec. See https://swagger.io/specification/ for the specification
        method = endpoint_func.endpoint.method
        path = endpoint_func.endpoint.path
        operation_obj = api_spec["paths"][path][method]
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
            path_param_fields = [DataclassModelField(x, str) for x in expected_path_params]
            body_or_query_param_fields = [x for x in body_or_query_param_fields if x[0] not in expected_path_params]
    else:
        # Generate model fields from the function signature
        sig = inspect.signature(endpoint_func._original_func)
        for name, param_obj in sig.parameters.items():
            if name == "self" or param_obj.kind == inspect.Parameter.VAR_KEYWORD:
                continue
            elif param_obj.default == inspect.Parameter.empty:
                # Positional arguments (path parameters)
                path_param_fields.append(DataclassModelField(name, param_obj.annotation))
            else:
                # keyword arguments (body/query parameters)
                _add_body_or_query_param_field(body_or_query_param_fields, name, param_obj.annotation)

    # Address the case where a path param name conflicts with body/query param name
    for i, (field_name, field_type, _) in enumerate(path_param_fields):
        if field_name in [x[0] for x in body_or_query_param_fields]:
            path_param_fields[i] = DataclassModelField(f"{field_name}_", field_type)

    # Some OpenAPI specs define a parameter name using characters we can't use as a python variable name.
    # We will use the cleaned name as the model field and annotate it as `Annotated[field_type, Alias(<original_val>)]`
    # When calling an endpoint function, the actual name will be automatically resolved in the payload/query parameters
    endpoint = f"{endpoint_func.method.upper()} {endpoint_func.path}"
    param_model_util.alias_illegal_model_field_names(endpoint, path_param_fields)
    param_model_util.alias_illegal_model_field_names(endpoint, body_or_query_param_fields)

    fields = path_param_fields + body_or_query_param_fields
    return cast(
        type[EndpointModel],
        make_dataclass(
            model_name,
            fields,
            bases=(EndpointModel,),
            namespace={"content_type": content_type, "endpoint_func": endpoint_func},
            kw_only=True,
            frozen=True,
        ),
    )


def generate_func_signature_in_str(model: type[EndpointModel]) -> str:
    """Convert model to type annotated function signature in string

    :param model: Endpoint model
    """
    model_dataclass_fields = model.__dataclass_fields__
    signatures = ["self"]
    has_path_var = False
    has_params = False
    positional_only_added = False
    for field_name, field_obj in model_dataclass_fields.items():
        is_path_var = field_obj.default is MISSING
        type_annotation = param_type_util.get_type_annotation_as_str(field_obj.type)
        if is_path_var:
            has_path_var = True
            sig = f"{field_name}: {type_annotation}"
        else:
            if has_path_var and not positional_only_added:
                signatures.append("/")
            positional_only_added = True
            if not has_params:
                signatures.append("*")
            has_params = True
            sig = f"{field_name}: {type_annotation} = Unset"
        signatures.append(sig)
    if has_path_var and not positional_only_added:
        signatures.append("/")

    kwargs_arg = "**kwargs"
    kwargs_type = f"Unpack[{Kwargs.__name__}]"
    if any("kwargs:" in s for s in signatures):
        kwargs_arg = kwargs_arg + "_"
    signatures.append(f"{kwargs_arg}: {kwargs_type}")
    return ", ".join(signatures)


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
                        path_param_fields.append(DataclassModelField(param_name, param_type_annotation))
                elif param_location == "query":
                    if method.upper() != "GET":
                        # Annotate query params for non GET endpoints
                        param_type_annotation = param_type_util.annotate_type(param_type_annotation, "query")

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
                            _add_body_or_query_param_field(
                                body_or_query_param_fields, param_name, param_type_annotation, param_obj=param_obj
                            )

                    else:
                        _add_body_or_query_param_field(
                            body_or_query_param_fields, param_name, param_type_annotation, param_obj=param_obj
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
                # requests lib option.
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
                    param_type = File
                    if not param_def.is_required:
                        param_type = param_type | None  # type: ignore[assignment]
                    _add_body_or_query_param_field(
                        body_or_query_param_fields, param_name, param_type, param_obj=param_obj
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
                        _add_body_or_query_param_field(
                            body_or_query_param_fields, param_name, param_type_annotation, param_obj=param_obj
                        )
            except Exception:
                logger.error(
                    "Encountered an error while processing the param object in 'requestBody':\n"
                    f"- param name: {param_name}\n"
                    f"- param object: {param_obj}"
                )
                raise

    schema_obj = request_body_obj["content"][content_type]["schema"]
    parse_schema_obj(schema_obj)

    return content_type


def _add_body_or_query_param_field(
    param_fields: list[DataclassModelField],
    param_name: str,
    param_type_annotation: Any,
    param_obj: Mapping[str, Any] | dict[str, Any] | None = None,
) -> None:
    if param_name not in [x[0] for x in param_fields]:
        param_fields.append(
            DataclassModelField(param_name, param_type_annotation, default=field(default=Unset, metadata=param_obj))
        )


def _is_file_param(
    content_type: str,
    param_def: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType,
) -> bool:
    if content_type == "multipart/form-data":
        if isinstance(param_def, ParamDef):
            return param_def.format == "binary"
        elif isinstance(param_def, ParamDef.ParamGroup):
            return any([p.format == "binary" for p in param_def])
        else:
            return False
    else:
        return False
