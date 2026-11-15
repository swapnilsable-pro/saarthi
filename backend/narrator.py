"""Optional Claude narrator (IMPLEMENTATION_PLAN.md §11 step 10). OFF unless SAARTHI_NARRATOR=1.

It turns one decided idea's recorded evidence into plain English for a newcomer. It never decides,
never creates ideas or orders, and is told to use only the numbers it is given. Credentials are the
Anthropic SDK's usual resolution (ANTHROPIC_API_KEY, or an `ant auth login` profile); Saarthi never
asks for or stores a key.
"""
from __future__ import annotations

import json
import os
from typing import Any

MODEL = "claude-opus-5-5"

SYSTEM = """You explain one paper-trading idea from an educational NSE (India) trading simulator to a beginner.

Rules:
- Use ONLY the facts in the JSON you are given. Do not add prices, news, opinions or predictions of your own.
- This is not investment advice and no real order can be placed. Never tell the reader to buy or sell; describe what the tools found and why the verdict followed from the stated rule.
- Explain any jargon you use (R, opening range, stop, net of costs, GTT) in a few words the first time.
- Say plainly how much the evidence can be trusted: small samples, synthetic test data, missing checks.
- 120 to 180 words, short paragraphs, no headings, no bullet points, Indian number formatting with the rupee sign."""


def enabled() -> bool:
    return os.environ.get("SAARTHI_NARRATOR", "0") == "1"


def _facts(d: dict[str, Any]) -> dict[str, Any]:
    detail = d.get("detail") or {}
    return {
        "symbol": d["symbol"], "setup": d["setup"], "session_day": d["session_day"], "decided_at": d["decided_at"],
        "verdict": d["verdict"], "deciding_reason": detail.get("reason"), "verdict_rule": detail.get("verdict_rule"),
        "synthetic_test_data": detail.get("synthetic"),
        "checks": [{k: g.get(k) for k in ("step", "label", "status", "summary", "required")} for g in detail.get("gates", [])],
        "plan": d.get("plan"), "odds": d.get("odds"), "costs": d.get("costs"),
        "timing": detail.get("timing", [])[:12], "market_mood": detail.get("mood"),
    }


class NarratorError(RuntimeError):
    pass


def narrate(decision: dict[str, Any]) -> dict[str, Any]:
    if not enabled():
        raise NarratorError("The Claude narrator is off. Start the API with SAARTHI_NARRATOR=1 to turn it on.")
    import anthropic

    client = anthropic.Anthropic()
    facts = json.dumps(_facts(decision), default=str, ensure_ascii=False)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "low"},          # short explanatory text: low effort is enough
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                       # on a refusal, the API retries on a suitable model
            messages=[{"role": "user", "content": f"Explain this idea:\n<idea>\n{facts}\n</idea>"}],
        )
    except anthropic.AuthenticationError:
        raise NarratorError("No valid Anthropic credentials. Set ANTHROPIC_API_KEY or run `ant auth login`.")
    except anthropic.RateLimitError:
        raise NarratorError("Rate limited by the Claude API. Try again in a minute.")
    except anthropic.APIStatusError as e:
        raise NarratorError(f"Claude API error {e.status_code}.")
    except anthropic.APIConnectionError:
        raise NarratorError("Could not reach the Claude API.")
    if response.stop_reason == "refusal":
        raise NarratorError("Claude declined to narrate this idea.")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return {"text": text, "model": response.model, "request_id": response._request_id}
