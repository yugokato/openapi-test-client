from typing import Annotated, Any, Literal

from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint
from openapi_test_client.libraries.api.types import Constraint, File, Format, Optional, Unset

from ..models.users import Metadata


class UsersAPI(DemoAppBaseAPI):
    TAGs = ("Users",)

    @endpoint.post("/v1/users")
    def create_user(
        self,
        *,
        first_name: Annotated[str, Constraint(min_len=1, max_len=255)] = Unset,
        last_name: Annotated[str, Constraint(min_len=1, max_len=255)] = Unset,
        email: Annotated[str, Format("email")] = Unset,
        role: Literal["admin", "viewer", "support"] = Unset,
        metadata: Optional[Metadata] = Unset,
        **kwargs: Any,
    ) -> RestResponse:
        """Create a new user"""
        ...

    @endpoint.get("/v1/users/{user_id}")
    def get_user(self, user_id: int, /, **kwargs: Any) -> RestResponse:
        """Get user"""
        ...

    @endpoint.get("/v1/users")
    def get_users(
        self,
        *,
        id: Optional[int] = Unset,
        email: Optional[Annotated[str, Format("email")]] = Unset,
        role: Optional[Literal["admin", "viewer", "support"]] = Unset,
        **kwargs: Any,
    ) -> RestResponse:
        """Get users"""
        ...

    @endpoint.content_type("multipart/form-data")
    @endpoint.post("/v1/users/images")
    def upload_image(self, *, file: File = Unset, description: Optional[str] = Unset, **kwargs: Any) -> RestResponse:
        """Upload user image"""
        ...

    @endpoint.delete("/v1/users/{user_id}")
    def delete_user(self, user_id: int, /, **kwargs: Any) -> RestResponse:
        """Delete user"""
        ...
