from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.jobs import router as jobs_router
from object_storage import ensure_bucket_exists, ensure_incomplete_upload_lifecycle_rule

app = FastAPI(title="Castify Shorts Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)


@app.on_event("startup")
def on_startup():
    ensure_bucket_exists()
    ensure_incomplete_upload_lifecycle_rule()