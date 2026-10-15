"""
Auto-instrumentation: kalytera.init() finds the agent frameworks you have
installed and hooks into each one, so there is nothing else to add.

Each integration does two things through the framework's own extension points:
- See: every run becomes one Kalytera session (named after the agent), with the
  tool calls made in it, scored when the run ends.
- Block: every tool call is checked against your rules first. A stopped call
  doesn't run; the model gets the rule's reason back and tells the user.
"""
import importlib
import importlib.metadata
import re
import uuid
from typing import Callable, Dict, List, Optional

from .. import tracer

# Integration name → (pip package that must be installed, module with install()).
# Checked by package, not module name: plenty of apps have their own "agents" folder.
_INTEGRATIONS: Dict[str, tuple] = {
    "OpenAI Agents SDK": ("openai-agents", "kalytera.integrations.openai_agents"),
    "LangChain / LangGraph": ("langchain-core", "kalytera.integrations.langchain"),
}
_installed: List[str] = []


def instrument(only: Optional[List[str]] = None) -> List[str]:
    """Hook into every supported framework that is installed. Safe to call twice."""
    for name, (needs, module) in _INTEGRATIONS.items():
        if name in _installed or (only is not None and name not in only):
            continue
        try:
            try:
                importlib.metadata.version(needs)
            except importlib.metadata.PackageNotFoundError:
                continue
            installer: Callable[[], bool] = importlib.import_module(module).install
            if installer():
                _installed.append(name)
        except Exception as exc:  # a framework we can't hook must never break the app
            tracer._notify(f"instrument_{name}", f"⚠ Kalytera: couldn't hook into {name}: {exc}")
    return list(_installed)


def agent_id_for(name: Optional[str]) -> str:
    """
    The agent_id for a framework agent. kalytera.init(agent_id=...) wins; otherwise
    the agent's own name, made unique to your key ("Refund bot" -> "refund-bot-3fa2c1")
    so two companies' agents called "Assistant" never share data.
    """
    if tracer._agent_id_explicit:
        return tracer._agent_id
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40] or "agent"
    return tracer.key_scoped(slug)


def new_session_id(conversation: Optional[str] = None) -> str:
    """One run = one session. Runs in the same conversation share a searchable prefix."""
    run = uuid.uuid4().hex[:8]
    return f"{conversation}-{run}" if conversation else run
