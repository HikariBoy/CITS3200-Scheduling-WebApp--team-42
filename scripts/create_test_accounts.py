#!/usr/bin/env python3
"""
Script to create test accounts:
- 1 admin account: admin@email.com
- 1 unit coordinator account: uc@email.com
- 3 facilitator accounts: facilitator1@email.com, facilitator2@email.com, facilitator3@email.com

All accounts use password: Admin123
"""

import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from application import app, db
from models import User, UserRole

def create_test_accounts():
    """Create test accounts for development/testing"""
    password = "Admin123"
    
    accounts = [
        {
            "email": "admin@email.com",
            "role": UserRole.ADMIN,
            "first_name": "Admin",
            "last_name": "User"
        },
        {
            "email": "uc@email.com",
            "role": UserRole.UNIT_COORDINATOR,
            "first_name": "Unit",
            "last_name": "Coordinator"
        },
        {
            "email": "facilitator1@email.com",
            "role": UserRole.FACILITATOR,
            "first_name": "Facilitator",
            "last_name": "One"
        },
        {
            "email": "facilitator2@email.com",
            "role": UserRole.FACILITATOR,
            "first_name": "Facilitator",
            "last_name": "Two"
        },
        {
            "email": "facilitator3@email.com",
            "role": UserRole.FACILITATOR,
            "first_name": "Facilitator",
            "last_name": "Three"
        }
    ]
    
    with app.app_context():
        # Ensure database tables exist
        db.create_all()
        
        created_count = 0
        skipped_count = 0
        
        for account_info in accounts:
            email = account_info["email"]
            role = account_info["role"]
            
            # Check if user already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                print(f"⚠️  User {email} already exists. Skipping...")
                skipped_count += 1
                continue
            
            # Create new user
            user = User(
                email=email,
                first_name=account_info["first_name"],
                last_name=account_info["last_name"],
                role=role
            )
            
            # Set password using the User model's method
            user.set_password(password)
            
            db.session.add(user)
            print(f"✓ Created {role.value}: {email}")
            created_count += 1
        
        # Commit all new users
        if created_count > 0:
            db.session.commit()
            print(f"\n✅ Successfully created {created_count} account(s)")
        
        if skipped_count > 0:
            print(f"⚠️  Skipped {skipped_count} existing account(s)")
        
        print(f"\nAll accounts use password: {password}")

if __name__ == "__main__":
    create_test_accounts()

