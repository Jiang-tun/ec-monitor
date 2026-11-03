from fastapi import APIRouter
from sqlalchemy import text

from app.core.response import ok
from app.db.session import engine

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return ok({"status": "up"})


@router.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ok({"db": "up"})
    except Exception as e:
        return {"code": 500, "message": f"db down: {e}", "data": None}
