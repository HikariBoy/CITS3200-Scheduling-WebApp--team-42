import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from application import app, db
from models import User, UserRole
from werkzeug.security import generate_password_hash

def create_facilitators():
    """Create 5 facilitator accounts with emails fac1@email.com through fac5@email.com"""
    password = "Admin123!@"
    
    with app.app_context():
        # Make sure tables exist
        db.create_all()
        
        created_count = 0
        skipped_count = 0
        
        for i in range(1, 6):
            email = f"fac{i}@email.com"
            
            # Check if user already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                print(f"User {email} already exists. Skipping.")
                skipped_count += 1
                continue
            
            # Create facilitator user
            facilitator = User(
                email=email,
                first_name=f"Facilitator",
                last_name=f"{i}",
                role=UserRole.FACILITATOR,
                password_hash=generate_password_hash(password)
            )
            
            db.session.add(facilitator)
            created_count += 1
            print(f"Created facilitator account: {email}")
        
        # Commit all changes
        db.session.commit()
        
        print(f"\nSummary:")
        print(f"• Created: {created_count} facilitator account(s)")
        print(f"• Skipped: {skipped_count} existing account(s)")
        print(f"• Password for all accounts: {password}")

if __name__ == "__main__":
    create_facilitators()

