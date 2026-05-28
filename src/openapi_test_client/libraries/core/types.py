from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from dataclasses import MISSING, Field, asdict, astuple, dataclass
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, TypeAlias, TypedDict

from common_libs.clients.rest_client import JSONType, RestResponse

if TYPE_CHECKING:
    from collections.abc import Generator
    from dataclasses import _MISSING_TYPE, _DataclassParams  # type: ignore
    from typing import Protocol

    from common_libs.clients.rest_client import RestResponse as _RestResponse

    from .endpoints import EndpointFunc

    class RestResponse(_RestResponse[JSONType]):  # type: ignore[no-redef]
        """TYPE_CHECKING-only type that is both RestResponse and awaitable.

        Enables IDE support for both sync and async (await) usage patterns:
        """

        def __await__(self) -> Generator[Any, None, _RestResponse]: ...
else:
    Protocol = object


__all__ = ["APIResponse", "Alias", "File", "Kwargs", "Query", "Unset"]


APIResponse: TypeAlias = RestResponse | Awaitable[RestResponse]


class _UnsetType:
    """Sentinel type for parameters that were not explicitly provided.

    Parameters with this value will not be included in the actual API call payload.
    """

    def __repr__(self) -> str:
        return "Unset"

    def __bool__(self) -> bool:
        return False


Unset: Any = _UnsetType()


class Kwargs(TypedDict, total=False):
    """For annotating the `kwargs` param in endpoint functions (PEP 692)"""

    quiet: bool
    with_hooks: bool
    raw_options: dict[str, Any]


class DataclassModel(Protocol):
    """Base class for endpoint/param models"""

    if TYPE_CHECKING:
        __dataclass_fields__: ClassVar[Mapping[str, Field[Any]]]
        __dataclass_params__: ClassVar[_DataclassParams]
        __post_init__: ClassVar[Callable[..., None]]


class DataclassModelField(NamedTuple):
    """Dataclass model field"""

    name: str
    type: Any
    default: Field[Any] | _MISSING_TYPE | object = MISSING


class EndpointModel(DataclassModel):
    """Protocol for endpoint parameter models"""

    content_type: str | None
    endpoint_func: EndpointFunc


@dataclass
class File(dict[str, Any], DataclassModel):
    """A file to pass to MultipartFormData class"""

    filename: str
    content: str | bytes
    content_type: str

    def __post_init__(self) -> None:
        super().__init__(asdict(self))

    def to_tuple(self) -> tuple[str, str | bytes, str]:
        return astuple(self)


class MultipartFormData(MutableMapping[str, Any]):
    """Multipart Form data

    >>> files = MultipartFormData(
    ...     logo=File("logo.png", b"content", "image/png"), favicon=File("favicon.png", b"content", "image/png")
    ... )
    >>> files.to_dict()
    {'logo': ('logo.png', b'content', 'image/png'), 'favicon': ('favicon.png', b'content', 'image/png')}

    NOTE: The File obj can be a dictionary instead
    """

    def __init__(self, **files: File | dict[str, str | bytes | Any]):
        self._files: dict[str, tuple[str, str | bytes, str]] = dict(
            {
                param_name: (file.to_tuple() if isinstance(file, File) else tuple(file.values()))
                for (param_name, file) in files.items()
                if file
            }
        )

    def __getattr__(self, name: str) -> tuple[str, str | bytes, str]:
        """Allow attribute-style read access to stored files (e.g. ``files.logo``).

        Only invoked when normal attribute lookup fails (i.e. for file keys, not for
        ``_files`` or methods).  Raises ``AttributeError`` for unknown names so that
        ``hasattr`` and ``getattr(..., default)`` behave correctly.

        :param name: File key to look up
        """
        if name == "_files":
            # Guard against infinite recursion during __init__ before _files is set
            raise AttributeError(name)
        try:
            return self._files[name]
        except KeyError:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}") from None

    def __getitem__(self, key: str) -> tuple[str, str | bytes, str]:
        return self._files[key]

    def __setitem__(self, key: str, value: File | dict[str, Any] | Any) -> None:
        if isinstance(value, File):
            self._files[key] = value.to_tuple()
        elif isinstance(value, dict):
            self._files[key] = tuple(value.values())
        else:
            self._files[key] = value

    def __delitem__(self, key: str) -> None:
        del self._files[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._files)

    def __len__(self) -> int:
        return len(self._files)

    def to_dict(self) -> dict[str, tuple[str, str | bytes, str] | Any]:
        return dict(self._files)


@dataclass(frozen=True, slots=True)
class ParamAnnotationType:
    """Base class for all custom classes used for annotating endpoint function parameters"""

    ...


@dataclass(frozen=True, slots=True)
class Alias(ParamAnnotationType):
    """Alias param name

    Use it as a metadata of typing.Annotated when a param model field name and actual param name need to be different
    (eg. Actual param name contains illegal characters for python variable names)
    """

    value: str


@dataclass(frozen=True, slots=True)
class Query(ParamAnnotationType):
    """Marker that forces a parameter to be sent as a URL query string for non-GET endpoints.

    Use as metadata of typing.Annotated. By default, body/query params on non-GET endpoints are
    sent in the request body; this marker overrides that on a per-parameter basis. Has no effect
    on GET endpoints, which already send all params as query strings.

    Both the class itself and an instance are accepted:
        mode: Annotated[str, Query()]  # canonical instance form
        mode: Annotated[str, Query]    # bare class form (ergonomic shortcut)
    """
