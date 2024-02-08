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

from .processor import (
    KitsuProcessor,
)


def main():
    try:
        processor.start_processing()
    except Exception:
        log_traceback()
    sys.exit()


if __name__ == "__main__":
    err = None
    try:
        processor = KitsuProcessor()
    except (KitsuServerError, KitsuSettingsError) as e:
        logging.error(str(e))
    except Exception:
        log_traceback()
    else:
        main()

    time.sleep(10)
    critical_error("Unable to initialize KitsuProcessor. Exiting")
