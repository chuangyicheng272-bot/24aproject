import os


FLASK_BASE_URL = os.getenv("FLASK_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
FLASK_RANGE_URL = f"{FLASK_BASE_URL}/api/uwb/range"
FLASK_BELT_STATUS_URL = f"{FLASK_BASE_URL}/api/belt/status"
FORWARD_TIMEOUT_SECONDS = 3
