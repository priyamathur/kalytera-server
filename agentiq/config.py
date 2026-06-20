import os

DEFAULT_ENDPOINT: str = os.getenv("AGENTIQ_API_ENDPOINT", "http://localhost:8000")
REQUEST_TIMEOUT: float = 5.0
ERROR_LOG_PATH: str = os.path.expanduser("~/.agentiq/errors.log")
