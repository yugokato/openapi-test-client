from enum import Enum

from pydantic import AnyUrl, BaseModel, EmailStr, Field, PositiveInt


class UserRole(Enum):
    ADMIN = "admin"
    VIEWER = "viewer"
    SUPPORT = "support"


class UserTheme(Enum):
    LIGHT_MODE = "light"
    DARK_MODE = "dark"
    SYSTEM_SYNC = "system"


class UserQuery(BaseModel):
    id: PositiveInt | None = None
    email: EmailStr | None = None
    role: UserRole | None = None


class SocialLinks(BaseModel):
    facebook: AnyUrl | None = None
    instagram: AnyUrl | None = None
    linkedin: AnyUrl | None = None
    github: AnyUrl | None = None


class Preferences(BaseModel):
    theme: UserTheme | None = UserTheme.LIGHT_MODE
    language: str | None = None
    font_size: int | None = Field(None, ge=8, le=40, multiple_of=2)


class Metadata(BaseModel):
    preferences: Preferences | None = None
    social_links: SocialLinks | None = None


class UserRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    role: UserRole
    metadata: Metadata | None = None


class User(UserRequest):
    id: PositiveInt
