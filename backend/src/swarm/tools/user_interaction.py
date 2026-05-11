"""User interaction tool — lets agents ask the user a question mid-run.

The agent calls ask_user(...) with a list of questions. The tool:
  1. Generates a unique question_id.
  2. Publishes a 'question' SSE event to the project's Redis channel so the
     frontend can display the question UI.
  3. Polls Redis for the answer key (set by POST /api/projects/{id}/answer).
  4. Returns the user's answers as a JSON string.

New Redis connection per call — matches the pattern used in todo_tools.py.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

import redis.asyncio as redis
from langchain_core.tools import tool

from .workspace_tools import get_project_id

logger = logging.getLogger("tools")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# How long to wait for a user answer before timing out (seconds).
ANSWER_TIMEOUT_SECONDS = int(os.getenv("ASK_USER_TIMEOUT_SECONDS", "300"))
POLL_INTERVAL_SECONDS = 1.0


def _split_options(raw: str) -> list[str]:
    return [
        part.strip(" \t\n\r-•")
        for part in raw.replace(" / ", ",").replace(" or ", ",").split(",")
        if part.strip(" \t\n\r-•")
    ]


def _normalize_question(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        label = str(raw.get("label") or raw.get("question") or raw.get("text") or "").strip()
        raw_type = str(raw.get("type") or raw.get("kind") or raw.get("input_type") or "text").lower()
        options_raw = raw.get("options") or raw.get("choices") or []
        options = [
            str(option.get("label") if isinstance(option, dict) else option).strip()
            for option in options_raw
            if str(option.get("label") if isinstance(option, dict) else option).strip()
        ]
        mapped_type = {
            "select": "single_select",
            "radio": "single_select",
            "choice": "single_select",
            "choices": "single_select",
            "checkbox": "multi_select",
            "checkboxes": "multi_select",
            "multi": "multi_select",
            "multiselect": "multi_select",
            "long_text": "textarea",
            "boolean": "boolean",
            "yes_no": "boolean",
        }.get(raw_type, raw_type)
        if mapped_type not in {"text", "textarea", "single_select", "multi_select", "boolean"}:
            mapped_type = "single_select" if options else "text"
        return {
            "id": str(raw.get("id") or f"q_{abs(hash(label)) % 100000}"),
            "label": label,
            "type": mapped_type,
            "options": options,
            "required": bool(raw.get("required", True)),
            "help": str(raw.get("help") or raw.get("description") or "").strip(),
        }

    label = str(raw).strip()
    lower = label.lower()
    options: list[str] = []
    qtype = "text"

    for marker in ("options:", "choices:", "choose one:", "select one:"):
        if marker in lower:
            start = lower.index(marker) + len(marker)
            options = _split_options(label[start:])
            qtype = "single_select"
            break

    if not options:
        import re

        match = re.search(r"\((?:e\.g\.|for example)\s+([^)]+)\)", label, flags=re.IGNORECASE)
        if match:
            options = _split_options(match.group(1))
            if len(options) >= 2 and any(word in lower for word in ("which", "what", "choose", "select", "prefer", "should i use")):
                qtype = "single_select"

    if "select all" in lower or "choose all" in lower or "multiple" in lower:
        qtype = "multi_select" if options else "textarea"
    elif qtype == "text" and lower.startswith(("do ", "does ", "should ", "would ", "is ", "are ", "can ")):
        qtype = "boolean"
        options = ["Yes", "No"]
    elif qtype == "text" and any(word in lower for word in ("describe", "details", "requirements", "constraints", "notes")):
        qtype = "textarea"

    return {
        "id": f"q_{abs(hash(label)) % 100000}",
        "label": label,
        "type": qtype,
        "options": options,
        "required": True,
        "help": "",
    }


@tool
async def ask_user(questions: list[Any]) -> str:
    """Ask the user one or more questions and wait for their answers.

    Use this tool when you need information from the user that is required
    to continue (e.g., preferred tech stack, language, database engine).

    Args:
        questions: A list of question strings or structured question objects.

    Returns:
        A JSON string with a 'answers' key containing the user's responses
        in the same order as the questions, or an 'error' key on timeout.
    """
    project_id = get_project_id()
    if not project_id:
        return json.dumps({"error": "No active project context — cannot ask user."})

    question_id = str(uuid.uuid4())
    answer_key = f"project:{project_id}:questions:{question_id}:answers"
    channel = f"project:{project_id}:events"
    question_items = [_normalize_question(question) for question in questions]

    event_payload = json.dumps({
        "type": "question",
        "data": {
            "question_id": question_id,
            "questions": [item["label"] for item in question_items],
            "question_items": question_items,
            "schema_version": 2,
        },
    })

    r: redis.Redis | None = None
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)

        # Publish the SSE question event so the frontend shows the question UI.
        await r.publish(channel, event_payload)
        logger.info(
            "[ask_user] Published question event (project=%s, question_id=%s, count=%d)",
            project_id,
            question_id,
            len(questions),
        )

        # Poll for the answer key written by POST /api/projects/{id}/answer.
        elapsed = 0.0
        while elapsed < ANSWER_TIMEOUT_SECONDS:
            raw = await r.get(answer_key)
            if raw is not None:
                try:
                    answers = json.loads(raw)
                except json.JSONDecodeError:
                    answers = [raw]
                logger.info(
                    "[ask_user] Received answers (question_id=%s)", question_id
                )
                return json.dumps({"answers": answers})

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS

        logger.warning(
            "[ask_user] Timed out waiting for answers (question_id=%s)", question_id
        )
        return json.dumps({"error": f"User did not answer within {ANSWER_TIMEOUT_SECONDS}s."})

    except Exception as exc:
        logger.exception("[ask_user] Unexpected error: %s", exc)
        return json.dumps({"error": str(exc)})
    finally:
        if r is not None:
            await r.aclose()
