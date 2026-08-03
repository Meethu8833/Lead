# Database Migrations (`/alembic`)

This folder manages relational database schema changes using Alembic. 

## Structure
- [env.py](file:///d:/Projects/Lead%20CRM/alembic/env.py): Bootstraps the migration environment. We configured it to read credentials dynamically from `app/core/config.py` using asynchronous drivers.
- [script.py.mako](file:///d:/Projects/Lead%20CRM/alembic/script.py.mako): The Mako template used to generate new migration scripts.
- [versions/](file:///d:/Projects/Lead%20CRM/alembic/versions): Contains auto-generated or hand-written python migration version files tracking schema revisions.
