import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.db import check_db_connection, init_db
from app import metrics
from app.errors import ApiError, error_body, request_id_of
from app.routers import runs, workflows

settings = get_settings()

app = FastAPI(title="Hososhi API", version=settings.app_version)

app.include_router(workflows.router)
app.include_router(runs.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTTP_STATUS_TO_CODE = {
    400: "VALIDATION_ERROR",
    404: "NOT_FOUND",
    409: "INVALID_STATE_TRANSITION",
    422: "AI_OUTPUT_INVALID",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.retryable, request_id_of(request)),
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=error_body(
            "VALIDATION_ERROR",
            "Request payload failed validation.",
            False,
            request_id_of(request),
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException):
    code = HTTP_STATUS_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, detail, exc.status_code >= 500, request_id_of(request)),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=error_body(
            "INTERNAL_ERROR",
            "Unexpected server error.",
            True,
            request_id_of(request),
        ),
    )


@app.on_event("startup")
def on_startup() -> None:
    check_db_connection()
    init_db()


@app.get("/api/v1/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": settings.app_version}


@app.get("/api/v1/meta", tags=["system"])
def meta() -> dict:
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import PurchaseRequest, WorkflowEvent

    with SessionLocal() as db:
        event_count = db.scalar(select(func.count()).select_from(WorkflowEvent)) or 0
        request_count = db.scalar(select(func.count()).select_from(PurchaseRequest)) or 0

    return {
        "product": "Hososhi",
        "version": settings.app_version,
        "dataset_name": settings.dataset_name,
        "dataset_is_synthetic": True,
        "dataset_seed": settings.dataset_seed,
        "event_count": event_count,
        "purchase_request_count": request_count,
        "data_generated_by": "deterministic_synthetic_generator",
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model or None,
        "ai_fallback_active": False,
        "measurement_method": metrics.MEASUREMENT_METHOD,
        "notes": "All data is synthetic and generated for demonstration purposes.",
    }