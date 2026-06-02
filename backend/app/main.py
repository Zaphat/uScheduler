from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, log


configure_logging()


def create_app() -> FastAPI:
    app = FastAPI(
        title="uScheduler API",
        description="Appointment scheduling API for automotive dealerships.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    @app.get("/health", tags=["ops"])
    async def health():
        return {"status": "ok"}

    @app.get("/.well-known/jwks.json", tags=["ops"], include_in_schema=False)
    async def jwks():
        """Expose the RSA public key in JWK Set format for JWT authorizers (e.g. API Gateway)."""
        if settings.ALGORITHM != "RS256":
            return {"keys": []}
        pub_pem = settings.JWT_PUBLIC_KEY or settings.JWT_PRIVATE_KEY
        if not pub_pem:
            return {"keys": []}
        try:
            from jose import jwk as jose_jwk
            key = jose_jwk.construct(pub_pem, algorithm="RS256")
            return {"keys": [key.public_key().to_dict()]}
        except Exception:
            log.exception("jwks_construction_failed")
            return {"keys": []}

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log.error("unhandled_exception", path=str(request.url), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred.", "details": {}}},
        )

    return app


app = create_app()
