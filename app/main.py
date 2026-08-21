from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.browse import router as browse_router
from app.api.calendar import router as calendar_router
from app.api.corrections import router as corrections_router
from app.api.debug import router as debug_router
from app.api.emphasis import router as emphasis_router
from app.api.generation import router as generation_router
from app.api.health import router as health_router
from app.api.ingestion import router as ingestion_router
from app.api.mapping import router as mapping_router
from app.api.planning import router as planning_router

app = FastAPI(title="CurriculumOS")
app.include_router(health_router)
app.include_router(ingestion_router)
app.include_router(calendar_router)
app.include_router(mapping_router)
app.include_router(emphasis_router)
app.include_router(planning_router)
app.include_router(corrections_router)
app.include_router(generation_router)
app.include_router(browse_router)
app.include_router(debug_router)

# Minimal demo UI. Mounted last so it doesn't shadow any API route above.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
