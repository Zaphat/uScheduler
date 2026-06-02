from fastapi import APIRouter, Depends, HTTPException, status
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


@router.get("/dealerships/{dealership_id}", response_model=DealershipOut)
async def get_dealership(
    dealership_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    repo = ReferenceRepository(db)
    dealership = await repo.get_dealership(dealership_id)
    if not dealership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Dealership not found.", "details": {}}},
        )
    return dealership


@router.get("/dealerships/{dealership_id}/service-types", response_model=list[ServiceTypeOut])
async def list_service_types(
    dealership_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    repo = ReferenceRepository(db)
    return await repo.list_service_types_for_dealership(dealership_id)


@router.get("/service-types/{service_type_id}", response_model=ServiceTypeOut)
async def get_service_type(
    service_type_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_customer),
):
    repo = ReferenceRepository(db)
    service_type = await repo.get_service_type(service_type_id)
    if not service_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "ServiceType not found.", "details": {}}},
        )
    return service_type
