import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from application import app, db
from models import User, UserRole
from werkzeug.security import generate_password_hash

def create_uc():
    """Create a Unit Coordinator account with email uc@example.com"""
    email = "uc@example.com"
    password = "Admin123!@"
    
    with app.app_context():
        # Make sure tables exist
        db.create_all()
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f"User {email} already exists. Skipping.")
            return
        
        # Create Unit Coordinator user
        uc = User(
            email=email,
            first_name="Unit",
            last_name="Coordinator",
            role=UserRole.UNIT_COORDINATOR,
            password_hash=generate_password_hash(password)
        )
        
        db.session.add(uc)
        db.session.commit()
        
        print(f"Created Unit Coordinator account:")
        print(f"• Email: {email}")
        print(f"• Password: {password}")

if __name__ == "__main__":
    create_uc()

