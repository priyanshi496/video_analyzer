"""merge heads

Revision ID: 07130787d3ba
Revises: 27ff8b7f29fa, d4f2b7ed1887
Create Date: 2026-06-17 19:33:32.661451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07130787d3ba'
down_revision: Union[str, Sequence[str], None] = ('27ff8b7f29fa', 'd4f2b7ed1887')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
