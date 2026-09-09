import argparse
from pathlib import Path

from app.auth import get_password_hash
from app.database import SessionLocal
from app.models import User


def read_credentials(path: str) -> tuple[str, str]:
    values = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(values) != 2 or "@" not in values[0] or len(values[1]) < 8:
        raise ValueError("Credential file must contain email and password on separate lines")
    return values[0].lower(), values[1]


def main():
    parser = argparse.ArgumentParser(description="Create or promote an Aquanotes admin.")
    parser.add_argument("email", nargs="?")
    parser.add_argument("--credentials-file")
    args = parser.parse_args()

    if bool(args.email) == bool(args.credentials_file):
        parser.error("provide either email or --credentials-file")

    email, password = read_credentials(args.credentials_file) if args.credentials_file else (args.email.lower(), None)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            if not password:
                raise SystemExit(f"User not found: {email}")
            user = User(
                name="Super Admin Aquanotes",
                email=email,
                password_hash=get_password_hash(password),
                role="admin",
                email_verified=True,
            )
            db.add(user)
        elif password:
            user.password_hash = get_password_hash(password)
        user.role = "admin"
        user.email_verified = True
        db.commit()
        print("Super admin ready")
    finally:
        db.close()


if __name__ == "__main__":
    main()
