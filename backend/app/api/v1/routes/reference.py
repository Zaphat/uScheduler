from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_customer
from app.db.session import get_db
from app.repositories.appointment_repo import ReferenceRepository
from app.schemas.schemas import DealershipOut, ServiceTypeOut

router = APIRouter(tags=["reference"])


@router.get("/dealerships", response_model=list[DealershipOut])
async def list_dealerships(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    repo = ReferenceRepository(db)
    return await repo.list_dealerships()


@router.get("/dealerships/{dealership_id}/service-types", response_model=list[ServiceTypeOut])
async def list_service_types(
    dealership_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    repo = ReferenceRepository(db)
    return await repo.list_service_types_for_dealership(dealership_id)
