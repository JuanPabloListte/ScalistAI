from app.core.database import SessionLocal
from app.models.user import User
from app.models.organization import Organization
from sqlalchemy import select

def fix_users():
    with SessionLocal() as db:
        # Check if default org exists
        default_org = db.get(Organization, 1)
        if not default_org:
            default_org = Organization(id=1, name="Default Organization", subscription_status="active")
            db.add(default_org)
            db.commit()
            print("Created Default Organization with ID 1")

        # Get all users with NULL organization_id
        users = db.execute(select(User).where(User.organization_id.is_(None))).scalars().all()
        for u in users:
            u.organization_id = 1
            print(f"Assigned organization 1 to user {u.email}")
        
        if users:
            db.commit()
            print("Fix applied successfully.")
        else:
            print("No users needed fixing.")

if __name__ == "__main__":
    fix_users()
