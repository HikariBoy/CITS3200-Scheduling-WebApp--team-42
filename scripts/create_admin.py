import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from application import app, db
from models import User, UserRole
from werkzeug.security import generate_password_hash

def create_admin():
    """Create an Admin account"""
    account = {
        "email": "admin@example.com",
        "first_name": "Admin",
        "last_name": "User",
        "password": "Admin123!@"
    }
    
    with app.app_context():
        # Make sure tables exist
        db.create_all()
        
        email = account["email"]
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f"User {email} already exists. Skipping.")
            return
        
        # Create Admin user
        admin = User(
            email=email,
            first_name=account["first_name"],
            last_name=account["last_name"],
            role=UserRole.ADMIN,
            password_hash=generate_password_hash(account["password"])
        )
        
        db.session.add(admin)
        db.session.commit()
        
        print(f"Created Admin account:")
        print(f"• Email: {email}")
        print(f"• Name: {account['first_name']} {account['last_name']}")
        print(f"• Password: {account['password']}")
        print()
        print("Successfully created Admin account.")

if __name__ == "__main__":
    create_admin()

