import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from application import app, db
from models import User, UserRole
from werkzeug.security import generate_password_hash

def create_uc():
    """Create 2 Unit Coordinator accounts"""
    accounts = [
        {
            "email": "uc@example.com",
            "first_name": "Unit",
            "last_name": "Coordinator",
            "password": "Admin123!@"
        },
        {
            "email": "uc2@example.com",
            "first_name": "Unit",
            "last_name": "Coordinator 2",
            "password": "Admin123!@"
        }
    ]
    
    with app.app_context():
        # Make sure tables exist
        db.create_all()
        
        created_count = 0
        for account in accounts:
            email = account["email"]
            
            # Check if user already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                print(f"User {email} already exists. Skipping.")
                continue
            
            # Create Unit Coordinator user
            uc = User(
                email=email,
                first_name=account["first_name"],
                last_name=account["last_name"],
                role=UserRole.UNIT_COORDINATOR,
                password_hash=generate_password_hash(account["password"])
            )
            
            db.session.add(uc)
            created_count += 1
            
            print(f"Created Unit Coordinator account:")
            print(f"• Email: {email}")
            print(f"• Name: {account['first_name']} {account['last_name']}")
            print(f"• Password: {account['password']}")
            print()
        
        if created_count > 0:
            db.session.commit()
            print(f"Successfully created {created_count} Unit Coordinator account(s).")
        else:
            print("No new accounts were created (all already exist).")

if __name__ == "__main__":
    create_uc()

