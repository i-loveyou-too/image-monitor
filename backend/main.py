from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from browser_session import BrowserSessionManager
from database import init_database
from routers import jobs, sellers
from selenium_session import SeleniumSessionManager

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


@app.on_event("shutdown")
def shutdown_browser_sessions():
    # The Auction/Smartstore adapters keep a headful Chrome window (Playwright
    # and/or Selenium) alive across requests; make sure it and its process
    # actually go away when the server stops, instead of relying solely on
    # atexit (which doesn't always run on every termination path).
    BrowserSessionManager.instance().shutdown()
    SeleniumSessionManager.instance().shutdown()
