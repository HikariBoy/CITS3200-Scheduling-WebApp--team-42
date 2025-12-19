"""Add UnitCoordinator table for multiple coordinators per unit

Revision ID: add_unit_coordinator_table
Revises: add_email_token_model
Create Date: 2025-01-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'add_unit_coordinator_table'
down_revision = 'add_email_token_model'
branch_labels = None
depends_on = None


def upgrade():
    # Check if table already exists (in case it was created manually)
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    table_exists = 'unit_coordinator' in inspector.get_table_names()
    
    if not table_exists:
        # Create the unit_coordinator table
        op.create_table('unit_coordinator',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unit_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['unit_id'], ['unit.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unit_id', 'user_id', name='uq_coordinator_per_unit')
        )
    
    # Migrate existing created_by relationships to unit_coordinator table
    # This preserves all existing coordinator assignments
    # Only insert if the relationship doesn't already exist
    op.execute("""
        INSERT INTO unit_coordinator (unit_id, user_id, created_at)
        SELECT u.id, u.created_by, u.created_at
        FROM unit u
        WHERE u.created_by IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM unit_coordinator uc 
            WHERE uc.unit_id = u.id AND uc.user_id = u.created_by
        )
    """)


def downgrade():
    # Drop the unit_coordinator table
    # Note: We don't restore created_by relationships as they still exist in the unit table
    op.drop_table('unit_coordinator')

