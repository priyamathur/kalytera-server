import os

DEFAULT_ENDPOINT: str = os.getenv("KALYTERA_API_ENDPOINT", "http://localhost:8000")
REQUEST_TIMEOUT: float = 5.0
ERROR_LOG_PATH: str = os.path.expanduser("~/.kalytera/errors.log")
