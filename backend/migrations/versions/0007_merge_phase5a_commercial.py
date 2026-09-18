"""Merge the provenance branch into the commercial Alembic chain.

The Phase 5-A migration was introduced from 0001 before the commercial
migration chain was added. This merge revision preserves both histories and
makes a single Alembic head so `alembic upgrade head` is deterministic.
"""

from alembic import op

revision = "0007_merge_phase5a_commercial"
down_revision = ("0002_phase5a_provenance", "0006_phase3a_admin_config")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
