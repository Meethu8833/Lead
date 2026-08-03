# Application Core Configuration (`/app/core`)

This module provides cross-cutting, application-wide utilities that are decoupled from specific business logic or API endpoints.

## Contents
- [config.py](file:///d:/Projects/Lead%20CRM/app/core/config.py): Validates configurations and environment settings using Pydantic Settings.
- [database.py](file:///d:/Projects/Lead%20CRM/app/core/database.py): Establishes the asynchronous SQLAlchemy engine, session maker, and DB base model.
- [exceptions.py](file:///d:/Projects/Lead%20CRM/app/core/exceptions.py): Defines customized application exceptions and global FastAPI exception handlers.
- [logging.py](file:///d:/Projects/Lead%20CRM/app/core/logging.py): Configures custom structured log formats for unified application logging.
