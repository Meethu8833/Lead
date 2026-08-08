"""rename lead status CUSTOMER to CONVERTED

Revision ID: a1f4c7b93e02
Revises: 9dcc5194e0bb
Create Date: 2026-08-07 10:12:44.318702

Renames the terminal-success member of the `lead_status` Postgres ENUM from `CUSTOMER` to
`CONVERTED`, so the enum matches the vocabulary the Lead Pipeline (Kanban) board uses for
its final column. Before this change the board would have had to either send an invalid
`CONVERTED` value (a 422 from `PUT /leads/{id}`) or label its column with a word the API
does not speak.

Three things are worth knowing about this migration:

1. **It is a rename, not an add-plus-backfill.** `ALTER TYPE ... RENAME VALUE` rewrites the
   label in the type's catalog entry; rows already storing `CUSTOMER` keep their physical
   OID and simply read back as `CONVERTED` afterwards. No `UPDATE leads SET ...` is needed
   and no row is rewritten, which is what makes this safe on a populated table. The
   alternative — add `CONVERTED`, backfill, drop `CUSTOMER` — is strictly worse here:
   Postgres cannot drop an enum member at all, so it would leave a permanently dead value.

2. **`lead_status` is not the only enum with a `CUSTOMER` member, and the other one must not
   be touched.** `app/models/photographer.py` declares a separate `LeadStatus` on the
   Postgres type `leadstatus` (no underscore) which keeps its own `CUSTOMER` member, still
   referenced by `app/services/photographer.py`. Both statements below name `lead_status`
   explicitly for that reason — a careless `leadstatus` here would silently break the
   photographer module instead.

3. **`ALTER TYPE ... RENAME VALUE` requires PostgreSQL 10+ and is transaction-safe**, unlike
   `ADD VALUE`, which carried a pre-12 restriction (see migration 9dcc5194e0bb). It
   therefore runs inline with no `COMMIT` juggling.

The downgrade is an exact inverse, so a downgrade/re-upgrade cycle round-trips cleanly.
Note that `server_default='NEW'` on `leads.status` is unaffected either way — the renamed
member is not the default.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1f4c7b93e02'
down_revision: Union[str, None] = '9dcc5194e0bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename lead_status.CUSTOMER -> CONVERTED, preserving every existing row."""
    op.execute("ALTER TYPE lead_status RENAME VALUE 'CUSTOMER' TO 'CONVERTED'")


def downgrade() -> None:
    """Restore the original CUSTOMER label."""
    op.execute("ALTER TYPE lead_status RENAME VALUE 'CONVERTED' TO 'CUSTOMER'")
