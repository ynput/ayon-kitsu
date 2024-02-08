import sys
import time

from kitsu_common.utils import (
    KitsuServerError,
    KitsuSettingsError,
)
from nxtools import (
    critical_error,
    log_traceback,
    logging,
)

from .listener import KitsuListener


def main():
    try:
        listener.start_listening()
    except Exception:
        log_traceback()
    sys.exit()


if __name__ == "__main__":
    err = None
    try:
        listener = KitsuListener()
    except (KitsuServerError, KitsuSettingsError) as e:
        logging.error(str(e))
    except Exception:
        log_traceback()
    else:
        main()

    time.sleep(10)
    critical_error("Unable to initialize KitsuListener. Exiting")
