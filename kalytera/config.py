import os

DEFAULT_ENDPOINT: str = os.getenv("KALYTERA_API_ENDPOINT", "http://localhost:8000")
REQUEST_TIMEOUT: float = 5.0
ERROR_LOG_PATH: str = os.path.expanduser("~/.kalytera/errors.log")

# "session" = one Haiku call per complete session (free tier, ~$10/10K sessions)
# "step"    = one Haiku call per step (paid tier, granular per-step scores)
EVAL_MODE: str = os.getenv("KALYTERA_EVAL_MODE", "session")

# Set this to use your own Anthropic API key (BYOK) instead of Kalytera's shared key.
# When set, all eval calls for this deployment use this key and are billed to its owner.
BYOK_ANTHROPIC_KEY: str = os.getenv("BYOK_ANTHROPIC_API_KEY", "")

FREE_TIER_SESSION_LIMIT: int = int(os.getenv("FREE_TIER_SESSION_LIMIT", "10000"))
