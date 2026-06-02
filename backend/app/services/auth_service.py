from datetime import datetime, timezone, timedelta
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.security import create_access_token
from app.models.models import Customer
from app.schemas.schemas import CustomerCreate


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def register(self, payload: CustomerCreate) -> Customer:
        existing = (await self.session.execute(
            select(Customer).where(Customer.email == payload.email)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

        customer = Customer(
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            password_hash=hash_password(payload.password),
        )
        self.session.add(customer)
        await self.session.commit()
        await self.session.refresh(customer)
        return customer

    async def login(self, email: str, password: str) -> str:
        customer = (await self.session.execute(
            select(Customer).where(Customer.email == email)
        )).scalar_one_or_none()
        if not customer or not verify_password(password, customer.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = create_access_token({
            "sub": customer.id,
            "role": "CUSTOMER",
            "dealership_id": None,
            "exp": int(expire.timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
        })
        return token
