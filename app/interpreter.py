"""LLM-backed, schema-constrained interpretation of GridWise operator notes."""

import json
import os
import time

from openai import (
    APIError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError
from dotenv import load_dotenv

from app.schemas import Directive

load_dotenv()


SYSTEM_PROMPT = """You interpret GridWise smart-campus operator notes.
Return JSON only, with a `directives` array containing exactly one entry per
input note in the original order. The required number of entries is supplied
in `expected_note_count`. Never omit an irrelevant note: emit a no_op entry
with applies=false for it. Never add extra entries. Each entry must have note_index, applies,
directive_type, structured_adjustment, and explanation.

Allowed directive types and exact adjustments:
- solar_reduction: {\"hours\":[integer 0..23],\"factor\":number 0..1}; factor is
  the usable solar fraction remaining, so an 80% reduction means 0.2.
- minimum_battery_reserve: {\"hours\":[integer 0..23],\"minimum_energy_kwh\":number}
- no_charge_window: {\"hours\":[integer 0..23]}
- no_discharge_window: {\"hours\":[integer 0..23]}
- max_grid_window: {\"hours\":[integer 0..23],\"max_grid_kwh\":number}
- no_op: null

Whole-hour time windows include the start and exclude the end. Do not invent
facts or directives. For irrelevant notes emit only no_op with applies false.
For all other directives emit applies true. Hours must be unique and sorted."""


class InterpretationError(RuntimeError):
    """A controlled failure while calling or decoding the required LLM."""


def _client() -> OpenAI:
    provider = (os.getenv("LLM_PROVIDER") or "google").strip().lower()
    if provider == "google":
        api_key = os.getenv("GOOGLE_API_KEY")
        base_url = os.getenv(
            "LLM_BASE_URL"
        ) or "https://generativelanguage.googleapis.com/v1beta/openai/"
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("LLM_BASE_URL") or None
    else:
        raise InterpretationError(
            "Unsupported LLM_PROVIDER. Use google or openai."
        )

    if not api_key:
        raise InterpretationError(
            f"{provider.title()} API key is not configured"
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def interpret_notes(notes: list[str], capacity: float) -> list[Directive]:
    """Use a language-capable model; downstream code validates its output."""
    payload = {
        "battery_capacity_kwh": capacity,
        "expected_note_count": len(notes),
        "operator_notes": [
            {"note_index": index, "text": note}
            for index, note in enumerate(notes)
        ],
    }
    provider = (os.getenv("LLM_PROVIDER") or "google").strip().lower()
    model = os.getenv("LLM_MODEL") or (
        "gemini-3.6-flash" if provider == "google" else "gpt-4o-mini"
    )
    try:
        client = _client()
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload)},
                    ],
                )
                break
            except InternalServerError as exc:
                if attempt == 2:
                    raise InterpretationError(
                        f"{provider.title()} is temporarily unavailable. Please try again shortly."
                    ) from exc
                time.sleep(2 ** attempt)
        content = response.choices[0].message.content
        if not content:
            raise InterpretationError("LLM returned no interpretation")
        decoded = json.loads(content)
        return [Directive.model_validate(item) for item in decoded["directives"]]
    except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise InterpretationError("LLM returned invalid directive data") from exc
    except RateLimitError as exc:
        if "insufficient_quota" in str(exc) or "credit_balance_exhausted" in str(exc):
            raise InterpretationError(
                f"{provider.title()} API quota is exhausted. Add credits or configure a funded API key."
            ) from exc
        raise InterpretationError(
            f"{provider.title()} rate limit reached. Please try again shortly."
        ) from exc
    except NotFoundError as exc:
        raise InterpretationError(
            f"{provider.title()} model '{model}' is unavailable. Check LLM_MODEL."
        ) from exc
    except (APIError, APIStatusError, APITimeoutError) as exc:
        raise InterpretationError("LLM interpretation request failed") from exc
