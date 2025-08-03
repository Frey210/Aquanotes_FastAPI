from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from app import models, database
from datetime import datetime, timedelta
import uuid

security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_auth_token(db: Session, user_id: int, expires_hours: int = 720) -> str:
    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
    
    db_token = models.AuthToken(
        token=token,
        user_id=user_id,
        expires_at=expires_at
    )
    
    db.add(db_token)
    db.commit()
    return token

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(database.get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        db_token = db.query(models.AuthToken).filter(
            models.AuthToken.token == token,
            models.AuthToken.expires_at > datetime.utcnow()
        ).first()
        
        if not db_token:
            raise credentials_exception
            
        user = db.query(models.User).filter(
            models.User.id == db_token.user_id
        ).first()
        
        if not user:
            raise credentials_exception
            
        return user
        
    except Exception as e:
        print(f"Authentication error: {str(e)}")
        raise credentials_exception