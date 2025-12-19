"""Add CSV report fields to Unit model

Revision ID: add_csv_report_fields
Revises: 
Create Date: 2025-12-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_csv_report_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add csv_report_filename and csv_report_generated_at columns to unit table
    with op.batch_alter_table('unit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('csv_report_filename', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('csv_report_generated_at', sa.DateTime(), nullable=True))


def downgrade():
    # Remove the columns if rolling back
    with op.batch_alter_table('unit', schema=None) as batch_op:
        batch_op.drop_column('csv_report_generated_at')
        batch_op.drop_column('csv_report_filename')
