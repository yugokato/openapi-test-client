from collections.abc import MutableMapping
from typing import Any

from openapi_test_client.libraries.api.types import File


class MultipartFormData(MutableMapping):
    """Multipart Form data

    >>> files = MultipartFormData(logo=File("logo.png", b"content", "image/png"), favicon=File("favicon.png", b"content", "image/png"))
    >>> files.to_dict()
    {'logo': ('logo.png', b'content', 'image/png'), 'favicon': ('fabicon.png', b'content', 'image/png')}

    NOTE: The File obj can be a dictionary instead
    """  # noqa: E501

    def __init__(self, **files: File | dict[str, str | bytes | Any]):
        self._files = dict(
            {
                param_name: (file.to_tuple() if isinstance(file, File) else tuple(file.values()))
                for (param_name, file) in files.items()
                if file
            }
        )
        for param_name in files.keys():
            setattr(
                MultipartFormData,
                param_name,
                property(
                    lambda _: self.__getitem__(param_name),
                    lambda _, value: self.__setitem__(param_name, value),
                    lambda _: self.__delitem__(param_name),
                ),
            )

    def __getitem__(self, key):
        return self._files[key]

    def __setitem__(self, key: str, value: File | dict[str, Any] | Any):
        if isinstance(value, File):
            self._files[key] = value.to_tuple()
        elif isinstance(value, dict):
            self._files[key] = tuple(value.values())
        else:
            self._files[key] = value

    def __delitem__(self, key):
        del self._files[key]

    def __iter__(self):
        return iter(self._files)

    def __len__(self):
        return len(self._files)

    def to_dict(self) -> dict[str, tuple[str, str | bytes, str] | Any]:
        return dict(self._files)
