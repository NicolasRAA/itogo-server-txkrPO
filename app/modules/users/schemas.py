from pydantic import BaseModel, ConfigDict, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    consent: bool


class LoginIn(BaseModel):
    email: str
    password: str


class ConfirmIn(BaseModel):
    token: str


class SettingsIn(BaseModel):
    notify_by_email: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    email_confirmed: bool
    notify_by_email: bool
