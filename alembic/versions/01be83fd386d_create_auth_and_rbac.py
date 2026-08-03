"""create_auth_and_rbac

Revision ID: 01be83fd386d
Revises: a8804be68f0c
Create Date: 2026-08-02 16:45:51.329612

"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01be83fd386d'
down_revision: Union[str, None] = 'a8804be68f0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Static seeding data definitions
PERMISSIONS = [
    # orders
    ("orders", "create"),
    ("orders", "update"),
    ("orders", "delete"),
    ("orders", "view"),
    ("orders", "*"),
    # payments
    ("payments", "create"),
    ("payments", "update"),
    ("payments", "delete"),
    ("payments", "view"),
    ("payments", "*"),
    # inventory
    ("inventory", "create"),
    ("inventory", "update"),
    ("inventory", "delete"),
    ("inventory", "view"),
    ("inventory", "*"),
    # dashboard
    ("dashboard", "view"),
    # production
    ("production", "update"),
    ("production", "view"),
    ("production", "*"),
    # invoices
    ("invoices", "create"),
    ("invoices", "update"),
    ("invoices", "delete"),
    ("invoices", "view"),
    ("invoices", "*"),
    # delivery
    ("delivery", "create"),
    ("delivery", "update"),
    ("delivery", "delete"),
    ("delivery", "view"),
    ("delivery", "*"),
    # reports
    ("reports", "view"),
    # employees
    ("employees", "create"),
    ("employees", "update"),
    ("employees", "delete"),
    ("employees", "view"),
    ("employees", "*"),
    # photographers
    ("photographers", "create"),
    ("photographers", "update"),
    ("photographers", "delete"),
    ("photographers", "view"),
    ("photographers", "*"),
    # wildcards
    ("*", "*"),
    ("*", "view"),
]

ROLE_PERMISSIONS_MAPPING = {
    "Administrator": {
        "description": "System administrator with full database bypass",
        "is_system": True,
        "patterns": [("*", "*")]
    },
    "Manager": {
        "description": "Operational manager overseeing all CRM modules",
        "is_system": False,
        "patterns": [
            ("orders", "*"), ("payments", "*"), ("inventory", "*"),
            ("dashboard", "view"), ("production", "*"), ("invoices", "*"),
            ("delivery", "*"), ("reports", "view"), ("employees", "*"),
            ("photographers", "*")
        ]
    },
    "Reception": {
        "description": "Front-desk receptionist managing bookings and payments",
        "is_system": False,
        "patterns": [
            ("orders", "create"), ("orders", "view"), ("orders", "update"),
            ("payments", "create"), ("payments", "view"), ("photographers", "*"),
            ("dashboard", "view")
        ]
    },
    "Designer": {
        "description": "Album design specialist",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update"),
            ("dashboard", "view")
        ]
    },
    "Editor": {
        "description": "Photo correction and retouching editor",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update"),
            ("dashboard", "view")
        ]
    },
    "Color Correction": {
        "description": "Color profiling and balance correction specialist",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Printing": {
        "description": "Lab printing operator",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update"),
            ("inventory", "view")
        ]
    },
    "Lamination": {
        "description": "Lamination operator",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Quality Check": {
        "description": "Product quality assurance specialist",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Packing": {
        "description": "Finished product packaging operator",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("production", "view"), ("production", "update")
        ]
    },
    "Delivery": {
        "description": "Courier and dispatch clerk",
        "is_system": False,
        "patterns": [
            ("orders", "view"), ("delivery", "*")
        ]
    },
    "Accountant": {
        "description": "Financial ledger and invoicing specialist",
        "is_system": False,
        "patterns": [
            ("invoices", "*"), ("payments", "*"), ("reports", "view"),
            ("dashboard", "view")
        ]
    },
    "Viewer": {
        "description": "Read-only access across all operations",
        "is_system": False,
        "patterns": [("*", "view")]
    }
}


def upgrade() -> None:
    # 1. Create tables
    op.create_table('permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('module', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('module', 'action', name='uq_permission_module_action')
    )
    op.create_index(op.f('ix_permissions_action'), 'permissions', ['action'], unique=False)
    op.create_index(op.f('ix_permissions_id'), 'permissions', ['id'], unique=False)
    op.create_index(op.f('ix_permissions_module'), 'permissions', ['module'], unique=False)

    op.create_table('roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_roles_id'), 'roles', ['id'], unique=False)
    op.create_index(op.f('ix_roles_name'), 'roles', ['name'], unique=True)

    op.create_table('employees',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_code', sa.String(length=50), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('designation', sa.String(length=100), nullable=True),
        sa.Column('role_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False),
        sa.Column('last_failed_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lock_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reset_token', sa.String(length=255), nullable=True),
        sa.Column('reset_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('profile_photo_url', sa.String(length=500), nullable=True),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_employees_email'), 'employees', ['email'], unique=True)
    op.create_index(op.f('ix_employees_employee_code'), 'employees', ['employee_code'], unique=True)
    op.create_index(op.f('ix_employees_id'), 'employees', ['id'], unique=False)
    op.create_index(op.f('ix_employees_phone'), 'employees', ['phone'], unique=True)

    op.create_table('role_permissions',
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('permission_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )

    op.create_table('user_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('device_name', sa.String(length=255), nullable=True),
        sa.Column('is_revoked', sa.Boolean(), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_sessions_employee_id'), 'user_sessions', ['employee_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_id'), 'user_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_user_sessions_token_hash'), 'user_sessions', ['token_hash'], unique=True)

    # 2. Create PostgreSQL Sequence for employee codes
    op.execute("CREATE SEQUENCE employee_code_seq START WITH 1")

    # 3. Alter PostgreSQL enum type for AuditAction
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'LOGIN_SUCCESS'")
        op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'LOGIN_FAILURE'")
        op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'LOGOUT'")
        op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'PASSWORD_RESET'")

    # 4. Seed Permissions, Roles and Mappings with Upsert (ON CONFLICT) logic
    namespace = uuid.UUID("8aa0eed3-6f30-4196-8919-4377038e5281")
    bind = op.get_bind()

    # Permissions upsert
    for module, action in PERMISSIONS:
        perm_id = uuid.uuid5(namespace, f"permission:{module}:{action}")
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, module, action) VALUES (:id, :module, :action) "
                "ON CONFLICT (module, action) DO NOTHING"
            ),
            {"id": str(perm_id), "module": module, "action": action}
        )

    # Roles upsert
    for role_name, config in ROLE_PERMISSIONS_MAPPING.items():
        role_id = uuid.uuid5(namespace, f"role:{role_name}")
        bind.execute(
            sa.text(
                "INSERT INTO roles (id, name, description, is_system, created_at) "
                "VALUES (:id, :name, :description, :is_system, NOW()) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {
                "id": str(role_id),
                "name": role_name,
                "description": config["description"],
                "is_system": config["is_system"]
            }
        )

        # Mappings upsert
        for p_mod, p_act in config["patterns"]:
            perm_id = uuid.uuid5(namespace, f"permission:{p_mod}:{p_act}")
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :permission_id) "
                    "ON CONFLICT (role_id, permission_id) DO NOTHING"
                ),
                {"role_id": str(role_id), "permission_id": str(perm_id)}
            )


def downgrade() -> None:
    # 1. Drop sequence
    op.execute("DROP SEQUENCE IF EXISTS employee_code_seq")

    # 2. Drop tables
    op.drop_index(op.f('ix_user_sessions_token_hash'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_id'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_employee_id'), table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_employees_phone'), table_name='employees')
    op.drop_index(op.f('ix_employees_id'), table_name='employees')
    op.drop_index(op.f('ix_employees_employee_code'), table_name='employees')
    op.drop_index(op.f('ix_employees_email'), table_name='employees')
    op.drop_table('employees')
    op.drop_index(op.f('ix_roles_name'), table_name='roles')
    op.drop_index(op.f('ix_roles_id'), table_name='roles')
    op.drop_table('roles')
    op.drop_index(op.f('ix_permissions_module'), table_name='permissions')
    op.drop_index(op.f('ix_permissions_id'), table_name='permissions')
    op.drop_index(op.f('ix_permissions_action'), table_name='permissions')
    op.drop_table('permissions')
