from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_customer
from app.db.session import get_db
from app.schemas.schemas import (
    AppointmentCreate, AppointmentOut, AppointmentCancelOut,
    AppointmentListOut, AvailabilityOut, SlotOut, Pagination,
)
from app.services.booking_service import BookingService

router = APIRouter(tags=["appointments"])


@router.get("/availability", response_model=AvailabilityOut)
async def check_availability(
    dealership_id: str = Query(...),
    service_type_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    service = BookingService(db)
    slots = await service.check_availability(dealership_id, service_type_id, date)
    return AvailabilityOut(
        dealership_id=dealership_id,
        service_type_id=service_type_id,
        date=date,
        slots=[SlotOut(start=s, end=e) for s, e in slots],
    )


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
):
    service = BookingService(db)
    appt = await service.create_appointment(
        payload,
        customer_id=user["sub"],
        idempotency_key=x_idempotency_key,
    )
    return appt


@router.get("/appointments", response_model=AppointmentListOut)
async def list_appointments(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    service = BookingService(db)
    appts, total = await service.list_appointments(user["sub"], status, page, limit)
    return AppointmentListOut(
        data=appts,
        pagination=Pagination(page=page, limit=limit, total=total),
    )


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    service = BookingService(db)
    return await service.get_appointment(
        appointment_id,
        user["sub"],
        user.get("role", "CUSTOMER"),
        dealership_id=user.get("dealership_id"),
    )


@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentCancelOut)
async def cancel_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    service = BookingService(db)
    return await service.cancel_appointment(appointment_id, user["sub"])
