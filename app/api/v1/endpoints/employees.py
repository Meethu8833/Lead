"""
app/api/v1/endpoints/employees.py

API router exposing employee profile management endpoints.
Under Clean Architecture, this resides in the Interface Adapters layer.
"""

import os
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.api import deps
from app.core.exceptions import BadRequestException
from app.models.employee import Employee
from app.schemas.employee import (
    EmployeeResponse,
    PhoneUpdateRequest,
    EmailUpdateRequest,
)
from app.services.employee import EmployeeService
from app.services.cache import permission_cache

router = APIRouter()


@router.get("/me/profile", response_model=EmployeeResponse)
async def get_my_profile(
    current_employee: Employee = Depends(deps.get_current_employee)
) -> Employee:
    """
    Retrieves the profile of the current logged-in employee.
    """
    return current_employee


@router.post("/me/profile-photo", response_model=EmployeeResponse)
async def upload_profile_photo(
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(deps.get_db),
    current_employee: Employee = Depends(deps.get_current_employee),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> Employee:
    """
    Saves a profile photo for the current employee.
    Validates file formats (PNG, JPG, JPEG).
    """
    filename = photo.filename or "photo.jpg"
    ext = filename.split(".")[-1].lower()
    if ext not in ["png", "jpg", "jpeg"]:
        raise BadRequestException("Invalid file format. Only JPG, JPEG, and PNG are allowed.")

    upload_dir = "uploads/profile_photos"
    os.makedirs(upload_dir, exist_ok=True)
    new_filename = f"{current_employee.id}.{ext}"
    filepath = os.path.join(upload_dir, new_filename)

    contents = await photo.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    photo_url = f"/static/profile_photos/{new_filename}"
    return await employee_service.update_profile_photo(db, current_employee.id, photo_url)


@router.put("/me/phone", response_model=EmployeeResponse)
async def update_phone(
    payload: PhoneUpdateRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_employee: Employee = Depends(deps.get_current_employee),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> Employee:
    """
    Updates the contact phone number of the current employee.
    """
    return await employee_service.update_phone(db, current_employee.id, payload.phone)


@router.put("/me/email", response_model=EmployeeResponse)
async def update_email(
    payload: EmailUpdateRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_employee: Employee = Depends(deps.get_current_employee),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> Employee:
    """
    Updates the email address of the current employee.
    """
    return await employee_service.update_email(db, current_employee.id, payload.email)


@router.get("/me/permissions")
async def get_my_permissions(
    db: AsyncSession = Depends(deps.get_db),
    current_employee: Employee = Depends(deps.get_current_employee),
    employee_service: EmployeeService = Depends(deps.get_employee_service),
) -> list[str]:
    """
    Returns a flat list of permissions assigned to the current employee.
    Hits cache first, falls back to database querying on miss.
    """
    cached_perms = await permission_cache.get_permissions(current_employee.id)
    if cached_perms is None:
        role_id, db_perms = await employee_service.get_permissions_from_db(db, current_employee.id)
        await permission_cache.set_permissions(current_employee.id, role_id, db_perms)
        cached_perms = db_perms
    return cached_perms
