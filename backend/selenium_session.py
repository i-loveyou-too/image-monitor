"""Minimal Selenium fallback session, used ONLY for platforms where a headful
Playwright persistent context (browser_session.py) still gets blocked.

This exists to answer one narrow question per such platform: does a real
Chrome window driven by Selenium (with the automation-detection switches
Chrome ships turned off) reach the product page where Playwright's CDP
connection gets fingerprinted and blocked? It is not a replacement for the
Playwright-based adapters — see adapters/auction.py for the one adapter that
currently needs it.
"""

import atexit
import os
import threading
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

DEFAULT_PROFILE_DIR = r"C:\image-monitor\chrome-profile-selenium"


class SeleniumSessionManager:
    """Process-wide singleton that owns one headful, persistent Selenium
    Chrome driver. Same reuse/single-instance/sequential-task contract as
    BrowserSessionManager."""

    _instance: "SeleniumSessionManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, profile_dir: str = DEFAULT_PROFILE_DIR):
        self._profile_dir = profile_dir
        self._driver = None
        self._task_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._shutdown_registered = False

    @classmethod
    def instance(cls) -> "SeleniumSessionManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_driver(self):
        with self._state_lock:
            if self._driver is not None:
                try:
                    _ = self._driver.window_handles  # cheap liveness check
                    return self._driver
                except Exception:
                    # The Chrome process/session died underneath us (crash,
                    # manual close, etc.) — drop the stale handle and relaunch
                    # below instead of failing every future crawl.
                    self._driver = None
            os.makedirs(self._profile_dir, exist_ok=True)
            options = Options()
            options.add_argument(f"--user-data-dir={self._profile_dir}")
            options.add_argument("--start-maximized")
            # Removes the "Chrome is being controlled by automated test
            # software" infobar / the automation extension. This is a stock
            # Chrome/Selenium option, not a stealth/fingerprint-spoofing
            # plugin — it just stops Chrome from actively advertising the
            # automation state some bot-detection heuristics key off of.
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            self._driver = webdriver.Chrome(options=options)
            self._driver.set_window_size(1440, 1000)
            if not self._shutdown_registered:
                atexit.register(self.shutdown)
                self._shutdown_registered = True
            return self._driver

    @contextmanager
    def tab_session(self):
        """Run one crawl task in a fresh tab of the shared driver, closing
        that tab afterward and returning focus to the original window."""
        with self._task_lock:
            driver = self._ensure_driver()
            original_handle = driver.current_window_handle
            driver.switch_to.new_window("tab")
            try:
                yield driver
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
                try:
                    driver.switch_to.window(original_handle)
                except Exception:
                    pass

    def shutdown(self):
        with self._state_lock:
            if self._driver is not None:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None
