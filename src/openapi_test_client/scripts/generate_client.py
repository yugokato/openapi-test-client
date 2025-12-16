#!/usr/bin/env python3

"""
This is a script to generate/update an API client from OpenAPI specs.
You can directly execute the script, or use a CLI command `openapi-client` that should be available after setting
up the project.

The script requires either `generate` or `upgrade` as the first argument. See help (-h/--help) for available options
for each action.

usage: openapi-client [-h] {generate,update} ...

positional arguments:
  {generate,update}  Action to take
    generate         Generate a new API client from an OpenAPI spec URL
    update           Update an existing API client


1. Generate a new API client:
    usage: openapi-client generate [-h] [-e ENV] [-d] -u URL -a APP_NAME [--dir EXTERNAL_DIR] [-q]

    options:
      -h, --help            show this help message and exit
      -e ENV, --env ENV     Target environment
      -d, --dry-run         Just show code for API client, API classes, and models to be generated (Code will not be
                            actually added)
      -u URL, --url URL     URL to the OpenAPI spec file (must be JSON or YAML) to generate the API client with
      -a APP_NAME, --app APP_NAME
                            The app name associated with the API client
      --dir DIRECTORY       A directory path to an external location to save the generated client code and modules to.
                            This is optional if your project was cloned from the original repo
      -q, --quiet           Do not show generated code on the console



2. Update an existing API client:
    usage: openapi-client update [-h] [--env ENV] [-d] -c CLIENT_NAME [-t TAG | -e [ENDPOINT ...] | -a
                                       [API_CLASS_NAME ...] | -f [API_FUNC_NAME ...] | -A] [-m]
                                       [-i [ENDPOINTS_TO_IGNORE ...]] [-I] [-q]

    options:
      -h, --help            show this help message and exit
      --env ENV             Target env
      -d, --dry-run         Just run the check and show diff (Code will not actually be updated)
      -c CLIENT_NAME, --client CLIENT_NAME
                            Our API client app name
      -t TAG, --tag TAG     Limit the scope of update to the specific API tag. If the tag is not associated with any
                            of existing API classes, a new API class will be dynamically created for the tag.
                            Otherwise the existing API class functions will be updated
      -e [ENDPOINT ...], --endpoint [ENDPOINT ...]
                            Target specific endpoint(s) to update. The format of each endpoint should be "<METHOD>
                            <path>"
      -a [API_CLASS_NAME ...], --api-class [API_CLASS_NAME ...]
                            Limit the scope of update to the specific API class name(s)
      -f [API_FUNC_NAME ...], --api-function [API_FUNC_NAME ...]
                            Limit the scope of update to the specific API function name(s)
      -A, --add-api-class   Add API class files for API tags that don't currently have an associated API class
      -m, --model-only      Update param models only. API class files will not be touched
      -i [ENDPOINTS_TO_IGNORE ...], --ignore [ENDPOINTS_TO_IGNORE ...]
                            Endpoint(s) to ignore. The format of each endpoint should be "<METHOD> <path>"
      -I, --ignore-undefined-endpoints
                            Update existing endpoints only. Undefined/missing endpoints won't be automatically added
      -q, --quiet           Do not show diff on the console
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING

from common_libs.clients.rest_client import RestClient
from common_libs.logging import get_logger
from common_libs.utils import clean_obj_name, list_items

from openapi_test_client import (
    _PACKAGE_DIR,
    _PROJECT_ROOT_DIR,
    DEFAULT_ENV,
    ENV_VAR_PACKAGE_DIR,
    find_external_package_dir,
    get_package_dir,
    is_external_project,
)
from openapi_test_client.clients import OpenAPIClient
from openapi_test_client.libraries.api import api_client_generator as generator
from openapi_test_client.libraries.common.misc import get_module_name_by_file_path

if TYPE_CHECKING:
    from openapi_test_client.libraries.api.api_classes.base import APIBase

logger = get_logger(__name__)


API_CLIENTS_DIR = get_package_dir() / "clients"
EXISTING_CLIENT_NAMES = [x.name for x in API_CLIENTS_DIR.iterdir() if x.is_dir() and not x.name.startswith("__")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True, help="Action to take")
    subparser_generate = subparsers.add_parser("generate", help="Generate a new API client from an OpenAPI spec URL")
    subparser_update = subparsers.add_parser("update", help="Update an existing API client")
    _parse_generate_args(subparser_generate)
    _parse_update_args(subparser_update)
    return parser.parse_args()


def _parse_generate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-e",
        "--env",
        dest="env",
        default=DEFAULT_ENV,
        help="Target environment",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Just show code for API client, API classes, and models to be generated (Code will not be actually added)",
    )
    parser.add_argument(
        "-u",
        "--url",
        dest="url",
        required=True,
        help="URL to the OpenAPI spec file (must be JSON or YAML) to generate the API client with",
    )
    parser.add_argument(
        "-a",
        "--app",
        dest="app_name",
        required=True,
        help="The app name associated with the API client",
    )
    parser.add_argument(
        "--dir",
        dest="external_dir",
        metavar="DIRECTORY",
        default=None,
        required=is_external_project(),
        help="A directory path to generate client code and modules to. This is optional if your project was cloned "
        "from the original repo",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Do not show generated code on the console",
    )


def _parse_update_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env",
        dest="env",
        default="dev",
        help="Target env",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Just run the check and show diff (Code will not actually be updated)",
    )
    parser.add_argument(
        "-c",
        "--client",
        dest="client_app_name",
        metavar="CLIENT_NAME",
        choices=EXISTING_CLIENT_NAMES,
        required=True,
        help="Our API client app name",
    )
    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        "-t",
        "--tag",
        dest="tag",
        metavar="TAG",
        default=None,
        help="Limit the scope of update to the specific API tag. If the tag is not associated with any of existing API "
        "classes, a new API class will be dynamically created for the tag. Otherwise the existing API class functions "
        "will be updated",
    )
    filter_group.add_argument(
        "-e",
        "--endpoint",
        dest="endpoints",
        metavar="ENDPOINT",
        nargs="*",
        help='Target specific endpoint(s) to update. The format of each endpoint should be "<METHOD> <path>"',
    )
    filter_group.add_argument(
        "-a",
        "--api-class",
        dest="api_classes",
        metavar="API_CLASS_NAME",
        nargs="*",
        help="Limit the scope of update to the specific API class name(s)",
    )
    filter_group.add_argument(
        "-f",
        "--api-function",
        dest="api_functions",
        metavar="API_FUNC_NAME",
        nargs="*",
        help="Limit the scope of update to the specific API function name(s)",
    )
    filter_group.add_argument(
        "-A",
        "--add-api-class",
        dest="add_api_classes",
        action="store_true",
        default=False,
        help="Add API class files for API tags that don't currently have an associated API class",
    )
    parser.add_argument(
        "-m",
        "--model-only",
        dest="update_param_models_only",
        action="store_true",
        default=False,
        help="Update param models only. API class files will not be touched",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        dest="endpoints_to_ignore",
        nargs="*",
        help='Endpoint(s) to ignore. The format of each endpoint should be "<METHOD> <path>"',
    )
    parser.add_argument(
        "-I",
        "--ignore-undefined-endpoints",
        dest="ignore_undefined_endpoints",
        action="store_true",
        default=False,
        help="Update existing endpoints only. Undefined/missing endpoints won't be automatically added",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Do not show diff on the console",
    )


def generate_client(args: argparse.Namespace) -> None:
    """Generate a new API client from OpenAPI spec URL"""
    matched = re.match(r"(https?://[^/]+)/(.+)", args.url)
    if not matched:
        raise ValueError(f"Invalid OpenAPI spec URL: {args.url} ")

    base_url, doc_path = matched.groups()
    external_dir = None
    if args.external_dir:
        external_dir = Path(args.external_dir).resolve()
        if external_dir.name in ["test", _PACKAGE_DIR.name]:
            raise ValueError(f"The specified directory name '{external_dir.name}' is reserved. Please change the name")

        if external_dir.is_relative_to(_PROJECT_ROOT_DIR):
            raise ValueError(f"Specified external directory must be outside of {_PROJECT_ROOT_DIR}")
        elif external_dir.exists() and not external_dir.is_dir():
            raise ValueError(f"{external_dir} is not a directory")
        elif external_dir.parent.exists():
            if (
                existing_package_dir := find_external_package_dir(external_dir.parent, missing_ok=True)
            ) and existing_package_dir != external_dir:
                raise ValueError(
                    f"Detected the existing client setup in {existing_package_dir}. Please delete it first."
                )
        else:
            external_dir.mkdir(parents=True, exist_ok=True)

    if external_dir:
        os.environ[ENV_VAR_PACKAGE_DIR] = str(external_dir)
        sys.path.append(str(external_dir.parent))

    app_name = clean_obj_name(args.app_name).lower()
    if (client_dir := generator.get_client_dir(app_name)).exists():
        raise RuntimeError(f"API Client for '{app_name}' already exists in {client_dir}")

    if external_dir:
        logger.warning(f"Generating client in the external location: {client_dir}")
        generator.setup_external_directory(app_name, base_url, env=args.env)

    tmp_api_client = OpenAPIClient(app_name, rest_client=RestClient(base_url=base_url), doc=doc_path)
    api_spec = tmp_api_client.api_spec.get_api_spec()
    if not api_spec:
        raise RuntimeError(f"Failed to fetch API spec from {args.url}")

    # Generate API classes and models from the OpenAPI specs
    documented_tags = [x["name"] for x in api_spec["tags"] if x["name"]]
    failed_results = []
    for tag in documented_tags:
        result = generator.generate_api_class(
            tmp_api_client, tag, dry_run=args.dry_run, show_generated_code=not args.quiet
        )
        if isinstance(result, tuple):
            failed_results.append(result)

    if not args.dry_run:
        # Generate API client with the generated API classes
        generator.generate_api_client(tmp_api_client, show_generated_code=not args.quiet)

    if failed_results:
        _log_errors(args.action, failed_results)
    elif not args.dry_run:
        # Instantiate the generated client to make sure no error is thrown
        success_msg = f"API client for {app_name} has been successfully generated!"
        try:
            OpenAPIClient.get_client(app_name, env=args.env)
        except NotImplementedError as e:
            if not external_dir:
                # This is the expected result if --dir is not given as we don't automatically update urls.json.
                # Base URL for this client needs to be manually added.
                logger.info(success_msg)
                logger.warning(e)
            else:
                raise
        else:
            logger.info(success_msg)


def update_client(args: argparse.Namespace) -> None:
    """Update an existing API client based on the current OpenAPI spec"""
    api_client = OpenAPIClient.get_client(args.client_app_name, env=args.env)
    api_classes = _get_api_classes(args.client_app_name)
    api_spec = api_client.api_spec.get_api_spec()
    assert api_spec

    api_tags_undefined: list[str] = []
    all_documented_tags = [x["name"] for x in api_spec["tags"] if x["name"] and not x["name"].startswith("_")]
    all_defined_tags: list[str] = list(chain.from_iterable([x.TAGs for x in api_classes]))  # type: ignore[arg-type]
    update_required = []
    failed_results: list[tuple[str, Exception]] = []

    done = False
    if args.tag:
        if args.tag not in all_documented_tags:
            raise RuntimeError(
                f"Unable find the specified TAGs '{args.tag}' in the documented TAGs:\n"
                f"{list_items(sorted(all_documented_tags))}"
            )
        elif args.tag not in all_defined_tags:
            # Generate a new API class file for this tag
            generate_result = generator.generate_api_class(
                api_client,
                args.tag,
                add_endpoint_functions=not args.ignore_undefined_endpoints,
                dry_run=args.dry_run,
            )
            if isinstance(generate_result, tuple):
                failed_results.append(generate_result)
            done = True

    if not done:
        for cls in api_classes:
            if not args.tag or args.tag in cls.TAGs:
                update_result = generator.update_endpoint_functions(
                    cls,
                    api_spec,
                    dry_run=args.dry_run,
                    target_endpoints=args.endpoints,
                    endpoints_to_ignore=args.endpoints_to_ignore,
                    add_missing_endpoints=not args.ignore_undefined_endpoints,
                    update_param_models_only=args.update_param_models_only,
                    verbose=False,
                )
                if update_result is True:
                    update_required.append(cls)
                elif isinstance(update_result, tuple):
                    failed_results.append(update_result)

        if not args.tag:
            defined_tags = [  # type: ignore[var-annotated]
                x.strip()
                for x in chain(*[x.TAGs for x in api_classes if not isinstance(x.TAGs, property)])  # type: ignore[arg-type]
            ]
            undefined_tags = set(all_documented_tags).difference(set(defined_tags))
            if undefined_tags:
                api_tags_undefined.extend(undefined_tags)

        if api_tags_undefined and not any([args.tag, args.endpoints, args.api_classes, args.api_functions]):
            if args.add_api_classes:
                for tag in api_tags_undefined:
                    generator.generate_api_class(
                        api_client,
                        tag,
                        add_endpoint_functions=not args.ignore_undefined_endpoints,
                        dry_run=args.dry_run,
                    )
            else:
                logger.warning(
                    f"API class(es) need to be added for the following TAG(s):\n{list_items(api_tags_undefined)}"
                )

        print()  # noqa: T201
        if args.dry_run and update_required:
            logger.warning(
                f"The following API class(es) have one or more API functions that need to be updated\n"
                f"{list_items([x.__name__ for x in update_required])}"
            )

        if failed_results:
            _log_errors(args.action, failed_results)


def _get_api_classes(app: str) -> list[type[APIBase]]:
    mod = importlib.import_module(
        f"{get_module_name_by_file_path(API_CLIENTS_DIR)}.{app}.{generator.API_CLASS_DIR_NAME}"
    )
    return mod.API_CLASSES


def _log_errors(action: str, failed_results: list[tuple[str, Exception]]) -> None:
    error_details = []
    for failed_result in failed_results:
        api_class_name, e = failed_result
        tb = e.__traceback__
        while tb.tb_next:
            tb = tb.tb_next
        error_details.append(
            f"API class: {api_class_name}\n"
            f"File: {tb.tb_frame.f_code.co_filename} (lineno={tb.tb_lineno})\n"
            f"Error: {type(e).__name__}: {e}"
        )
    err = f"Failed to {action} code for the following API class(es). Please fix the issue and rerun the script."
    logger.error(err + "\n" + list_items(error_details))
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise Exception(f"{err}\n{list_items(error_details)}")


def main() -> None:
    args = parse_args()
    if args.action == "generate":
        generate_client(args)
    else:
        update_client(args)


if __name__ == "__main__":
    main()
