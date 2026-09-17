from datetime import datetime, timezone

from fastapi import FastAPI

from .anchor_api import router as anchor_router
from .belt_api import router as belt_router


app = FastAPI(title="UWB Device Backend")
app.include_router(anchor_router)
app.include_router(belt_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }
