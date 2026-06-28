"""Reset admin password to admin123"""
import sys
sys.path.insert(0, '.')

from app.db.base import SessionLocal
from app.models.sys import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

if __name__ == "__main__":
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "admin@smartua.com").first()
        if user:
            hashed = pwd_context.hash("admin123")
            user.password_hash = hashed
            db.commit()
            print(f"Password reset for admin@smartua.com")
            print(f"Hash: {hashed}")
        else:
            print("User not found")
    finally:
        db.close()
