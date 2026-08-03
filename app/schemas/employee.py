"""
app/schemas/employee.py

Defines the Pydantic schemas/DTOs for Employee creation, update, authentication, and responses.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import uuid
import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class EmployeeBase(BaseModel):
    """
    Base shared properties of an Employee.
    """
    first_name: str = Field(..., min_length=1, description="First name of the employee")
    last_name: str = Field(..., min_length=1, description="Last name of the employee")
    email: str = Field(..., description="Staff email address")
    phone: str = Field(..., description="Unique contact phone number")
    department: str | None = Field(None, description="Department name")
    designation: str | None = Field(None, description="Job title/designation")
    role_id: uuid.UUID | None = Field(None, description="Assigned security role ID")

    @field_validator("first_name", "last_name")
    @classmethod
    def cannot_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip()
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("Phone number contains invalid characters.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return v


class EmployeeCreate(EmployeeBase):
    """
    Schema for creating a new Employee.
    """
    password: str = Field(..., min_length=8, description="Plain text password")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Validates password strength:
        - Minimum length 8 (ensured by min_length=8 field parameter)
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one digit
        - At least one special character
        """
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        
        special_chars = "!@#$%^&*()-_=+[]{}|;:',.<>?/`~"
        if not any(c in special_chars for c in v):
            raise ValueError("Password must contain at least one special character.")
            
        return v


class EmployeeUpdate(BaseModel):
    """
    Schema for updating an Employee.
    """
    first_name: str | None = Field(None, min_length=1)
    last_name: str | None = Field(None, min_length=1)
    email: str | None = Field(None)
    phone: str | None = Field(None)
    department: str | None = Field(None)
    designation: str | None = Field(None)
    role_id: uuid.UUID | None = Field(None)
    is_active: bool | None = Field(None)
    version: int | None = Field(None, description="Version number for optimistic locking verification")

    @field_validator("first_name", "last_name")
    @classmethod
    def cannot_be_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return stripped

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("Phone number contains invalid characters.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return v


class EmployeeResponse(EmployeeBase):
    """
    Schema for returning an Employee profile.
    """
    id: uuid.UUID
    employee_code: str
    is_active: bool
    last_login: datetime | None
    profile_photo_url: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==========================
# AUTH SCHEMAS
# ==========================

class LoginRequest(BaseModel):
    """
    Schema for logging in.
    """
    email: str = Field(..., description="Login email")
    password: str = Field(..., description="Login password")


class TokenResponse(BaseModel):
    """
    Schema representing JWT access and refresh token response.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    """
    Schema for changing a password.
    """
    old_password: str = Field(..., description="Current password")
    new_password: str = Field(..., description="New password")

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        
        special_chars = "!@#$%^&*()-_=+[]{}|;:',.<>?/`~"
        if not any(c in special_chars for c in v):
            raise ValueError("Password must contain at least one special character.")
        return v


class ForgotPasswordRequest(BaseModel):
    """
    Schema for requesting password reset.
    """
    email: str = Field(..., description="Registered email address")


class ResetPasswordRequest(BaseModel):
    """
    Schema for resetting a password using a token.
    """
    token: str = Field(..., description="Reset token received")
    new_password: str = Field(..., description="New password")

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        
        special_chars = "!@#$%^&*()-_=+[]{}|;:',.<>?/`~"
        if not any(c in special_chars for c in v):
            raise ValueError("Password must contain at least one special character.")
        return v


class PhoneUpdateRequest(BaseModel):
    """
    Schema for changing employee phone number.
    """
    phone: str = Field(..., description="New phone number")

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\+?[\d\s\-\(\)]+$", v):
            raise ValueError("Phone number contains invalid characters.")
        digit_count = sum(1 for c in v if c.isdigit())
        if digit_count < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return v


class EmailUpdateRequest(BaseModel):
    """
    Schema for changing employee email.
    """
    email: str = Field(..., description="New email address")

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip()
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format.")
        return v
