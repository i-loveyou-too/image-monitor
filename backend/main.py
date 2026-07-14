from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_database
from routers import jobs, sellers

init_database()

app = FastAPI(title="이미지 도용 모니터링 시스템", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sellers.router)
app.include_router(jobs.router)


@app.get("/health")
def health():
    return {"status": "ok"}
