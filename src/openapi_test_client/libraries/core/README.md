API Client Core — General-Purpose API Client Framework
=================================================

This directory contains the core framework for building Python API clients. It provides decorator-driven endpoint 
declaration, request lifecycle hooks, sync/async dual-mode support, and runtime capabilities such as automatic retry, concurrency, streaming, and locking.

The framework uses the `httpx`-based REST API client from [common-libs](https://github.com/yugokato/common-libs/tree/main/src/common_libs/clients/rest_client) for underlying HTTP request handling.


# Table of Contents

- [Design Goals](#design-goals)
- [Quick Start](#quick-start)
- [Try it out](#try-it-out)
- [Core Concepts](#core-concepts)
  - [Endpoint Factory (`endpoint`)](#endpoint-factory-endpoint)
  - [Endpoint Functions (`EndpointFunc`)](#endpoint-functions-endpointfunc)
  - [API Client (`APIClient`)](#api-client-apiclient)
  - [API Class (`APIBase`)](#api-class-apibase)
  - [Endpoint Object (`Endpoint`)](#endpoint-object-endpoint)
  - [Auto-Discovery (`APIBase.init()`)](#auto-discovery-apibaseinit)
  - [API Statistics](#api-statistics)
- [Type and Response Reference](#type-and-response-reference)
- [Extending Core](#extending-core)


# Design Goals

- **Decorator-driven endpoint declaration** — annotate a plain method with `@endpoint.<method>("/path")` and the framework handles the rest.
- **Sync/async dual-mode** from the same source code — one endpoint definition works with both `sync` and `async` callers.
- **Batteries included** for common needs: automatic retry, distributed locking, concurrent execution, streaming responses, and API call Stats.
- **Extensible** via request/response hooks and decorators.


# Quick Start

Define an API endpoint by annotating a class method with `@endpoint.<method>("/path")`:

```python
from openapi_test_client.libraries.core import endpoint


class UsersAPI(MyAppBaseAPI):
    """User APIs"""
    @endpoint.get("/users/{user_id}")
    def get_user(self, user_id: int, include_posts: bool = False) -> RestResponse:
        """Get a user by ID"""
        ...
```

Call it like a regular Python method. The framework automatically builds and sends the HTTP request using the provided arguments and returns a `RestResponse`:

```pycon
>>> r = client.Users.get_user(user_id=42, include_posts=True)
>>> print(r.response)
{'id': 42, 'name': 'Jane Doe', 'email': 'jane@example.com', 'posts': [{'id': 1, 'title': 'Hello World'}, {'id': 2, 'title': 'API Design Notes'}]}
```


# Try it out

The following illustrative example shows how to build a minimal API client using the `core` library. The example
assumes a fictional "my-app" service at `https://api.example.com`.

### 1. Define a base API class for your service

Define an app-level base class with an `app_name`, optionally with shared request/response hooks and request wrappers:

```python
# myproject/clients/my_app/api/base/my_app_api.py

from openapi_test_client.libraries.core import APIBase


class MyAppBaseAPI(APIBase):
    """Base class for my-app API classes"""

    app_name = "my-app"
```

### 2. Define each API class and its endpoints

Define each concrete API class inheriting from that base, and add endpoint functions using the 
`@endpoint.<method>("/path")` endpoint factory decorator. Function parameters are automatically mapped to path, query, 
or request body fields.

<details open>
<summary><code>auth.py</code></summary>

```python
# myproject/clients/my_app/api/auth.py

from typing import Annotated, Unpack

from openapi_test_client.libraries.core import endpoint
from openapi_test_client.libraries.core.types import RestResponse, Kwargs, Query, Unset

from .base.my_app_api import MyAppBaseAPI


class AuthAPI(MyAppBaseAPI):
    """Auth APIs"""

    @endpoint.is_public
    @endpoint.post("/auth/login")
    def login(self, username: str, password: str, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Log in"""
        ...

    @endpoint.post("/auth/logout")
    def logout(self, redirect_to: Annotated[str, Query()] = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Log out"""
        ...

    @endpoint.is_public
    @endpoint.post("/auth/sessions/{session_id}/refresh")
    def refresh_session(
        self, session_id: str, refresh_token: str, expires_in: int = 3600, scopes: list[str] = Unset
    ) -> RestResponse:
        """Refresh an existing session"""
        ...
```

</details>

<details>
<summary><code>users.py</code></summary>

```python
# myproject/clients/my_app/api/users.py

from typing import Unpack

from openapi_test_client.libraries.core import endpoint
from openapi_test_client.libraries.core.types import RestResponse, Kwargs, Unset

from .base.my_app_api import MyAppBaseAPI


class UsersAPI(MyAppBaseAPI):
    """User APIs"""

    @endpoint.post("/users")
    def create_user(self, username: str, email: str, role: str = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Create a user"""
        ...

    @endpoint.get("/users/{user_id}")
    def get_user(self, user_id: int, include_posts: bool = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Get a user by ID"""
        ...

    @endpoint.get("/users")
    def list_users(self, page: int = Unset, page_size: int = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """List users"""
        ...
```

</details>

> [!NOTE]
>- For most cases, the function body should be empty (`...`, `pass`, etc.). The framework automatically
>handles the HTTP request using the provided parameters.
> - Use the `Unset` sentinel instead of `None` as the default value when a parameter should be omitted from the request
> payload unless explicitly set. `None` means the parameter will be included in the payload with a `null` value.
> - `**kwargs` takes framework-level request control options and raw `httpx` options.

### 3. Define the API client

Define the API client for your application, and attach the API classes you created using `@cached_property`.

```python
# myproject/clients/my_app/my_app_client.py

from functools import cached_property
from typing import Any

from openapi_test_client.libraries.core import APIClient

from .api.auth import AuthAPI
from .api.users import UsersAPI


class MyAppAPIClient(APIClient):
    """API client for the my-app service"""

    def __init__(self, *, base_url: str = "https://api.example.com", async_mode: bool = False, **kwargs: Any) -> None:
        super().__init__("my-app", base_url=base_url, async_mode=async_mode, **kwargs)

    @cached_property
    def Auth(self) -> AuthAPI:
        return AuthAPI(self)

    @cached_property
    def Users(self) -> UsersAPI:
        return UsersAPI(self)
```

### 4. Use the client

```pycon
>>> from myproject.clients.my_app.my_app_client import MyAppAPIClient
>>> client = MyAppAPIClient()
>>> r = client.Auth.login(username="foo", password="bar")
2024-01-01T00:00:00.100-0800 - request: POST https://api.example.com/auth/login
2024-01-01T00:00:00.115-0800 - response: 200 (OK)
- request_id: a2b20acf-22d5-4131-ac0d-6796bf19d2af
- request: POST https://api.example.com/auth/login
- payload: {"username": "foo", "password": "***"}
- status_code: 200 (OK)
- response: {
    "token": "eyJ1c2VySWQiOjQyLCJyb2xlIjoiYWRtaW4ifQ.d8f3Kx91LmQa7P2v",
    "refresh_token": "rft_91LmQa7P2vXk82",
    "token_type": "Bearer",
    "expires_in": 3600
}
>>> r.status_code
200
>>> r.response
{'token': 'eyJ1c2VySWQiOjQyLCJyb2xlIjoiYWRtaW4ifQ.d8f3Kx91LmQa7P2v', 'refresh_token': 'rft_91LmQa7P2vXk82', 'token_type': 'Bearer', 'expires_in': 3600}
```

> [!TIP]
> The recommended way to use a client is as a context manager, which ensures HTTP connections are cleaned up on exit:
> ```python
> # sync
> with MyAppAPIClient() as client:
>     r = client.Auth.login(username="foo", password="bar")
>
> # async
> async with MyAppAPIClient(async_mode=True) as client:
>     r = await client.Auth.logout()
> ```


---


# Core Concepts

## Endpoint Factory (`endpoint`)

The `endpoint` class is a factory providing decorators that convert a plain API class method into a fully managed endpoint function.

### HTTP-method decorators

`endpoint` provides one decorator per HTTP verb (`get`, `post`, `put`, `patch`, `delete`, `options`, `head`, `trace`), each wiring the method to that verb and the given path:

- `@endpoint.get(path)` always sends parameters as a query string.
- All other verbs send parameters as the request body by default. Pass `use_query_string=True` to route every parameter to the query string, or annotate individual params with [`Query`](#query) to target specific ones.

All HTTP-method decorators also accept `**default_raw_options`, forwarded to the underlying HTTP library (`httpx`) for every call to that endpoint (e.g., `timeout=30`).

### Metadata decorators

| Decorator                       | Applies to           | Description                                                               |
|---------------------------------|----------------------|---------------------------------------------------------------------------|
| `@endpoint.is_public`           | function             | Marks the endpoint as not requiring authentication (`is_public=True`).    |
| `@endpoint.is_deprecated`       | function or class    | Marks the endpoint (or all endpoints on a class) as deprecated.           |
| `@endpoint.undocumented`        | function or class    | Marks the endpoint as not part of the documented public API.              |
| `@endpoint.content_type("...")` | function             | Explicitly sets the `Content-Type` header for this endpoint.              |
| `@endpoint.decorator`           | decorator definition | Registers a user-written decorator so it can be applied to API functions. |

### Stacking decorators

Metadata decorators can appear anywhere in the stack — above or below `@endpoint.<method>("/path")`. The framework resolves them in the right order at class-definition time:

```python
@my_decorator   # Your custom decorator — must be registered
@endpoint.is_deprecated
@endpoint.get("/v1/items")
def list_items(self, *, page: int = Unset, page_size: int = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
    """List items (deprecated)"""
    ...
```

## Endpoint Functions (`EndpointFunc`)

This is the heart of the framework. When you decorate a method with the `@endpoint.<method>("/path")` endpoint factory decorator, two things happen:

1. **At class-definition time** — the decorator replaces the method on the class with an `EndpointHandler` descriptor.
2. **At runtime access** — the `EndpointHandler` descriptor returns a dynamically created (and cached) `EndpointFunc` instance, making the method a fully managed endpoint function.

```pycon
# instance-level access
>>> client.Auth.login
<openapi_test_client.libraries.core.endpoints.endpoint_func.AuthAPILoginEndpointFunc object at 0x10f5abcd0>
(mapped to: <function AuthAPI.login at 0x10f4d1360>)

# class-level access
>>> AuthAPI.login
<openapi_test_client.libraries.core.endpoints.endpoint_func.AuthAPILoginEndpointFunc object at 0x10f3c2ab0>
(mapped to: <function AuthAPI.login at 0x10f4d1360>)
```

### Calling an endpoint function

Call an endpoint function like a regular method to make an API request. The framework handles
payload generation and the HTTP call for you, then returns the response as a [`RestResponse`](#restresponse) object:

```python
r = client.Auth.login(username="foo", password="bar")
```

Beyond the endpoint's own parameters, the function also accepts framework-level control options and `httpx` raw 
options as `kwargs`. See [`Kwargs`](#kwargs-and-unpack).

**Streaming**

Use `stream()` instead of a direct call to open a streaming response. It supports the same pre/post hooks and wrappers as a regular call:

```python
# sync
with client.Events.subscribe.stream(topic="updates") as r:
    for chunk in r.stream():
        print(chunk)

# async
async with client.Events.subscribe.stream(topic="updates") as r:
    async for chunk in r.astream():
        print(chunk)
```


### Function parameter signatures

The framework classifies each parameter by name, not by position in the signature:

- **Path parameters** — any parameter whose name matches a `{placeholder}` token in the endpoint path. The framework substitutes it into the URL.
- **Body/query parameters** — every other parameter.

Both kinds can be defined as required (no default) or optional (with a default value). There is no restriction on where they appear in the signature.

```python
@endpoint.get('/v1/users/{user_id}/orders/{order_id}')
def get_order(self, user_id: int, order_id: int, include_items: bool = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
    #               ^^^^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #               path params (name matches    body/query param (any other name)
    #               placeholder in path)
    ...
```

For path placeholders that are not valid Python identifiers (e.g. `{order-id}`), name the parameter using underscores instead of hyphens — the framework maps them back to the original placeholder:

```python
@endpoint.get("/v1/users/{user_id}/orders/{order-id}")
def get_order(self, user_id: int, order_id: int, **kwargs: Unpack[Kwargs]) -> RestResponse:
    #                             order_id  ↑ matches {order-id}
    ...
```

### `Unset` and default values

`Unset` is a sentinel default value for optional parameters. A parameter whose value is `Unset` is
**excluded from the request entirely**, unlike `None`, which is still sent to the server — as `null`
in the request body, or as an empty value in the query string.

```python
r = client.Auth.logout()                              # query string: N/A
r = client.Auth.logout(redirect_to=None)              # query string: ?redirect_to=
r = client.Auth.logout(redirect_to="/dashboard")      # query string: ?redirect_to=/dashboard
```

Concrete (non-`Unset`) default values are always included in the request when the caller omits the argument. Use `Unset` when a parameter should be absent unless explicitly provided:

```python
# page always defaults to 1 if not given; per_page is omitted unless the caller sets it
@endpoint.get("/v1/items")
def list_items(self, *, page: int = 1, per_page: int = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse: ...

r = client.Items.list_items()                     # payload: {"page": 1} 
r = client.Items.list_items(page=2)               # payload: {"page": 2} 
r = client.Items.list_items(per_page=50)          # payload: {"page": 1, "per_page": 50} 
r = client.Items.list_items(page=2, per_page=50)  # payload: {"page": 2, "per_page": 50}
```

### Configurable execution wrappers

In addition to `__call__`, every endpoint function provides the following configurable execution wrappers:

| Method                                                                                                     | Description                                                                                                                                                                                                                                                                  |
|------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `with_retry(condition=lambda r: not r.ok, num_retries=1, retry_after=5, safe_methods_only=False)` → `Self` | Configure retry and return a chainable endpoint func. `condition` can be a status code or exception class, a list of status codes or exception classes, a callable `(RestResponse \| Exception) -> bool`). Defaults to retrying on any non-2xx response.                     |
| `with_lock(lock_name=None)` → `Self`                                                                       | Configure a distributed lock and return a chainable endpoint func. Default lock name is `<app_name>-<APIClass>.<func_name>`.                                                                                                                                                 |
| `with_expected_status(*status_codes)` → `Self`                                                             | Assert the response status code is one of the expected values. Raises `AssertionError` otherwise.                                                                                                                                                                            |
| `with_max_response_time(threshold_msecs)` → `Self`                                                         | Assert the server response time does not exceed `threshold_msecs`. Raises `AssertionError` otherwise.                                                                                                                                                                        |
| `with_polling(until, interval=5, timeout=60)` → `Self`                                                     | Poll the endpoint until `until(response)` returns `True`, waiting `interval` seconds between calls. Raises `TimeoutError` if not satisfied within `timeout` seconds.                                                                                                         |
| `with_concurrency(num=2, *, return_exceptions=False)` → `Callable[..., list[RestResponse]]`                | Configure concurrency and return a callable. Pass the endpoint's own parameters to that callable — it fires `num` concurrent calls and returns `list[RestResponse]`. Set `return_exceptions=True` to collect exceptions in the list instead of propagating.                  |
| `with_repeat(num=2, *, return_exceptions=False)` → `Callable[..., list[RestResponse]]`                     | Configure sequential repetition and return a callable. Pass the endpoint's own parameters — it fires `num` sequential calls and returns `list[RestResponse]`. Set `return_exceptions=True` to collect exceptions (`list[RestResponse \| Exception]`) instead of propagating. |

> [!IMPORTANT]
> - All `with_xxx()` wrappers use a **curried** call style: each wrapper accepts only its own configuration options
> and returns a configured callable. Pass the endpoint's own parameters to that returned callable.
> - `with_retry`, `with_lock`, `with_expected_status`, `with_max_response_time`, and `with_polling` return the
> concrete endpoint func (`Self`), so they can be **chained** before the final call. `with_concurrency` and
> `with_repeat` are terminal and must always be last.

**Examples:**

With retries:

```python
r = client.Auth.login.with_retry(condition=429, num_retries=3, retry_after=2)(username="foo", password="bar")
```


Chaining wrappers:

```python
# Apply a lock, retry on transient failures, and validate the status code
r = client.Auth.login.with_lock().with_retry(condition=429).with_expected_status(200)(username="foo", password="bar")
```


> [!TIP]
> Wrappers compose left-to-right — The first wrapper applied becomes the outermost layer, so the example above is 
> conceptually equivalent to:
> 
> ```python
> with lock():
>     with retry(condition=429):
>         r = client.Auth.login(username="foo", password="bar")
>         assert r.status_code == 200
> ```


## API Client (`APIClient`)

`APIClient` is the base class for all API clients. It owns the HTTP transport and determines whether endpoint calls run in sync or async mode.

```python
class APIClient:
    def __init__(
        self,
        app_name: str,
        /,
        *,
        env: str | None = None,
        base_url: str | None = None,
        rest_client: RestClient | AsyncRestClient | None = None,
        async_mode: bool = False,
        **kwargs: Any,
    ) -> None: ...
```

| Parameter     | Description                                                                                                                                                          |
|---------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `app_name`    | Logical name for the application. Must match `app_name` on all associated API classes.                                                                               |
| `env`         | Target environment label (e.g., `"dev"`, `"prod"`). Optional; accessible on API class instances via `self.env`.                                                      |
| `base_url`    | Base URL prepended to every endpoint path. Mutually exclusive with `rest_client`.                                                                                    |
| `rest_client` | Pre-configured `RestClient` or `AsyncRestClient` to inject. Use this when you need full control over transport-level settings (TLS, proxies, session cookies, etc.). |
| `async_mode`  | Set to `True` to enable async mode. All endpoint calls must then be awaited.                                                                                         |
| `**kwargs`    | Additional keyword arguments forwarded to the underlying REST client constructor (e.g., `headers`, `timeout`, `verify`).                                             |


## API Class (`APIBase`)

`APIBase` is the abstract base class for all API classes. In practice, you define two levels of subclass:

- An **app-level base class** (e.g., `MyAppBaseAPI`) — Define one per application. It sets `app_name`, declares shared
class attributes, and holds any hooks that inject extra logic to endpoints in that application.
- **Concrete API classes** (e.g., `AuthAPI`) — one per logical resource group.

```python
# App-level base — one per application
class MyAppBaseAPI(APIBase):
    app_name = "my-app"   # must match api_client.app_name


# Concrete API class — one per resource group
class AuthAPI(MyAppBaseAPI):

    @endpoint.post("/auth/login")
    def login(self, username: str, password: str, **kwargs: Unpack[Kwargs]) -> RestResponse:
        ...
```
It is generic over the client type — `APIBase[T]` — so subclasses get a typed `self.api_client`.

### Class attributes

| Attribute       | Type                     | Description                                                                                    |
|-----------------|--------------------------|------------------------------------------------------------------------------------------------|
| `app_name`      | `str \| None`            | Must match `api_client.app_name`. Validated at instantiation. Set on the app-level base class. |
| `is_documented` | `bool`                   | Marks every endpoint in the class as documented (default `True`).                              |
| `is_deprecated` | `bool`                   | Marks every endpoint in the class as deprecated (default `False`).                             |
| `endpoints`     | `list[Endpoint] \| None` | Populated by `APIBase.init()`. Lists all `Endpoint` objects for this class.                    |

The class-level `is_documented`/`is_deprecated` flags can also be controlled per-endpoint via the `endpoint` factory decorators (see [Endpoint Factory](#endpoint-factory-endpoint) above).

### Request hooks

Override these methods on your app-level base class to inject cross-cutting behavior shared across all API classes in that application.

#### `pre_request_hook`

Called immediately before each request is made.

```python
def pre_request_hook(self, endpoint: Endpoint, *path_params: Any, **params: Any) -> None: ...
```

#### `post_request_hook`

Called immediately after each request completes (or raises an HTTP error).

```python
def post_request_hook(
    self,
    endpoint: Endpoint,
    response: RestResponse | None,
    exception: HTTPError | None,
    *path_params: Any,
    **params: Any,
) -> None: ...
```

#### `request_wrapper`

Returns a list of callables that each wrap `EndpointFunc.__call__`. Each callable receives the `EndpointFunc` instance as its first positional argument. Useful for behavior that must see both the call and its result at the class level (e.g., activating a validation mode, adding timing).

```python
def request_wrapper(self) -> list[Callable[..., Any]]:
    return [my_wrapper]
```

> [!NOTE]
> If multiple wrappers are returned, they are applied in reverse order — the first element ends up as the outermost wrapper (processed first).

#### `stream_wrapper`

Analogous to `request_wrapper` but applied to `stream()` calls.

#### Execution order

When both decorators and hooks are configured, the full request lifecycle runs in this order:

1. Endpoint decorators applied with `@endpoint.decorator` (before-call)
2. `request_wrapper` callable (before-call)
3. `pre_request_hook`
4. Request (actual HTTP call)
5. `post_request_hook`
6. `request_wrapper` callable (after-call)
7. Endpoint decorators (after-call)

**Example — Automatically attach/detach a token after a successful login/logout:**

```python
from collections.abc import Callable
from typing import Any

from httpx import HTTPError

from openapi_test_client.libraries.core import APIBase, Endpoint
from openapi_test_client.libraries.core.types import RestResponse


class MyAppBaseAPI(APIBase):
    app_name = "my-app"

    def post_request_hook(
        self,
        endpoint: Endpoint,
        response: RestResponse | None,
        exception: HTTPError | None,
        *path_params: Any,
        **params: Any,
    ) -> None:
        super().post_request_hook(endpoint, response, exception, *path_params, **params)
        if response and response.ok:
            if endpoint == self.api_client.Auth.login.endpoint:
                self.api_client.rest_client.set_bearer_token(response.response["token"])
            elif endpoint == self.api_client.Auth.logout.endpoint:
                self.api_client.rest_client.unset_bearer_token()
```


## Endpoint Object (`Endpoint`)

`Endpoint` is a frozen dataclass holding all metadata for a single endpoint. It is attached to every endpoint function as `.endpoint` and to each API class via its `.endpoints` list.

| Field           | Type                  | Description                                                                    |
|-----------------|-----------------------|--------------------------------------------------------------------------------|
| `api_class`     | `type[APIBase]`       | The API class that owns this endpoint.                                         |
| `method`        | `str`                 | HTTP method in lowercase (e.g., `"get"`, `"post"`).                            |
| `path`          | `str`                 | Endpoint path (e.g., `"auth/login"`).                                          |
| `func_name`     | `str`                 | Name of the original API class function.                                       |
| `model`         | `type[EndpointModel]` | Dynamically generated model describing this endpoint's parameters.             |
| `url`           | `str \| None`         | Full URL; only set when accessed via a client instance (not via the class).    |
| `content_type`  | `str \| None`         | Explicitly set Content-Type, or `None` to auto-detect.                         |
| `is_public`     | `bool`                | `True` if the endpoint does not require authentication.                        |
| `is_documented` | `bool`                | `True` by default; `False` if the endpoint is marked `@endpoint.undocumented`. |
| `is_deprecated` | `bool`                | `True` if the endpoint was marked `@endpoint.is_deprecated`.                   |

`str(endpoint)` returns `"METHOD /path"` (e.g., `"POST /auth/login"`).

```pycon
>>> print(client.Auth.login.endpoint)
POST /auth/login
>>> pprint(client.Auth.login.endpoint)
Endpoint(api_class=<class 'myproject.clients.my_app.api.auth.AuthAPI'>,
         method='post',
         path='/auth/login',
         func_name='login',
         model=<class 'openapi_test_client.libraries.core.utils.endpoint_model.AuthAPILoginEndpointModel'>,
         url='https://api.example.com/auth/login',
         content_type=None,
         is_public=True,
         is_documented=True,
         is_deprecated=False)
```

`Endpoint` is also callable. This lets you dispatch a request directly from an endpoint object without going through the API class accessor:

```pycon
>>> endpoint = client.Auth.login.endpoint
>>> r = endpoint(client, username="foo", password="bar")   # equivalent to client.Auth.login(username="foo", password="bar")
```

### `EndpointModel`

Each `Endpoint` object carries a `model` field that holds a dynamically generated frozen dataclass class `EndpointModel` for that endpoint.

```pycon
>>> model = client.Auth.login.endpoint.model
>>> print(model)
<class 'openapi_test_client.libraries.core.utils.endpoint_model.AuthAPILoginEndpointModel'>
>>> pprint(model.__dataclass_fields__, sort_dicts=False)
{'username': Field(name='username',type=<class 'str'>,default=Unset,default_factory=<dataclasses._MISSING_TYPE object at 0x1049bc440>,init=True,repr=True,hash=None,compare=True,metadata=mappingproxy({}),kw_only=True,doc=None,_field_type=_FIELD),
 'password': Field(name='password',type=<class 'str'>,default=Unset,default_factory=<dataclasses._MISSING_TYPE object at 0x1049bc440>,init=True,repr=True,hash=None,compare=True,metadata=mappingproxy({}),kw_only=True,doc=None,_field_type=_FIELD)}
```


## Auto-Discovery (`APIBase.init()`)

Call `<YourBaseClass>.init()` from the `__init__.py` of your API class directory. It walks all `.py` files in that directory, discovers every subclass of the base, and populates each class's `.endpoints` list.

```python
# myproject/clients/my_app/api/__init__.py

from .base import MyAppBaseAPI  # your concrete APIBase subclass

API_CLASSES = MyAppBaseAPI.init()
```

After this runs, `API_CLASSES` is a `list[type[APIBase]]` — one entry per discovered API class:

```pycon
>>> from myproject.clients.my_app.api import API_CLASSES
>>> for cls in API_CLASSES:
...     for ep in cls.endpoints:
...         # ep is an Endpoint object
...         print(ep)
...
POST /auth/login
POST /auth/logout
POST /auth/sessions/{session_id}/refresh
GET /users
GET /users/{user_id}
POST /users
```

> [!NOTE]
> `APIBase.init()` must be called from an `__init__.py` file. Calling it from any other module raises a `RuntimeError`.


## API Statistics

The framework automatically records per-endpoint metrics including call counts, status-code distributions (`1xx`–`5xx`),
errors, response times (`min` / `avg` / `max`), and estimated latency percentiles (`p50` / `p95` / `p99`) using DDSketch
(≤1% relative error). Calls made via `stream()` are not included.

### View statistics

Call `Stats.show()` to display a formatted summary of recorded endpoint activity:

```pycon
>>> from openapi_test_client.libraries.core.endpoints import Stats
>>> client.Auth.login.with_concurrency(num=10)(username="foo", password="bar")
>>> client.Users.get_user(user_id=42)
>>> Stats.show()
                                                                                   Latency (ms)             
                                                                    ----------------------------------------
Endpoint             | Calls | 1xx | 2xx | 3xx | 4xx | 5xx | Error | min  | avg  | max  | p50  | p95  | p99 
---------------------+-------+-----+-----+-----+-----+-----+-------+------+------+------+------+------+-----
POST /auth/login     |    10 |   0 |  10 |   0 |   0 |   0 |     0 | 3.21 | 4.80 | 6.57 | 4.30 | 6.54 | 6.54
GET /users/{user_id} |     1 |   0 |   1 |   0 |   0 |   0 |     0 | 0.68 | 0.68 | 0.68 | 0.68 | 0.68 | 0.68
```

Pass `sort_by` to sort results by `"calls"` (default), `"slowest"`, `"errors"`, or `"endpoint"`. Pass `reverse=False` 
to sort ascending instead of descending.

### Programmatic access

Use `Stats.get()` to retrieve a single endpoint's stat record, or `Stats.all()` to get a snapshot list of all
recorded stats. Both return independent copies, so reading them concurrently with ongoing calls is safe.

```python
stat = Stats.get("POST /auth/login")
assert stat.num_2xx == 2
```

`Stats.dump(path)` serializes the global collector to an indented JSON file (complementing `aggregate()`, which
file-locks and merges rather than overwrites):

```python
Stats.dump("run_stats.json")
```

### Scoped collection

Use `Stats.collect()` context manager to measure metrics inside a specific block of code. Calls made inside count
toward **both** the yielded scoped collector and the global total:

```python
with Stats.collect("login-flow") as stats:
    r = client.Auth.login(username="foo", password="bar")

stats.show()  # only the calls inside the `with` block
Stats.show()  # all calls ever made
```

Scopes can be nested: an inner `collect()` block sees only its own calls, while the outer scope accumulates both.

### Cross-process aggregation

`Stats.aggregate(path)` merges the current process's snapshot into a shared JSON file using a file lock, making
it safe for parallel workers to accumulate into one place.

### Reset statistics

Call `Stats.reset()` to clear all recorded stats.

### Collection control

Set `API_CLIENT_STATS_DISABLED` to `1` or `true` before import to disable collection process-wide, or call 
`Stats.disable()` at runtime. Call `Stats.enable()` to re-enable it. Existing data is retained in both cases. Call 
`Stats.reset()` to clear it.

---

# Type and Response Reference

## `RestResponse`

The object returned by every endpoint call. Key attributes:

| Attribute       | Type             | Description                                                                                                 |
|-----------------|------------------|-------------------------------------------------------------------------------------------------------------|
| `status_code`   | `int`            | HTTP status code.                                                                                           |
| `response`      | `JSONType`       | Decoded response body (dict, list, str, or `None`).                                                         |
| `ok`            | `bool`           | `True` if `200 <= status_code < 300`.                                                                       |
| `request`       | `Request`        | The underlying `httpx` request object, extended with `request_id`, `start_time`, `end_time`, and `retried`. |
| `_response`     | `httpx.Response` | Raw `httpx` response; needed for streaming or low-level access.                                             |
| `is_stream`     | `bool`           | `True` if this is a streaming response.                                                                     |
| `request_id`    | `str`            | UUID set per request in the `X-Request-ID` header.                                                          |
| `response_time` | `float`          | Wall-clock seconds between request dispatch and response received.                                          |

## `Kwargs` and `Unpack`

`Kwargs` is a `TypedDict` that captures the three built-in keyword options accepted by every endpoint function:

```python
class Kwargs(TypedDict, total=False):
    quiet: bool                 # suppress request/response log output
    with_hooks: bool            # set to False to skip pre/post hooks
    raw_options: dict[str, Any] # raw httpx client options (timeout, headers, ...)
```

Always include `**kwargs: Unpack[Kwargs]` in your endpoint function signatures so callers can use these options without triggering an "unexpected keyword argument" error:

```python
from typing import Unpack
from openapi_test_client.libraries.core.types import Kwargs, RestResponse

@endpoint.get("/v1/items")
def list_items(self, *, page: int = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
    ...
```

## `Query`

Use `Query` inside `Annotated` to send an individual parameter as a URL query string on non-GET endpoints. By
default, non-GET endpoints place parameters in the request body; `Query` overrides this on a per-parameter basis.

Three equivalent forms are accepted:

| Form                                         | Example                                 |
|----------------------------------------------|-----------------------------------------|
| `Query()` — canonical instance (recommended) | `mode: Annotated[str, Query()] = Unset` |
| `Query` — bare class (no parentheses)        | `mode: Annotated[str, Query] = Unset`   |
| `"query"` — legacy string (back-compat only) | `mode: Annotated[str, "query"] = Unset` |

```python
from typing import Annotated, Unpack
from openapi_test_client.libraries.core.types import Kwargs, Query, RestResponse, Unset

@endpoint.post("/v1/items/{item_id}")
def update_item(
    self,
    item_id: int,
    *,
    payload: str = Unset,
    mode: Annotated[str, Query()] = Unset,   # sent as ?mode=<value> in the URL
    **kwargs: Unpack[Kwargs],
) -> RestResponse:
    ...
```

`Query` is a per-parameter override. It is complementary to the endpoint-level `use_query_string=True` flag (which
routes *every* parameter to the query string), and has no effect on `@endpoint.get(...)` endpoints (all GET
parameters already go to the query string).

## `File`

Use `File` to upload files via `multipart/form-data`. Pass each file as a separate named parameter:

```python
from openapi_test_client.libraries.core.types import File

r = client.Users.upload_documents(
    avatar=File("avatar.png", b"<png bytes>", "image/png"),
    resume=File("resume.pdf", b"<pdf bytes>", "application/pdf"),
)
```

## `Alias`

Use `Alias` inside `Annotated` when the API requires a parameter key name that is not a valid Python identifier (e.g., it contains hyphens or collides with a keyword):

```python
from typing import Annotated, Unpack
from openapi_test_client.libraries.core.types import Alias, RestResponse, Kwargs, Unset

@endpoint.post("/v1/items")
def create_item(
    self,
    *,
    content_type: Annotated[str, Alias("Content-Type")] = Unset,
    **kwargs: Unpack[Kwargs],
) -> RestResponse:
    ...
```

The framework sends `"Content-Type"` as the actual key in the request payload while the Python parameter is named `content_type`.

---

# Extending Core

## Implement custom function logic

By default, an API function body should be just a stub (`...`), and the framework auto-generates the HTTP request from 
the parameters passed by the caller. In most cases you won't need to touch the body:

```python
@endpoint.post("/auth/login")
def login(self, username: str, password: str, **kwargs: Unpack[Kwargs]) -> RestResponse:
    """Log in"""
    ...
```

If a specific endpoint needs custom request logic, replace the stub with your own code. The body
must return a `RestResponse` (the object the underlying REST client returns); returning `None` (or
leaving the stub) falls back to the auto-generated request.

> [!NOTE]
> Returning anything other than a `RestResponse` or `None` from a custom function body raises a
> `RuntimeError`.

> [!TIP]
> If you only need to add behavior before or after the request, use a
> [registered decorator](#add-a-custom-registered-decorator) or [request hooks](#request-hooks) instead.


## Add a custom registered decorator

Create a decorator, register it with `@endpoint.decorator`, and apply it on an API function:

```python
from collections.abc import Callable
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar

from openapi_test_client.libraries.core import APIBase, endpoint
from openapi_test_client.libraries.core.types import RestResponse

P = ParamSpec("P")
R = TypeVar("R", bound=RestResponse)


@endpoint.decorator
def no_prod(f: Callable[Concatenate[APIBase, P], R]) -> Callable[Concatenate[APIBase, P], R]:
    """Raise if called against a production environment."""

    @wraps(f)
    def wrapper(self: APIBase, *args: P.args, **kwargs: P.kwargs) -> R:
        if self.env == "prod":
            raise RuntimeError(f"{f.__name__!r} must not be called against production")
        return f(self, *args, **kwargs)

    return wrapper
```

**Decorator with arguments:**

```python
import warnings
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from openapi_test_client.libraries.core import endpoint
from openapi_test_client.libraries.core.types import RestResponse

P = ParamSpec("P")
R = TypeVar("R", bound=RestResponse)


@endpoint.decorator
def warn_if_slow(threshold_ms: float) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Emit a warning when the response time exceeds the given threshold (ms)."""

    def decorator(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            r = f(*args, **kwargs)
            elapsed = r.response_time * 1000
            if elapsed > threshold_ms:
                warnings.warn(f"{r.request.method} {r.request.url} took {elapsed:.0f}ms (threshold: {threshold_ms}ms)")
            return r

        return wrapper

    return decorator
```

> [!TIP]
> Custom decorators can appear at any position relative to `@endpoint.<method>("/path")` — above or below it. The framework resolves the stack correctly either way.

## Override `request_wrapper` for class-level cross-cutting behavior

`request_wrapper` is the right place for class-level behavior that must wrap the core request 
lifecycle (pre/post hooks and the HTTP call). Note that endpoint decorators applied with `@endpoint.decorator` run 
*outside* the request wrapper — decorators are the outermost layer. Return a list of plain callables; each receives 
the `EndpointFunc` instance as its first argument:

```python
class MyAppBaseAPI(APIBase):
    app_name = "my-app"

    def request_wrapper(self) -> list[Callable[..., Any]]:
        return [timing_wrapper]
```

## Plug in custom `Endpoint` / `EndpointFunc` subclasses

`APIBase` exposes three class-level attributes that control which concrete classes are instantiated at runtime:

| Attribute                    | Default             | Purpose                                                                   |
|------------------------------|---------------------|---------------------------------------------------------------------------|
| `_endpoint_class`            | `Endpoint`          | The `Endpoint` dataclass subclass to use when building endpoint metadata. |
| `_sync_endpoint_func_class`  | `SyncEndpointFunc`  | The sync endpoint function subclass.                                      |
| `_async_endpoint_func_class` | `AsyncEndpointFunc` | The async endpoint function subclass.                                     |

Override any of them on your app-level base class to inject custom behavior into the endpoint lifecycle without modifying framework code:

```python
from openapi_test_client.libraries.core import APIBase
from openapi_test_client.libraries.core.endpoints.endpoint_func import SyncEndpointFunc, AsyncEndpointFunc


class MyEndpointFunc(SyncEndpointFunc):
    """Add a .docs() helper to every sync endpoint."""

    def docs(self) -> None:
        print(f"Endpoint: {self.endpoint}")


class MyAsyncEndpointFunc(AsyncEndpointFunc):
    """Async counterpart."""

    def docs(self) -> None:
        print(f"Endpoint: {self.endpoint}")


class MyAppBaseAPI(APIBase):
    app_name = "my-app"
    _sync_endpoint_func_class = MyEndpointFunc
    _async_endpoint_func_class = MyAsyncEndpointFunc
```
