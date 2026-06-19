"""merge

Revision ID: a992d2cd029d
Revises: 27ff8b7f29fa, d4f2b7ed1887
Create Date: 2026-06-18 13:43:27.158504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a992d2cd029d'
down_revision: Union[str, Sequence[str], None] = ('27ff8b7f29fa', 'd4f2b7ed1887')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
