from datetime import datetime, timezone
from jose import JWTError, jwt, ExpiredSignatureError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

bearer_scheme = HTTPBearer()


def _signing_key() -> str:
    """Return the key used to sign JWTs (private key for RS256, secret for HS256)."""
    if settings.ALGORITHM == "RS256":
        if not settings.JWT_PRIVATE_KEY:
            raise RuntimeError("JWT_PRIVATE_KEY is required when ALGORITHM=RS256")
        return settings.JWT_PRIVATE_KEY
    return settings.SECRET_KEY


def _verification_key() -> str:
    """Return the key used to verify JWTs (public key for RS256, secret for HS256)."""
    if settings.ALGORITHM == "RS256":
        # Prefer explicit public key; fall back to private key (python-jose can extract
        # the public component from an RSA private key PEM for verification).
        key = settings.JWT_PUBLIC_KEY or settings.JWT_PRIVATE_KEY
        if not key:
            raise RuntimeError("JWT_PUBLIC_KEY or JWT_PRIVATE_KEY is required when ALGORITHM=RS256")
        return key
    return settings.SECRET_KEY


def create_access_token(payload: dict) -> str:
    return jwt.encode(payload, _signing_key(), algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _verification_key(), algorithms=[settings.ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    return decode_token(credentials.credentials)


async def require_customer(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("CUSTOMER", "STAFF", "ADMIN"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user
