from __future__ import annotations

import inspect
import json
import re
import shutil
import traceback
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from common_libs.ansi_colors import ColorCodes, color
from common_libs.clients.rest_client.ext import RestResponse
from common_libs.logging import get_logger

import openapi_test_client.libraries.api.api_functions.utils.endpoint_model as endpoint_model_util
import openapi_test_client.libraries.api.api_functions.utils.param_model as param_model_util
from openapi_test_client import (
    _CONFIG_DIR,
    _PACKAGE_DIR,
    DEFAULT_ENV,
    ENV_VAR_PACKAGE_DIR,
    get_config_dir,
    get_package_dir,
    is_external_project,
)
from openapi_test_client.clients import OpenAPIClient
from openapi_test_client.libraries.api import APIBase
from openapi_test_client.libraries.api.api_classes import get_api_classes, init_api_classes
from openapi_test_client.libraries.api.types import ParamModel
from openapi_test_client.libraries.common.code import diff_code, format_code
from openapi_test_client.libraries.common.constants import BACKSLASH, TAB, VALID_METHODS
from openapi_test_client.libraries.common.misc import (
    camel_to_snake,
    generate_class_name,
    import_module_from_file_path,
    import_module_with_new_code,
    reload_all_modules,
    reload_obj,
)

if TYPE_CHECKING:
    from openapi_test_client.clients import APIClientType
    from openapi_test_client.libraries.api import EndpointFunc
    from openapi_test_client.libraries.api.api_classes import APIClassType


logger = get_logger(__name__)

API_CLASS_DIR_NAME = "api"
API_MODEL_CLASS_DIR_NAME = "models"
API_CLASS_NAME_SUFFIX = "API"
BASE_CLASS_DIR_NAME = "base"
BASE_API_CLASS_NAME_SUFFIX = "BaseAPI"
API_CLIENT_CLASS_NAME_SUFFIX = "APIClient"
API_CLIENTS_DIR = Path(inspect.getabsfile(OpenAPIClient)).parent

DO_NOT_DELETE_COMMENT = '''\
"""
This file was automatically generated by a script.
Do NOT manually update the content.
"""

'''


@lru_cache
def generate_base_api_class(temp_api_client: OpenAPIClient) -> type[APIClassType]:
    """Generate new base API class file for the given temporary API client"""
    from openapi_test_client.libraries.api import Endpoint

    assert _is_temp_client(temp_api_client)
    app_name = temp_api_client.app_name
    base_api_class_name = generate_class_name(app_name, suffix=BASE_API_CLASS_NAME_SUFFIX)
    code = f'''\
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from {APIBase.__module__} import {APIBase.__name__}

if TYPE_CHECKING:
    from {_get_package(Endpoint)} import {Endpoint.__name__}


class {base_api_class_name}({APIBase.__name__}):
    """Base class for {app_name} API classes"""

    app_name = "{app_name}"
    endpoints: Optional[list[{Endpoint.__name__}]] = None
'''
    app_client_dir = get_client_dir(app_name)
    app_api_class_dir = app_client_dir / API_CLASS_DIR_NAME
    base_app_api_class_dir = app_api_class_dir / BASE_CLASS_DIR_NAME
    base_app_api_class_dir.mkdir(parents=True, exist_ok=True)
    base_app_api_class_file_stem = f"{app_name}_api"
    base_app_api_class_file_path = base_app_api_class_dir / f"{base_app_api_class_file_stem}.py"

    # Add base class
    if not base_app_api_class_file_path.exists():
        base_app_api_class_file_path.write_text(code)

    # Update __init__.py and import the class
    code = f"from .{base_app_api_class_file_stem} import {base_api_class_name}\n"
    _write_init_file(base_app_api_class_dir, code)
    mod = import_module_from_file_path(base_app_api_class_file_path)

    # NOTE: Below __init__.py code is intentionally excluded from the above import since the initialization at least
    # requires one API class to exist, which is not the case here.
    # generate_api_class() will reload all modules to reinitialize everything later
    base_api_class = getattr(mod, base_api_class_name)
    code = format_code(
        f"from .{BASE_CLASS_DIR_NAME} import {base_api_class.__name__}\n"
        f"from {init_api_classes.__module__} import {init_api_classes.__name__}\n\n"
        f"API_CLASSES = {init_api_classes.__name__}({base_api_class.__name__})\n"
    )
    _write_init_file(app_api_class_dir, code)

    return base_api_class


def generate_api_class(
    api_client: APIClientType,
    tag: str,
    class_name: str = None,
    add_endpoint_functions: bool = True,
    dry_run: bool = False,
    show_generated_code: bool = True,
) -> type[APIClassType] | tuple[str, Exception]:
    """Generate new API class file for the given API tag.

    If an exception is thrown during the process, API tag, API class name, and the exception will be returned.

    The following components will also be added:
    - Base API class (if missing)
    - Endpoint functions (if add_endpoint_functions is True)
    - models

    :param api_client: API client
    :param tag: API tag associated with the API class
    :param class_name: API class name. The name must end with "API"
    :param add_endpoint_functions: Also add endpoint functions
    :param dry_run: Do not actually add an API class file. Just show diffs for new API functions
    :param show_generated_code: Show generated code
    """
    is_temp_client = _is_temp_client(api_client)
    api_spec = api_client.api_spec.get_api_spec()
    assert api_spec
    tags = [t["name"] for t in api_spec["tags"]]
    if tag not in tags:
        raise RuntimeError(f"Specified tag '{tag}' is not defined in the API spec")

    # Create API class as stub
    if class_name:
        if not class_name.endswith(API_CLASS_NAME_SUFFIX):
            raise ValueError(f"class_name MUST ends with '{API_CLASS_NAME_SUFFIX}'")
        class_name_part = class_name.removesuffix(API_CLASS_NAME_SUFFIX)
    else:
        class_name_part = generate_class_name(tag)
        class_name = class_name_part + API_CLASS_NAME_SUFFIX

    class_file_name = camel_to_snake(class_name_part)

    app_name = api_client.app_name
    app_client_dir = get_client_dir(app_name)
    if is_temp_client:
        base_class = generate_base_api_class(api_client)
    else:
        base_class = _get_base_api_class(api_client)
    api_dir = app_client_dir / API_CLASS_DIR_NAME
    api_class_file_path = api_dir / f"{class_file_name.lower()}.py"
    logger.warning(
        f"Generating a new API class file:\n"
        f"- API class name: {class_name} (tag={tag})\n"
        f"- file path: {api_class_file_path}"
    )
    if api_class_file_path.exists():
        raise RuntimeError(f"{api_class_file_path} exists")

    from openapi_test_client.libraries.api import endpoint

    code = (
        "\n".join([f"from {_get_package(m)} import {m.__name__}" for m in [base_class, endpoint, RestResponse]])
        + "\n\n"
    )
    code += f"class {class_name}({base_class.__name__}):\n{TAB}TAGs = {tuple([tag])}\n\n"
    code = format_code(code, remove_unused_imports=False)
    if is_temp_client:
        api_class_file_path.parent.mkdir(parents=True, exist_ok=True)
    api_class_file_path.write_text(code)

    # Add endpoint functions
    try:
        mod = import_module_with_new_code(code, api_class_file_path)
        api_class = getattr(mod, class_name)
        result = update_endpoint_functions(
            api_class,
            api_spec,
            is_new_api_class=True,
            add_missing_endpoints=add_endpoint_functions,
            verbose=False,
            dry_run=dry_run,
            show_diff=show_generated_code,
        )
        _recursively_add_init_file(app_client_dir)
        if isinstance(result, tuple):
            # Something failed while updating endpoint functions
            return result
        else:
            assert result is True
            # Reimport everything to trigger the initialization of API classes
            reload_all_modules(app_client_dir)
            # reflect the updated code on the API class
            return reload_obj(api_class)
    finally:
        if dry_run:
            if is_temp_client:
                shutil.rmtree(app_client_dir)


def update_endpoint_functions(
    api_class: type[APIClassType],
    api_spec: dict[str, Any],
    is_new_api_class: bool = False,
    target_endpoints: list[str] = None,
    endpoints_to_ignore: list[str] = None,
    add_missing_endpoints: bool = True,
    update_param_models_only: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
    show_diff: bool = True,
) -> bool | tuple[str, Exception]:
    '''Update endpoint functions (signature and docstring) and API TAGs based on the definition of the latest API spec

    When no exception is thrown during the process, a boolean flag to indicate whether update is required or not is
    returned.
    If an exception is thrown, API class name and the exception will be returned.

    :param api_class: API class
    :param api_spec: OpenAPI spec
    :param is_new_api_class: This update is done against a newly created API class
    :param target_endpoints: List of endpoints to update the function definition.
                             Specify each endpoint in the form of "<METHOD> <PATH>"
    :param endpoints_to_ignore: List of endpoints to exclude from the update process
    :param add_missing_endpoints: Automatically add undefined endpoints as function name _unnamed_endpoint_{idx}
    :param update_param_models_only: Update param models only. API classes and functions will be untouched
    :param dry_run: Do not actually update an API class file
    :param verbose: Print each endpoint
    :param show_diff: Show diff when update is required

    The API class file would look like this:
        >>> from common_libs.clients.rest_client import RestResponse
        >>>
        >>> from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
        >>> from openapi_test_client.libraries.api.api_functions import endpoint
        >>>
        >>>
        >>> class SomeDemoAPI(DemoAppBaseAPI):
        >>>     TAGs = ("Some Tag",)
        >>>
        >>>     @endpoint.get("/v1/something/{uuid}")
        >>>     def do_something(
        >>>         self, uuid: str, /, *, param1: str = None, param2: int = None, **kwargs
        >>>     ) -> RestResponse:
        >>>     """Do something"""
        >>>     ...
        >>>
    '''
    from openapi_test_client.libraries.api import endpoint

    print(f"Checking API class: {api_class.__name__}...")
    # Regex for API class definition
    regex_api_class = re.compile(rf"class {api_class.__name__}\(\S+{BASE_API_CLASS_NAME_SUFFIX}\):")
    # Regex for TAGs and for individual tag inside TAGs
    regex_tags = re.compile(r"TAGs = \([^)]*\)", flags=re.MULTILINE)
    regex_tag = re.compile(r'"(?P<tag>[^"]*)"', flags=re.MULTILINE)
    # Regex for each endpoint function block
    tab = f"(?:{TAB}|\t)"
    regex_ep_func = re.compile(
        # decorator(s)
        rf"^(?P<decorators>{tab}@\S+\n)*?"
        # endpoint decorator
        rf"{tab}@{endpoint.__name__}\.(?P<method>{'|'.join(VALID_METHODS)})\("
        # endpoint path and endpoint options
        rf"(\n{tab}{{2}})?\"(?P<path>.+?)\"(?P<ep_options>,.+?)?(\n{tab})?\)\n"
        # function def
        rf"(?P<func_def>{tab}def (?P<func_name>.+?)\((?P<signature>.+?){tab}?\) -> {RestResponse.__name__}:\n)"
        # docstring
        rf"({tab}{{2}}(?P<docstring>\"{{3}}.*?\"{{3}})\n)?"
        # function body
        rf"(?P<func_body>\n*{tab}{{2}}(?:[^@]+|\.{{3}})\n)?$",
        flags=re.MULTILINE | re.DOTALL,
    )

    api_cls_file_path = Path(inspect.getabsfile(api_class))
    model_file_path = api_cls_file_path.parent.parent / API_MODEL_CLASS_DIR_NAME / api_cls_file_path.name
    original_api_cls_code = modified_api_cls_code = format_code(
        api_cls_file_path.read_text(), remove_unused_imports=False
    )
    if model_file_path.exists():
        original_model_code = format_code(model_file_path.read_text(), remove_unused_imports=False)
    else:
        original_model_code = ""
    method = path = func_name = None
    defined_endpoints = []
    param_models = []

    def update_existing_endpoints(target_api_class: type[APIClassType] = api_class):
        """Updated existing endpoint functions"""
        nonlocal modified_api_cls_code
        new_code = current_code = modified_api_cls_code
        api_spec_tags = set()

        for matched in re.finditer(regex_ep_func, current_code):
            matched_api_function_def = matched.string[matched.start() : matched.end()]
            method = matched.group("method")
            path = matched.group("path")
            func_def = matched.group("func_def")
            func_name = matched.group("func_name")
            signature = matched.group("signature")
            docstring = matched.group("docstring")
            func_body = matched.group("func_body")
            endpoint_str = f"{method.upper()} {path}"
            defined_endpoints.append((method, path))

            # For troubleshooting
            # print(
            #     f"{method.upper()} {path}:\n"
            #     f" - matched: {repr(matched.group(0))}\n"
            #     f" - decorators: {repr(decorators)}\n"
            #     f" - func_def: {repr(matched.group("func_def"))}\n"
            #     f"   - func_name: {repr(func_name)}\n"
            #     f"   - signature: {repr(signature)}\n"
            #     f" - docstring: {repr(docstring)}\n"
            #     f" - func_body: {repr(func_body)}\n"
            # )

            if (target_endpoints and endpoint_str not in target_endpoints) or (
                endpoints_to_ignore and endpoint_str in endpoints_to_ignore
            ):
                continue

            endpoint_function: EndpointFunc = getattr(target_api_class, func_name)
            if verbose:
                print(f"{TAB}- {method.upper()} {path}")

            # Skip if the endpoint defined was not found in the API spec
            try:
                endpoint_spec = api_spec["paths"][path][method]
            except KeyError:
                if endpoint_function.endpoint.is_documented:
                    err = f"{TAB}Not found: {method.upper()} {path} ({func_name})"
                    print(color(err, color_code=ColorCodes.RED))
                else:
                    msg = f"{TAB}Skipped undocumented endpoint: {method.upper()} {path} ({func_name})"
                    print(msg)
                continue
            else:
                for tag in endpoint_spec.get("tags") or ["default"]:
                    api_spec_tags.add(tag)

            doc_summary = (
                endpoint_spec.get("summary")
                or endpoint_spec.get("description")
                or "No summary or description is available for this API"
            )
            is_deprecated_api = endpoint_spec.get("deprecated", False)
            is_public_api = endpoint_spec.get("security") == []

            endpoint_model = endpoint_model_util.create_endpoint_model(endpoint_function, api_spec=api_spec)
            content_type = endpoint_model.content_type

            # Collect all param models for this endpoint
            param_models.extend(param_model_util.get_param_models(endpoint_model))
            # Fill missing imports (typing and custom param model classes). Duplicates will be removed by black at
            # the end
            if missing_imports_code := param_model_util.generate_imports_code_from_model(api_class, endpoint_model):
                new_code = missing_imports_code + new_code

            updated_api_func_code = matched_api_function_def

            # Update docstrings
            expected_docstring = f'"""{doc_summary}"""'
            if docstring:
                if docstring != expected_docstring:
                    updated_api_func_code = updated_api_func_code.replace(docstring, expected_docstring)
            else:
                updated_api_func_code = updated_api_func_code.replace(
                    func_def, func_def + f"{TAB * 2}{expected_docstring}\n"
                )

            # Update API function signatures
            new_func_signature = endpoint_model_util.generate_func_signature_in_str(endpoint_model).replace(
                BACKSLASH, BACKSLASH * 2
            )
            updated_api_func_code = re.sub(re.escape(signature), new_func_signature, updated_api_func_code)

            # Update func body if missing
            if not func_body:
                updated_api_func_code += f"{TAB * 2}...\n"

            # Update endpoint decorators
            decorator_content_type = f"@{endpoint.__name__}.content_type"
            if content_type and content_type not in ["*/*", "application/json"]:
                if (decorator := f'{decorator_content_type}("{content_type}")') not in updated_api_func_code:
                    updated_api_func_code = f"{TAB}{decorator}\n{updated_api_func_code}"
            else:
                updated_api_func_code = re.sub(
                    rf"{re.escape(decorator_content_type)}\([^)]+\)", "", updated_api_func_code
                )
            for flag, decorator in [
                (is_deprecated_api, f"@{endpoint.__name__}.is_deprecated"),
                (is_public_api, f"@{endpoint.__name__}.is_public"),
            ]:
                if flag:
                    if decorator not in updated_api_func_code:
                        updated_api_func_code = f"{TAB}{decorator}\n{updated_api_func_code}"
                else:
                    updated_api_func_code = re.sub(re.escape(decorator), "", updated_api_func_code)

            # Apply above updates to the original API func code
            new_code = new_code.replace(matched_api_function_def, updated_api_func_code)

        # Update TAGs attribute if API spec has a different tag definition
        if api_spec_tags:
            defined_tags = None
            tags_in_class = re.search(regex_tags, original_api_cls_code)
            if tags_in_class:
                defined_tags = re.findall(regex_tag, tags_in_class.group(0))
            if defined_tags or (not defined_tags and tags_in_class):
                # Update TAGs only when none of defined tags match with documented tags. Note that when multiple tags
                # are documented, the updated tags may not what you exactly want. If that is the case you'll need to
                # remove tags that is not needed for this API class
                if not set(defined_tags).intersection(api_spec_tags):
                    new_code = re.sub(regex_tags, f"TAGs = {tuple(api_spec_tags)}", new_code)
            else:
                api_class_matched = re.search(regex_api_class, original_api_cls_code)
                defined_api_class = api_class_matched.group(0)
                new_code = re.sub(
                    regex_api_class, f"{defined_api_class}\n{TAB}TAGs = {tuple(api_spec_tags)}\n", new_code
                )

        # Update code (if code changes)
        new_code = format_code(new_code, remove_unused_imports=False)
        if current_code != new_code:
            modified_api_cls_code = new_code

    def update_missing_endpoints():
        """Add endpoints that haven't been added as function name _unnamed_endpoint_{idx}"""
        nonlocal modified_api_cls_code
        new_code = modified_api_cls_code
        available_endpoints = []
        for path in api_spec["paths"]:
            try:
                for avl_method in api_spec["paths"][path]:
                    if avl_method in VALID_METHODS:
                        if tags_in_spec := api_spec["paths"][path][avl_method].get("tags") or ["default"]:
                            if set(tags_in_spec).intersection(set(api_class.TAGs)):
                                available_endpoints.append((avl_method, path))
            except Exception as e:
                logger.error(f"Encountered an error during parsing api spec for '{path}'", exc_info=e)
                raise

        if undefined_endpoints := [x for x in available_endpoints if x not in defined_endpoints]:
            if not is_new_api_class:
                new_endpoints_str = "\n".join([f"{TAB}- {meth.upper()} {ep}" for meth, ep in list(undefined_endpoints)])
                msg = f"{TAB}New endpoints available:\n{new_endpoints_str}"
                print(color(msg, color_code=ColorCodes.YELLOW))
            if add_missing_endpoints:
                undefined_ep_functions = ""
                undefined_func_name_prefix = "_unnamed_endpoint_"
                undefined_func_regex = rf"{undefined_func_name_prefix}(\d+)"
                start_idx = max(sorted([0] + list(set(int(x) for x in re.findall(undefined_func_regex, new_code))))) + 1
                for idx, (meth, path) in enumerate(undefined_endpoints, start=start_idx):
                    endpoint_str = f"{meth.upper()} {path}"
                    if (target_endpoints and endpoint_str not in target_endpoints) or (
                        endpoints_to_ignore and endpoint_str in endpoints_to_ignore
                    ):
                        continue

                    undefined_ep_functions += (
                        f"\n"
                        f'{TAB}@{endpoint.__name__}.{meth}("{path}")\n'
                        f"{TAB}def {undefined_func_name_prefix}{idx}(self) -> {RestResponse.__name__}:\n"
                        f"{TAB * 2}...\n"
                    )
                if undefined_ep_functions:
                    new_code += undefined_ep_functions
                    new_code = format_code(new_code, remove_unused_imports=False)
                    modified_api_cls_code = new_code

                    # Add undefined model names to the model module to fake model definitions. This will prevent
                    # ImportError to occur when importing API class below
                    is_temp_model_file = dry_run and not model_file_path.exists()
                    try:
                        if param_models:
                            if not model_file_path.exists():
                                model_file_path.write_text("")
                            mod_models = import_module_from_file_path(model_file_path)
                            for param_model in param_models:
                                if param_model.__name__ not in mod_models.__dict__.keys():
                                    setattr(mod_models, param_model.__name__, None)

                        # Import the API class with updated code
                        mod_api_class = import_module_with_new_code(new_code, api_class)
                    finally:
                        if is_temp_model_file:
                            model_file_path.unlink(missing_ok=True)

                    # Update signatures for the newly added endpoints
                    update_existing_endpoints(target_api_class=getattr(mod_api_class, api_class.__name__))

    api_cls_updated = model_updated = False
    try:
        update_existing_endpoints()
        update_missing_endpoints()
        # Format code again tp remove unused imports
        modified_api_cls_code = format_code(modified_api_cls_code)
        if is_new_api_class:
            # Clear the original code so that diff will show everything as new
            original_api_cls_code = original_model_code = ""
        if not update_param_models_only:
            if api_cls_updated := (original_api_cls_code != modified_api_cls_code):
                if not is_new_api_class:
                    msg = f"{TAB}Update{' required' if dry_run else 'd'}: {api_cls_file_path}"
                    print(color(msg, color_code=ColorCodes.YELLOW))

                if show_diff:
                    # Print diff
                    diff_code(
                        original_api_cls_code,
                        modified_api_cls_code,
                        fromfile=f"{api_cls_file_path.name} (before)",
                        tofile=f"{api_cls_file_path.name} (after)",
                    )

                # Update file
                if not dry_run:
                    api_cls_file_path.write_text(modified_api_cls_code)

        if param_models:
            modified_model_code = (
                f"from dataclasses import dataclass\n\n"
                f"from {ParamModel.__module__} import {ParamModel.__name__}\n\n"
            )
            for model in param_model_util.sort_by_dependency(param_model_util.dedup_models_by_name(param_models)):
                imports_code, model_code = param_model_util.generate_model_code_from_model(api_class, model)
                # Stack all imports to the top, then append model code at the end
                modified_model_code = imports_code + modified_model_code + model_code
            modified_model_code = format_code(DO_NOT_DELETE_COMMENT + modified_model_code)

            if model_updated := (original_model_code != modified_model_code):
                # Print diff
                msg = f"{TAB}Update{' required' if dry_run else 'd'} (models): {model_file_path}"
                print(color(msg, color_code=ColorCodes.YELLOW))
                if show_diff:
                    diff_code(
                        original_model_code,
                        modified_model_code,
                        fromfile=f"{model_file_path.name} (before)",
                        tofile=f"{model_file_path.name} (after)",
                    )
                # Update file
                if not dry_run:
                    model_file_path.parent.mkdir(parents=True, exist_ok=True)
                    model_file_path.write_text(modified_model_code)
    except Exception as e:
        # This should not happen
        tb = traceback.format_exc()
        err = f"Failed to update {api_cls_file_path}:"
        if all([func_name, method, path]):
            err += f" {func_name} ({method} {path})"
        err += f"\n{tb})\n"
        print(color(err, color_code=ColorCodes.RED))
        if api_cls_updated and not dry_run:
            # revert back to original code
            api_cls_file_path.write_text(original_api_cls_code)
        return (api_class.__name__, e)
    else:
        if verbose:
            print()
        return api_cls_updated or model_updated


def generate_api_client(temp_api_client: OpenAPIClient, show_generated_code: bool = True) -> type[APIClientType]:
    """Generate new API client file

    NOTE: generate_api_class() must be called first for this to work properly

    :param temp_api_client: Temporary API client
    :param show_generated_code: Show generated client code
    """
    logger.warning(f"Generating a new API client for {temp_api_client.app_name}")
    assert _is_temp_client(temp_api_client)
    app_name = temp_api_client.app_name
    base_api_class = generate_base_api_class(temp_api_client)

    app_client_dir = get_client_dir(app_name)
    app_client_api_class_dir = app_client_dir / API_CLASS_DIR_NAME
    if not app_client_api_class_dir.exists():
        raise RuntimeError(f"'{API_CLASS_NAME_SUFFIX}' directory does not exist in {app_client_dir}")

    api_client_class_name_part = generate_class_name(app_name)
    api_client_class_name = f"{api_client_class_name_part}{API_CLIENT_CLASS_NAME_SUFFIX}"

    imports_code = (
        f"from functools import cached_property\n\n"
        f"from {OpenAPIClient.__module__} import {OpenAPIClient.__name__}\n"
    )
    api_client_code = (
        f"class {api_client_class_name}({OpenAPIClient.__name__}):\n"
        f'{TAB}"""API client for {app_name}"""\n\n'
        f'{TAB}def __init__(self, env: str = "dev"):\n'
        f'{TAB}{TAB}super().__init__("{app_name}", env=env, doc="{temp_api_client.api_spec.doc_path}")\n\n'
    )

    # Add an accessor to each API class as a property
    for api_class in sorted(
        get_api_classes(app_client_api_class_dir, base_api_class),
        key=lambda x: x.__name__,
    ):
        mod = inspect.getmodule(api_class)
        imports_code += f"from .{API_CLASS_DIR_NAME}.{Path(mod.__file__).stem} import {api_class.__name__}\n"
        property_name = camel_to_snake(api_class.__name__.removesuffix("API")).upper()
        api_client_code += (
            f"{TAB}@cached_property\n"
            f"{TAB}def {property_name}(self):\n"
            f"{TAB}{TAB}return {api_class.__name__}(self)\n\n"
        )

    code = format_code(imports_code + api_client_code)
    if show_generated_code:
        diff_code("", code)

    client_module_name = f"{app_name}_client"
    api_client_file_path = app_client_dir / f"{client_module_name}.py"
    api_client_file_path.write_text(code)

    # Update __init__.py
    code = f"from .{client_module_name} import {api_client_class_name}\n"
    _write_init_file(app_client_dir, code)

    mod = import_module_from_file_path(api_client_file_path)
    return getattr(mod, api_client_class_name)


def get_client_dir(client_name: str) -> Path:
    """Get directory path for the client

    :param client_name: Client name
    """
    return get_package_dir() / API_CLIENTS_DIR.name / client_name


def setup_external_directory(client_name: str, base_url: str, env: str = DEFAULT_ENV):
    """Set up external project directory

    :param client_name: Client name
    :param base_url: API base URL
    :param env: The target environment this client is generated for
    """
    assert is_external_project()
    api_client_lib_dir = get_package_dir()
    api_client_lib_dir.mkdir(parents=True, exist_ok=True)
    # Add __init__.py
    code = (
        f"import os\n"
        f"from pathlib import Path\n\n"
        f'os.environ["{ENV_VAR_PACKAGE_DIR}"] = str(Path(__file__).parent)'
    )
    _write_init_file(api_client_lib_dir, format_code(DO_NOT_DELETE_COMMENT + code))

    # Add a hidden file to the package directory so that we can locate this directory later
    (api_client_lib_dir / f".{_PACKAGE_DIR.name}").write_text("")

    # Copy /cfg from this project, add base url for this client
    cfg_dir = get_config_dir()
    url_conf_file = cfg_dir / "urls.json"
    if cfg_dir.exists():
        url_conf: dict[str, Any] = json.loads(url_conf_file.read_text())
        if env not in url_conf:
            url_conf[env] = {}
        url_conf[env][client_name] = base_url
        url_conf_file.write_text(json.dumps(url_conf, indent=2))
    else:
        shutil.copytree(_CONFIG_DIR, cfg_dir)
        url_conf_file.write_text(json.dumps({env: {client_name: base_url}}, indent=2))

    # Add client directory
    client_dir = get_client_dir(client_name)
    client_dir.mkdir(parents=True, exist_ok=True)

    # Add missing __init__.py to all directories
    _recursively_add_init_file(api_client_lib_dir, exclude_dirs=("cfg",))


def _is_temp_client(api_client: APIClientType) -> bool:
    return type(api_client) is OpenAPIClient


def _get_base_api_class(api_client: APIClientType) -> type[APIClassType]:
    client_file_path = Path(inspect.getabsfile(type(api_client)))
    app_client_dir = client_file_path.parent
    base_api_class_name = generate_class_name(api_client.app_name, suffix=BASE_API_CLASS_NAME_SUFFIX)
    mod = import_module_from_file_path(app_client_dir / API_CLASS_DIR_NAME)
    return getattr(mod, base_api_class_name)


def _recursively_add_init_file(base_dir: Path, exclude_dirs: tuple[str] = ()):
    def add_init_file(current_dir: Path):
        if current_dir.name not in exclude_dirs:
            if not (current_dir / "__init__.py").exists():
                _write_init_file(current_dir)
            for file_or_dir in current_dir.iterdir():
                if file_or_dir.is_dir():
                    add_init_file(file_or_dir)

    add_init_file(base_dir)


def _write_init_file(dir_path: Path, data: str = ""):
    init_file_path = dir_path / "__init__.py"
    init_file_path.write_text(data)


@lru_cache
def _get_package(obj: Any) -> str:
    mod = inspect.getmodule(obj)
    return mod.__package__
