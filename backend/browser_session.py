"""Shared headful, persistent Chrome browser session.

Some platforms' bot-detection reacts differently to a headless, throwaway
browser context than to a real, visible Chrome window with a profile that
persists across runs (cookies/local storage/session survive between crawls,
same as a human re-opening Chrome). This module manages exactly one such
browser instance for the whole process: a single persistent context is
launched on first use and reused by every subsequent caller, and everything
is torn down on process exit.

Playwright's sync API pins a browser/page to the OS thread that launched it;
calling its methods from a different thread raises a greenlet error, and
FastAPI's threadpool executor reuses worker threads across unrelated
requests. So instead of handing a Page object back to whatever thread called
in (which could later collide with another adapter's own independent
`sync_playwright()` call landing on that same reused thread), every actual
browser operation runs inside ONE dedicated, long-lived worker thread owned
by this manager; callers submit a function to run against the page and block
for the result. That keeps this persistent driver's thread-affinity
permanently isolated from the temporary, throwaway Playwright sessions the
other adapters (11st/GS SHOP/CJ온스타일) create on whatever thread FastAPI
happens to hand them.

MVP scope: crawl tasks that use this session are processed strictly one at a
time (`run_task()` is serialized by a single lock) — no concurrent headful
crawls.
"""

import atexit
import os
import queue
import threading

from playwright.sync_api import sync_playwright

DEFAULT_PROFILE_DIR = r"C:\image-monitor\chrome-profile"
DEFAULT_VIEWPORT = {"width": 1440, "height": 1000}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_SHUTDOWN_SENTINEL = object()


class BrowserSessionManager:
    """Process-wide singleton that owns one headful, persistent Chrome context,
    driven entirely from a single dedicated worker thread."""

    _instance: "BrowserSessionManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, profile_dir: str = DEFAULT_PROFILE_DIR):
        self._profile_dir = profile_dir
        self._task_lock = threading.Lock()  # serializes crawl tasks (MVP: sequential)
        self._state_lock = threading.Lock()  # guards worker thread start/stop
        self._worker_thread: threading.Thread | None = None
        self._call_queue: "queue.Queue" = queue.Queue()
        self._shutdown_registered = False

    @classmethod
    def instance(cls) -> "BrowserSessionManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_worker(self) -> None:
        with self._state_lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            ready = threading.Event()
            self._worker_thread = threading.Thread(
                target=self._worker_loop, args=(ready,), daemon=True, name="playwright-persistent"
            )
            self._worker_thread.start()
            ready.wait(timeout=60)
            if not self._shutdown_registered:
                atexit.register(self.shutdown)
                self._shutdown_registered = True

    def _worker_loop(self, ready: threading.Event) -> None:
        os.makedirs(self._profile_dir, exist_ok=True)
        playwright = sync_playwright().start()
        launch_kwargs = dict(
            user_data_dir=self._profile_dir,
            headless=False,
            viewport=DEFAULT_VIEWPORT,
            user_agent=USER_AGENT,
            args=["--start-maximized"],
        )
        try:
            context = playwright.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
        except Exception:
            # Installed Google Chrome not found under the "chrome" channel;
            # fall back to Playwright's bundled Chromium, still headful/persistent.
            context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        ready.set()

        try:
            while True:
                item = self._call_queue.get()
                if item is _SHUTDOWN_SENTINEL:
                    break
                func, result_box, done = item
                page = context.new_page()
                try:
                    result_box["value"] = func(page)
                except BaseException as exc:  # noqa: BLE001 - relayed to the caller's thread
                    result_box["error"] = exc
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                    done.set()
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                playwright.stop()
            except Exception:
                pass

    def run_task(self, func):
        """Run func(page) on the dedicated worker thread against a fresh tab
        in the shared persistent context, and return its result. Tasks are
        processed one at a time."""
        with self._task_lock:
            self._ensure_worker()
            result_box: dict = {}
            done = threading.Event()
            self._call_queue.put((func, result_box, done))
            done.wait()
            if "error" in result_box:
                raise result_box["error"]
            return result_box.get("value")

    def shutdown(self) -> None:
        with self._state_lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                self._call_queue.put(_SHUTDOWN_SENTINEL)
                self._worker_thread.join(timeout=15)
            self._worker_thread = None
