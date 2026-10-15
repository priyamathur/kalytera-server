"""
Encrypt connection credentials (Langfuse / LangSmith keys, Slack webhook URLs)
before they're stored. Fernet: AES-128 in CBC mode with an HMAC, so stored
values can't be read or altered without KALYTERA_ENCRYPTION_KEY.

Generate the key once and set it on the API service (never commit it):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import json
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

ENV = "KALYTERA_ENCRYPTION_KEY"


class SecretsUnavailable(RuntimeError):
    """The server has no (or a wrong) encryption key, so connections can't be saved or read."""


def _fernet() -> Fernet:
    key = os.environ.get(ENV, "")
    if not key:
        raise SecretsUnavailable(f"{ENV} is not set on the server, so connections can't be stored safely.")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise SecretsUnavailable(f"{ENV} is not a valid key: {exc}") from exc


def encrypt(values: Dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode()


def decrypt(token: str) -> Dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise SecretsUnavailable("Stored credentials can't be decrypted with the current key.") from exc
