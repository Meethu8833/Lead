"""
app/services/cache.py

Defines the PermissionCache service architecture.
Under Clean Architecture, this resides in the Application Business Rules (Use Cases) layer.
"""

import uuid
import logging
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)


class BasePermissionCache(ABC):
    """
    Abstract Base Class for permission caching.
    Enables future pluggability for Redis or other backends without modifying business logic.
    """

    @abstractmethod
    async def get_permissions(self, employee_id: uuid.UUID) -> List[str] | None:
        """
        Retrieves permissions list for the given employee ID.
        Returns None if cache miss.
        """
        pass

    @abstractmethod
    async def set_permissions(self, employee_id: uuid.UUID, role_id: uuid.UUID | None, permissions: List[str]) -> None:
        """
        Caches permissions list for the given employee ID.
        """
        pass

    @abstractmethod
    async def invalidate_employee(self, employee_id: uuid.UUID) -> None:
        """
        Invalidates cached permissions for a specific employee.
        """
        pass

    @abstractmethod
    async def invalidate_role(self, role_id: uuid.UUID) -> None:
        """
        Invalidates cached permissions for all employees belonging to a specific role.
        """
        pass

    @abstractmethod
    async def warm_cache(self, mapping: dict[uuid.UUID, tuple[uuid.UUID | None, List[str]]]) -> None:
        """
        Warms up the cache with a mapping of employee_id -> (role_id, permissions).
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """
        Clears all cached items.
        """
        pass


class InMemoryPermissionCache(BasePermissionCache):
    """
    In-memory thread-safe implementation of the permission cache.
    """

    def __init__(self) -> None:
        # Maps employee_id -> list of "module:action" permission strings
        self._cache: dict[uuid.UUID, List[str]] = {}
        # Maps employee_id -> role_id
        self._employee_roles: dict[uuid.UUID, uuid.UUID] = {}

    async def get_permissions(self, employee_id: uuid.UUID) -> List[str] | None:
        return self._cache.get(employee_id)

    async def set_permissions(self, employee_id: uuid.UUID, role_id: uuid.UUID | None, permissions: List[str]) -> None:
        self._cache[employee_id] = permissions
        if role_id is not None:
            self._employee_roles[employee_id] = role_id
        else:
            self._employee_roles.pop(employee_id, None)

    async def invalidate_employee(self, employee_id: uuid.UUID) -> None:
        self._cache.pop(employee_id, None)
        self._employee_roles.pop(employee_id, None)
        logger.debug(f"Invalidated permission cache for employee: {employee_id}")

    async def invalidate_role(self, role_id: uuid.UUID) -> None:
        # Identify all employees assigned to the role
        employees_to_invalidate = [
            emp_id for emp_id, r_id in self._employee_roles.items() if r_id == role_id
        ]
        for emp_id in employees_to_invalidate:
            self._cache.pop(emp_id, None)
            self._employee_roles.pop(emp_id, None)
        logger.debug(f"Invalidated permission cache for role: {role_id} (affected {len(employees_to_invalidate)} employees)")

    async def warm_cache(self, mapping: dict[uuid.UUID, tuple[uuid.UUID | None, List[str]]]) -> None:
        for emp_id, (role_id, perms) in mapping.items():
            self._cache[emp_id] = perms
            if role_id is not None:
                self._employee_roles[emp_id] = role_id
        logger.info(f"Warmed permission cache with {len(mapping)} employees.")

    async def clear(self) -> None:
        self._cache.clear()
        self._employee_roles.clear()


# Create global singleton instance of the permission cache
permission_cache = InMemoryPermissionCache()
