import sys
import time

from nxtools import log_traceback, critical_error, logging

from .processor import KitsuProcessor, KitsuServerError, KitsuSettingsError


if __name__ == "__main__":
    err = None
    try:
        processor = KitsuProcessor()
    except (KitsuServerError, KitsuSettingsError) as e:
        logging.error(str(e))
    except Exception:
        log_traceback()
    else:
        sys.exit(processor.start_processing())

    time.sleep(10)
    critical_error("Unable to initialize KitsuProcessor. Exiting")
