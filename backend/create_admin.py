"""Create or promote an administrator account from a local terminal.

Run from the project root with:
    python -m backend.create_admin
"""
from getpass import getpass

from .auth import hash_password
from .database import SessionLocal, Base, engine
from . import models  # noqa: F401 - register SQLAlchemy models
from .models import User


def main():
    Base.metadata.create_all(bind=engine)
    email = input("Admin email: ").strip().lower()
    full_name = input("Admin full name: ").strip()
    password = getpass("Admin password (minimum 8 characters): ")
    confirm = getpass("Confirm password: ")

    if not email or not full_name:
        raise SystemExit("Email and full name are required.")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")
    if password != confirm:
        raise SystemExit("Passwords do not match.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                full_name=full_name,
                email=email,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
            db.add(user)
        else:
            user.full_name = full_name
            user.password_hash = hash_password(password)
            user.role = "admin"
            user.is_active = True
        db.commit()
        print(f"Administrator account ready for {email}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
