"""merge billing and tally bridge heads

Revision ID: 92f7064a0b30
Revises: tally_bridge_keys, billing_policies
Create Date: 2026-08-08 20:40:03.107103

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '92f7064a0b30'
down_revision = ('tally_bridge_keys', 'billing_policies')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
