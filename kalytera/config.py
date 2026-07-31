import os

DEFAULT_ENDPOINT: str = os.getenv("KALYTERA_API_ENDPOINT", "http://localhost:8000")
REQUEST_TIMEOUT: float = 5.0
ERROR_LOG_PATH: str = os.path.expanduser("~/.kalytera/errors.log")

# ---------------------------------------------------------------------------
# Eval mode — controls free vs paid tier cost profile
# ---------------------------------------------------------------------------

# "session" = one LLM call per complete session (free tier, ~$10/10K sessions)
# "step"    = one LLM call per step (paid tier, granular per-step scores)
EVAL_MODE: str = os.getenv("KALYTERA_EVAL_MODE", "session")

FREE_TIER_SESSION_LIMIT: int = int(os.getenv("FREE_TIER_SESSION_LIMIT", "10000"))

# ---------------------------------------------------------------------------
# Judge provider — Kalytera is LLM-agnostic
# ---------------------------------------------------------------------------

# Which LLM to use as the quality judge.
# Options: "anthropic" (default) | "openai" | "gemini"
JUDGE_PROVIDER: str = os.getenv("KALYTERA_JUDGE_PROVIDER", "anthropic")

# Override the specific model within the provider. Leave empty to use the default.
# Anthropic default: claude-haiku-4-5-20251001
# OpenAI default:    gpt-4o-mini
# Gemini default:    gemini-1.5-flash
JUDGE_MODEL: str = os.getenv("KALYTERA_JUDGE_MODEL", "")

# ---------------------------------------------------------------------------
# BYOK (Bring Your Own API Key)
# LLM inference costs are billed directly to your provider account.
# Kalytera charges a platform fee separately (dashboard, SDK, pattern detection).
# ---------------------------------------------------------------------------

BYOK_ANTHROPIC_KEY: str = os.getenv("BYOK_ANTHROPIC_API_KEY", "")
BYOK_OPENAI_KEY: str = os.getenv("BYOK_OPENAI_API_KEY", "")
BYOK_GEMINI_KEY: str = os.getenv("BYOK_GOOGLE_API_KEY", "")
