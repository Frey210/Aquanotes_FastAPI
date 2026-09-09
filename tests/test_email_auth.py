import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app import auth, models, schemas
from app.database import Base
from app.routers import users


class EmailAuthTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user = models.User(
            name="Test User",
            email="user@example.com",
            password_hash=auth.get_password_hash("PasswordLama123"),
            email_verified=True,
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_reset_token_is_hashed_single_use_and_revokes_sessions(self):
        self.db.add(models.AuthToken(
            token="existing-session",
            user_id=self.user.id,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ))
        token = users._new_email_token(self.db, self.user.id, "reset")
        self.db.commit()

        stored = self.db.query(models.EmailToken).one()
        self.assertNotEqual(stored.token_hash, token)
        users.confirm_password_reset(
            schemas.PasswordResetConfirm(token=token, password="PasswordBaru123"),
            self.db,
        )

        self.assertTrue(auth.verify_password("PasswordBaru123", self.user.password_hash))
        self.assertEqual(self.db.query(models.AuthToken).count(), 0)
        self.assertIsNotNone(stored.used_at)
        self.assertIsNone(users._find_email_token(self.db, token, "reset"))

    def test_web_login_requires_verification_without_changing_legacy_login(self):
        self.user.email_verified = False
        self.db.commit()
        credentials = schemas.UserLogin(email=self.user.email, password="PasswordLama123")

        legacy = users.login(credentials, self.db)
        self.assertIn("access_token", legacy)
        with self.assertRaises(HTTPException) as context:
            users.login_web(credentials, self.db)
        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
