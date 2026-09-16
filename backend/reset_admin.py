"""AeroOps Admin CLI: list users and reset/set passwords directly in SQLite."""
import sys
from app.core.security import hash_password
from app.db.database import SessionLocal, init_db
from app.db.models import User


def main():
    init_db()
    db = SessionLocal()
    try:
        users = db.query(User).all()
        if len(sys.argv) < 3:
            print("=== AeroOps User Accounts ===")
            if not users:
                print("No users found in database.")
            for u in users:
                print(f"- ID: {u.id} | Username: {u.username} | Email: {u.email} | Role: {u.role}")
            print("\nUsage to reset password:")
            print("  python reset_admin.py <username_or_email> <new_password>")
            return

        target = sys.argv[1].strip()
        new_pw = sys.argv[2].strip()

        if len(new_pw) < 8:
            print("Error: Password must be at least 8 characters long.")
            sys.exit(1)

        user = db.query(User).filter(
            (User.username.ilike(target)) | (User.email.ilike(target))
        ).first()

        if not user:
            print(f"Error: User '{target}' not found.")
            print("Existing users:")
            for u in users:
                print(f"  {u.username} ({u.email})")
            sys.exit(1)

        user.password_hash = hash_password(new_pw)
        db.commit()
        print(f"Success: Password for '{user.username}' ({user.role}) has been updated.")
        print(f"You can now log in at http://localhost:5174/login with:")
        print(f"  Username: {user.username}")
        print(f"  Password: {new_pw}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
