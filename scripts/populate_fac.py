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
                # Check if user has a password (account is set up)
                if existing_user.password_hash:
                    print(f"User {email} already exists with password. Skipping.")
                    skipped_count += 1
                    continue
                else:
                    # User exists but doesn't have a password (created from CSV upload)
                    # Update them with password and basic info
                    existing_user.password_hash = generate_password_hash(password)
                    if not existing_user.first_name:
                        existing_user.first_name = f"Facilitator"
                    if not existing_user.last_name:
                        existing_user.last_name = f"{i}"
                    if existing_user.role != UserRole.FACILITATOR:
                        existing_user.role = UserRole.FACILITATOR
                    created_count += 1
                    print(f"Updated existing user {email} with password and account setup")
                    continue
            
            # Create new facilitator user
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
        print(f"• Created/Updated: {created_count} facilitator account(s)")
        print(f"• Skipped: {skipped_count} existing account(s) (already have passwords)")
        print(f"• Password for all accounts: {password}")

if __name__ == "__main__":
    create_facilitators()

