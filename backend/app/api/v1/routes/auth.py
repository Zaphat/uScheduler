from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.schemas import CustomerCreate, CustomerOut, LoginRequest, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=CustomerOut, status_code=201)
async def register(payload: CustomerCreate, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    customer = await service.register(payload)
    return customer


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    token = await service.login(payload.email, payload.password)
    return TokenResponse(access_token=token)
