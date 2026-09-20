"""Create vendor_followup_logs table.

Revision ID: 20260811_vendor_followup_tables
Revises: 20260811_gstr9_audit_overrides
Create Date: 2026-08-11 10:36:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260811_vendor_followup_tables'
down_revision = "gstr9_audit_overrides"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table('vendor_followup_logs', schema='public'):
        op.create_table(
            'vendor_followup_logs',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('client_gstin_id', UUID(as_uuid=True), sa.ForeignKey('public.client_gstins.id', ondelete='CASCADE'), nullable=False),
            sa.Column('supplier_gstin', sa.Text(), nullable=False),
            sa.Column('supplier_name', sa.Text(), nullable=True),
            sa.Column('vendor_phone', sa.Text(), nullable=True),
            sa.Column('vendor_email', sa.Text(), nullable=True),
            sa.Column('channel', sa.Text(), nullable=False, server_default='WHATSAPP'),
            sa.Column('template_type', sa.Text(), nullable=False, server_default='POLITE_REMINDER'),
            sa.Column('invoices_count', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('at_risk_itc_rupees', sa.Numeric(15, 2), nullable=False, server_default='0.00'),
            sa.Column('status', sa.Text(), nullable=False, server_default='SENT'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('dispatched_by', UUID(as_uuid=True), sa.ForeignKey('auth.users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc'::text, now())")),
            sa.Column('work_item_id', UUID(as_uuid=True), sa.ForeignKey('public.itc_work_items.id', ondelete='SET NULL'), nullable=True),
            sa.Column('message_body', sa.Text(), nullable=True),
            schema='public',
        )
        inspector = inspect(bind)

    existing_indexes = {
        idx['name']
        for idx in inspector.get_indexes('vendor_followup_logs', schema='public')
        if idx.get('name')
    }

    if 'idx_vendor_followup_client_supplier' not in existing_indexes:
        op.create_index(
            'idx_vendor_followup_client_supplier',
            'vendor_followup_logs',
            ['client_gstin_id', 'supplier_gstin'],
            schema='public',
        )

    if 'idx_vendor_followup_work_item' not in existing_indexes:
        op.create_index(
            'idx_vendor_followup_work_item',
            'vendor_followup_logs',
            ['work_item_id'],
            schema='public',
        )


def downgrade():
    op.drop_index('idx_vendor_followup_client_supplier', table_name='vendor_followup_logs')
    op.drop_table('vendor_followup_logs')
