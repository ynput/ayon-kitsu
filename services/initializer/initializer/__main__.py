import sys
import time

from nxtools import log_traceback, critical_error, logging

from .sync_server import KitsuInitializer, KitsuServerError, KitsuSettingsError

if __name__ == "__main__":
    err = None
    try:
        processor = KitsuInitializer()
    except (KitsuServerError, KitsuSettingsError) as e:
        logging.error(str(e))
    except Exception:
        log_traceback()

    time.sleep(10)
    critical_error("Unable to start KitsuInitializer. Exiting")
