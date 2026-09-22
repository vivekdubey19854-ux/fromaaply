from __future__ import annotations

import logging
import signal
import time

from .database import SessionLocal
from .website_health_service import WebsiteHealthService

log = logging.getLogger(__name__)
stop = False


def main() -> None:
    global stop
    signal.signal(signal.SIGTERM, lambda *_: globals().__setitem__("stop", True))
    signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("stop", True))
    while not stop:
        db = SessionLocal()
        try:
            WebsiteHealthService(db).check_all()
        except Exception:
            db.rollback()
            log.exception("website health check cycle failed")
        finally:
            db.close()
        for _ in range(300):
            if stop:
                return
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
