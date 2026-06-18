import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database import create_tables
from middleware.tracing import RequestTracingMiddleware
from routers import documents, auth, health

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        f"Starting {settings.APP_NAME} v{settings.APP_VERSION} "
        f"[{settings.ENVIRONMENT}]"
    )
    await create_tables()
    logger.info("Database tables verified.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
**KYC Pipeline** handles identity document upload, OCR extraction, and cross-validation for the digital lending platform.

## Document flow
1. Client uploads a document via 'POST /api/v1/applications/{id}/documents'
2. API validates file type/size, checks for duplicates, uploads to S3, returns **202 Accepted**
3. Background task runs OCR, cross-validates fields against declared data, masks PII
4. Document status moves to 'verified', 'flagged', or 'unreadable'
5. Flagged documents enter the manual review for ops

## Supported document types
'aadhaar' | 'pan' | 'salary_slip' | 'bank_statement' | 'passport' | 'voter_id'

## Authentication
All endpoints require a **Bearer JWT**. Get one from 'POST /api/v1/auth/login'.
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(RequestTracingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"Unhandled exception [{request_id}]: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        },
    )

app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(documents.router, prefix="/api/v1/applications", tags=["KYC Documents"])

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
