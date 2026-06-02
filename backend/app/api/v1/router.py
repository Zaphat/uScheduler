from fastapi import APIRouter
from app.api.v1.routes import auth, appointments, reference

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(appointments.router)
api_router.include_router(reference.router)
