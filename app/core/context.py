"""
app/core/context.py

This module manages request-scoped metadata (such as the current user, IP address, and user agent)
using python's standard contextvars library. This allows clean, async-safe data flow from HTTP middleware
down to the database layer without polluting service/repository function signatures.
"""

from contextvars import ContextVar
from typing import Any, Dict, Optional

# Async-scoped storage for auditing data
audit_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("audit_context", default=None)
