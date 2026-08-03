"""
app/api/v1/endpoints/auth.py

API router exposing authentication endpoints.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.api import deps
from app.models.employee import Employee
from app.schemas.employee import (
    LoginRequest,
    TokenResponse,
    EmployeeResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.services.auth import AuthService
from app.services.employee import EmployeeService

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(deps.get_db),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> TokenResponse:
    """
    Authenticates employee credentials.
    Returns access token and rotated opaque refresh token.
    Tracks failed login attempts and locking rules.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    # We can infer device name from user agent
    device_name = None
    if user_agent:
        if "Windows" in user_agent:
            device_name = "Windows Device"
        elif "Macintosh" in user_agent:
            device_name = "Mac Device"
        elif "iPhone" in user_agent:
            device_name = "iPhone"
        elif "Android" in user_agent:
            device_name = "Android Phone"
        elif "Linux" in user_agent:
            device_name = "Linux Device"
        else:
            device_name = "Web Client"

    return await auth_service.login(
        db=db,
        payload=payload,
        ip_address=ip_address,
        user_agent=user_agent,
        device_name=device_name,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    refresh_token: str,  # Passed in JSON body or query/header; accepting in body is simple
    db: AsyncSession = Depends(deps.get_db),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> TokenResponse:
    """
    Exchanges an opaque refresh token for a new access token and rotated refresh token.
    Detects replay attacks and revokes all active sessions on reuse.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return await auth_service.refresh(
        db=db,
        refresh_token=refresh_token,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post("/logout")
async def logout(
    refresh_token: str,
    request: Request,
    db: AsyncSession = Depends(deps.get_db),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> dict:
    """
    Logs out the current session by invalidating the refresh token.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await auth_service.logout(db, refresh_token, ip_address, user_agent)
    return {"success": True, "detail": "Session logged out successfully."}


@router.post("/logout-all")
async def logout_all(
    request: Request,
    db: AsyncSession = Depends(deps.get_db),
    current_employee: Employee = Depends(deps.get_current_employee),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> dict:
    """
    Revokes every session/refresh token for the currently authenticated employee.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await auth_service.logout_all(db, current_employee.id, ip_address, user_agent)
    return {"success": True, "detail": "All sessions terminated successfully."}


@router.get("/me", response_model=EmployeeResponse)
async def get_me(
    current_employee: Employee = Depends(deps.get_current_employee)
) -> Employee:
    """
    Returns the authenticated employee's profile.
    """
    return current_employee


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_employee: Employee = Depends(deps.get_current_employee),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> dict:
    """
    Updates the password for the current logged-in employee.
    """
    await employee_service.change_password(
        db=db,
        id=current_employee.id,
        old_pw=payload.old_password,
        new_pw=payload.new_password,
    )
    return {"success": True, "detail": "Password updated successfully. Other sessions invalidated."}


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(deps.get_db),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> dict:
    """
    Requests a password reset token.
    Returns the token in response to simplify testing.
    """
    token = await employee_service.forgot_password(db, payload.email)
    return {
        "success": True,
        "detail": "Password reset token generated.",
        "token": token,  # Provided directly for testing
    }


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(deps.get_db),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> dict:
    """
    Resets the password using a valid, non-expired reset token.
    """
    await employee_service.reset_password(
        db=db,
        token=payload.token,
        new_password=payload.new_password,
    )
    return {"success": True, "detail": "Password has been reset successfully."}
