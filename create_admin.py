#!/usr/bin/env python3
"""
Simple script to create an admin user in instance/dev.db
"""

import os
import sys

# Set DATABASE_URL BEFORE importing application - use absolute path
project_root = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(project_root, 'instance', 'dev.db')
os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from application import app, db
from models import User, UserRole
from werkzeug.security import generate_password_hash

def create_admin():
    """Create an admin user"""
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        
        email = "admin@email.com"
        password = "Admin123"
        
        # Check if user exists
        user = User.query.filter_by(email=email).first()
        if user:
            print(f"✓ Admin already exists: {email}")
            return
        
        # Create admin
        admin = User(
            email=email,
            first_name="Admin",
            last_name="User",
            role=UserRole.ADMIN,
            password_hash=generate_password_hash(password)
        )
        
        db.session.add(admin)
        db.session.commit()
        
        print(f"✓ Created Admin:")
        print(f"  Email:    {email}")
        print(f"  Password: {password}")

if __name__ == "__main__":
    create_admin()
