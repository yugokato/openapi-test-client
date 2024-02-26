from enum import Enum
from typing import Optional

from pydantic import AnyUrl, BaseModel, EmailStr, Field
from quart_schema.pydantic import File


class UserRole(Enum):
    ADMIN = "admin"
    VIEWER = "viewer"
    SUPPORT = "support"


class UserTheme(Enum):
    LIGHT_MODE = "light"
    DARK_MODE = "dark"
    SYSTEM_SYNC = "system"


class UserQuery(BaseModel):
    id: Optional[int] = None
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None


class SocialLinks(BaseModel):
    facebook: Optional[AnyUrl] = None
    instagram: Optional[AnyUrl] = None
    linkedin: Optional[AnyUrl] = None
    github: Optional[AnyUrl] = None


class Preferences(BaseModel):
    theme: Optional[UserTheme] = UserTheme.LIGHT_MODE.value
    language: Optional[str] = None
    font_size: Optional[int] = Field(None, ge=8, le=40, multiple_of=2)


class Metadata(BaseModel):
    preferences: Optional[Preferences] = None
    social_links: Optional[SocialLinks] = None


class UserRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    role: UserRole
    metadata: Optional[Metadata] = Field(default_factory=dict)


class User(UserRequest):
    id: int


class UserImage(BaseModel):
    file: File
    description: Optional[str] = None
