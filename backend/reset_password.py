"""Reset ALL users password to admin123"""
import sys
sys.path.insert(0, '.')

from app.db.base import SessionLocal
from app.models.sys import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

if __name__ == "__main__":
    db = SessionLocal()
    try:
        users = db.query(User).all()
        hashed = pwd_context.hash("admin123")
        for user in users:
            user.password_hash = hashed
            print(f"Password reset for: {user.email}")
        db.commit()
        print(f"\nAll {len(users)} users password reset to: admin123")
    finally:
        db.close()
