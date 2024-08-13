from typing import Annotated, Literal, Optional

from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.sample_app.api.base import SampleAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint
from openapi_test_client.libraries.api.types import Constraint, File, Format

from ..models.users import Metadata


class UsersAPI(SampleAppBaseAPI):
    TAGs = ["Users"]

    @endpoint.post("/v1/users")
    def create_user(
        self,
        *,
        first_name: Annotated[str, Constraint(min_len=1, max_len=255)] = None,
        last_name: Annotated[str, Constraint(min_len=1, max_len=255)] = None,
        email: Annotated[str, Format("email")] = None,
        role: Literal["admin", "viewer", "support"] = None,
        metadata: Optional[Metadata] = None,
        **kwargs,
    ) -> RestResponse:
        """Create a new user"""
        ...

    @endpoint.get("/v1/users/{user_id}")
    def get_user(self, user_id: int, /, **kwargs) -> RestResponse:
        """Get user"""
        ...

    @endpoint.get("/v1/users")
    def get_users(
        self,
        *,
        id: Optional[int] = None,
        email: Optional[Annotated[str, Format("email")]] = None,
        role: Optional[Literal["admin", "viewer", "support"]] = None,
        **kwargs,
    ) -> RestResponse:
        """Get users"""
        ...

    @endpoint.content_type("multipart/form-data")
    @endpoint.post("/v1/users/images")
    def upload_image(self, *, file: File = None, description: Optional[str] = None, **kwargs) -> RestResponse:
        """Upload user image"""
        ...

    @endpoint.delete("/v1/users/{user_id}")
    def delete_user(self, user_id: int, /, **kwargs) -> RestResponse:
        """Delete user"""
        ...
