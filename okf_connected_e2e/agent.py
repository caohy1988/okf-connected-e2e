"""ADK agent on Gemini that answers one governed finance question through the connected run.

The agent has exactly one tool. The tool runs the connected end-to-end path (the spike's `okf_bq_graph.connected`) and
returns the validated, identifier-free payload from `payload.tool_payload`. The number reaches the model only when the
run's enforcing consumer released it; otherwise the payload says REFUSED and why.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from .payload import tool_payload

APP_NAME = "okf_connected_e2e"
INSTRUCTION = (
    "You answer questions about Acme's governed gross margin. The data is a synthetic fixture. "
    "Always call governed_gross_margin before answering; never compute, estimate or recall a number yourself. "
    "If the tool's decision is RELEASED, quote its answer verbatim and say the receipt verdict. "
    "If the decision is REFUSED, say the number is withheld and give the reason. "
    "Then summarise in two or three short sentences what the run checked: the Catalog read, the pinned publication, "
    "governed retrieval, the fact read-back, the receipt, and that after access was revoked a fresh request, a bypass "
    "and the stored receipt were all refused. Use only the tool's fields. Do not print identifiers, SQL, principals or paths. "
    "State that the data is synthetic, the APIs are live GCP when the tool says so, and that this is one run, not readiness."
)
_JAN_2026 = re.compile(r"(2026-01(?:-\d\d)?|jan(?:uary)?\.?\s*2026)", re.IGNORECASE)


def is_declared_period(period: str) -> bool:
    return bool(_JAN_2026.search(period or ""))


def make_tool(run: Callable[[], dict], on_payload: Optional[Callable[[dict], None]] = None) -> Callable[[str], dict]:
    """`run()` performs the connected run and returns `connected.summary(out)`."""

    def governed_gross_margin(period: str) -> dict:
        """Acme's governed gross margin for a period, released only through the connected OKF path.

        Args:
          period: the reporting period. Only January 2026 ("2026-01") is declared by the pinned computation.

        Returns:
          The consumer decision, the released answer when RELEASED, the receipt verdict and the access and revocation
          checks of the run, with no identifiers.
        """
        if not is_declared_period(period):
            return {"decision": "REFUSED", "answer": None,
                    "reason": "only the January 2026 request is declared by the pinned computation; nothing was run"}
        payload = tool_payload(run())
        if on_payload is not None:
            on_payload(payload)
        return payload

    return governed_gross_margin


def build_agent(tool: Callable[..., dict], model_id: str) -> Any:
    from google.adk.agents import Agent
    from google.adk.models import Gemini
    from google.genai import types

    return Agent(
        name="okf_connected_e2e_agent",
        model=Gemini(model=model_id, retry_options=types.HttpRetryOptions(attempts=3)),
        description="Answers one governed gross-margin question through the connected OKF path; synthetic data.",
        instruction=INSTRUCTION,
        tools=[tool],
    )


async def ask(agent: Any, question: str, on_event: Callable[..., None] = lambda *a, **k: None) -> str:
    """Run one question; report tool calls and results through `on_event`; return the final text."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id="okf-e2e-demo")
    content = types.Content(role="user", parts=[types.Part(text=question)])
    final: list[str] = []
    async for event in runner.run_async(user_id="okf-e2e-demo", session_id=session.id, new_message=content):
        for part in (getattr(getattr(event, "content", None), "parts", None) or []):
            if getattr(part, "function_call", None):
                on_event("tool_call", name=part.function_call.name, args=dict(part.function_call.args or {}))
            elif getattr(part, "function_response", None):
                on_event("tool_result", name=part.function_response.name)
            elif getattr(part, "text", None) and event.is_final_response():
                final.append(part.text)
    closer = getattr(runner, "close", None)
    if closer:
        maybe = closer()
        if hasattr(maybe, "__await__"):
            await maybe
    return "".join(final).strip()
