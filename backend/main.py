from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.jobs import router as jobs_router

app = FastAPI(title="Castify Shorts Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # React dev server, once it exists
        "http://127.0.0.1:5500",   # submission.html served via python -m http.server
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)