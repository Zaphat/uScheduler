from fastapi import HTTPException, status


class SlotUnavailableError(HTTPException):
    def __init__(self, reason: str, detail: dict | None = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "SLOT_UNAVAILABLE",
                    "message": reason,
                    "details": detail or {},
                }
            },
        )


class SlotTakenError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "SLOT_UNAVAILABLE",
                    "message": "A concurrent request won this slot. Please retry.",
                    "details": {"reason": "LOCK_CONTENTION"},
                }
            },
        )


class NotFoundError(HTTPException):
    def __init__(self, resource: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"{resource} not found.", "details": {}}},
        )


class ForbiddenError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Access denied.", "details": {}}},
        )
