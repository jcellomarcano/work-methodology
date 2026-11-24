"""Upload of an export file, with retries on a timeout."""
import time

from export.client import UploadTimeout, upload

# A partner outage rarely lasts longer than a few seconds, so three
# attempts cover it without holding the nightly job for minutes.
FIRST_WAIT_SECONDS = 1
MAX_ATTEMPTS = 3


def upload_with_retry(path: str, destination: str) -> bool:
    """True when the file is at the destination, False when every attempt timed out."""
    wait = FIRST_WAIT_SECONDS
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            upload(path, destination)
            return True
        except UploadTimeout:
            if attempt == MAX_ATTEMPTS:
                return False
            time.sleep(wait)
            wait *= 2
    return False
