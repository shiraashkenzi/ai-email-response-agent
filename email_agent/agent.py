"""Agent decision layer: maintains conversation state and decides when and how to use tools."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from email_agent.llm_service import LLMService
from email_agent.tools import (
    build_tool_registry,
    execute_tool,
    tools_to_openai_schema,
)
from email_agent.gmail_service import GmailService

logger = logging.getLogger(__name__)

# Cap tool result size to avoid exceeding model context (e.g. 8192 tokens)
MAX_TOOL_RESULT_CHARS = 3500
TRUNCATE_SUFFIX = "\n[... truncated to fit context limit]"

# Model limit 8192 = messages + tools (~586) + completion. Cap messages so total fits.
COMPLETION_MAX_TOKENS = 512   # leaves more room for conversation
MAX_MESSAGE_TOKENS = 7000     # 7000 + 586 + 512 = 8098 < 8192
CHARS_PER_TOKEN_ESTIMATE = 4


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (conservative)."""
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


def _messages_token_estimate(messages: List[Dict[str, Any]]) -> int:
    """Estimate total tokens for a message list."""
    total = 0
    for m in messages:
        role = m.get("role", "")
        total += _estimate_tokens(role)
        if m.get("content"):
            total += _estimate_tokens(str(m["content"]))
        for tc in m.get("tool_calls") or []:
            total += _estimate_tokens(tc.get("id", ""))
            total += _estimate_tokens(str(tc.get("function", {})))
        if m.get("tool_call_id"):
            total += _estimate_tokens(m["tool_call_id"])
            total += _estimate_tokens(str(m.get("content", "")))
    return total


def _trim_messages_to_fit(messages: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
    """Keep system + suffix of conversation so estimated tokens <= max_tokens.
    Drops oldest messages; when dropping an assistant with tool_calls, drops
    the following tool messages too so the API never sees orphan tool results.
    """
    if not messages:
        return messages
    system = messages[0] if messages[0].get("role") == "system" else None
    rest = list(messages[1:] if system else messages)
    if not rest:
        return messages
    while rest and _messages_token_estimate(([system] + rest) if system else rest) > max_tokens:
        # Drop oldest message; if it's an assistant with tool_calls, drop following tool messages
        rest.pop(0)
        while rest and rest[0].get("role") == "tool":
            rest.pop(0)
    return ([system] + rest) if system else rest


def _truncate_tool_result(content: str) -> str:
    """Truncate tool result to stay within context limits."""
    if len(content) <= MAX_TOOL_RESULT_CHARS:
        return content
    return content[: MAX_TOOL_RESULT_CHARS - len(TRUNCATE_SUFFIX)] + TRUNCATE_SUFFIX


SYSTEM_PROMPT = """You are an execution-focused email agent.

Your goal is to complete the user's request using the available tools as efficiently as possible.

Rules:
- Always make progress. If a tool can be used, call it immediately.
- Do NOT ask follow-up questions unless missing information blocks execution.
- Do NOT explain your reasoning or your internal steps.
- Do NOT repeat the same action or tool call.
- Use the minimum number of steps required.
- If no tool call is needed, return a final answer and STOP.

Email workflow rules:
- If the user asks to respond to an email and no email is selected:
  1. Search for relevant emails.
  2. Present up to 5 results with index numbers.
  3. Ask the user to select ONE by number.
- After an email is selected:
  - Fetch and parse the email.
  - Generate a draft reply.
  - Wait for explicit user instruction to send or save as draft.

Tool note: If the user replies with a number (e.g. 1), call get_email with that line's message id, not the list index.

Completion:
- When the task is complete, respond with the result or a short confirmation.
- Do not continue the conversation unless the user provides a new request."""


class Agent:
    """Agent that maintains conversation state and uses the LLM to decide tool calls."""

    def __init__(
        self,
        gmail_service: GmailService,
        llm_service: LLMService,
    ) -> None:
        """Initialize the agent with Gmail and LLM services.

        Args:
            gmail_service: GmailService instance (used to build tools).
            llm_service: LLMService instance for completion with tools.
        """
        self._tools = build_tool_registry(gmail_service, llm_service)
        self._tools_schema = tools_to_openai_schema(self._tools)
        self._llm = llm_service
        self._gmail = gmail_service
        self._messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

    def add_user_message(self, content: str) -> None:
        """Append a user message to the conversation."""
        self._messages.append({"role": "user", "content": content})

    def run_turn(self) -> str:
        """Run the agent loop until the LLM produces a final response (no tool call).

        Executes tool calls, appends results to conversation, and calls the LLM again
        until the model returns content without tool_calls.

        Returns:
            The final assistant message content to show the user.

        Raises:
            email_agent.llm_service.LLMError: If the LLM call fails.
        """
        turn_start = time.perf_counter()
        openai_call_count = 0
        openai_time_ms = 0.0
        gmail_time_ms = 0.0
        tool_time_total = 0.0
        GMAIL_TOOLS = frozenset(("send_reply", "create_draft"))
        REPLY_TOOLS = frozenset(("send_reply", "create_draft"))
        self._reply_to_email_cache: Optional[Dict[str, Any]] = None
        max_iterations = 20
        for _ in range(max_iterations):
            messages_to_send = _trim_messages_to_fit(self._messages, MAX_MESSAGE_TOKENS)
            llm_start = time.perf_counter()
            assistant_msg = self._llm.complete_with_tools(
                messages_to_send,
                self._tools_schema,
                max_tokens=COMPLETION_MAX_TOKENS,
            )
            llm_elapsed_ms = (time.perf_counter() - llm_start) * 1000
            openai_call_count += 1
            openai_time_ms += llm_elapsed_ms
            logger.debug("OpenAI call took %.0f ms", llm_elapsed_ms)
            content = assistant_msg.get("content")
            tool_calls = assistant_msg.get("tool_calls") or []

            # Build the assistant message for history (OpenAI format)
            asst_for_history: Dict[str, Any] = {
                "role": "assistant",
                "content": content if content else None,
            }
            if tool_calls:
                asst_for_history["tool_calls"] = tool_calls
            self._messages.append(asst_for_history)

            if not tool_calls:
                turn_elapsed_ms = (time.perf_counter() - turn_start) * 1000
                logger.debug("Turn completed in %.0f ms", turn_elapsed_ms)
                other_ms = max(0, turn_elapsed_ms - openai_time_ms - gmail_time_ms)
                logger.debug(
                    "  Turn: %d ms | OpenAI: %d ms | Gmail: %d ms | Other: %d ms",
                    int(turn_elapsed_ms),
                    int(openai_time_ms),
                    int(gmail_time_ms),
                    int(other_ms),
                )
                return (content or "").strip()

            # Execute each tool call and append tool results (one LLM call per iteration)
            tool_start = time.perf_counter()
            for tc in tool_calls:
                fid = tc["id"]
                name = tc["function"]["name"]
                call_start = time.perf_counter()
                result = None
                try:
                    raw_args = tc["function"].get("arguments") or "{}"
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError as e:
                    result = f"Error parsing arguments: {e}"
                if result is None and name in REPLY_TOOLS and self._reply_to_email_cache is None:
                    result = (
                        "Error: reply_to_email is required. Open the email first by "
                        "calling get_email(message_id) or parse_email(message_id), then try again."
                    )
                if result is None:
                    if name in REPLY_TOOLS:
                        arguments = dict(arguments)
                        arguments["reply_to_email"] = self._reply_to_email_cache
                    try:
                        result = execute_tool(self._tools, name, arguments)
                        if name == "get_email" and isinstance(result, dict):
                            self._reply_to_email_cache = self._gmail.parse_email(result)
                        elif name == "parse_email" and isinstance(result, dict):
                            self._reply_to_email_cache = result
                        if not isinstance(result, str):
                            result = json.dumps(result, default=str)
                    except Exception as e:
                        result = f"Error: {e}"
                        logger.exception("Tool %s failed", name)
                call_elapsed_ms = (time.perf_counter() - call_start) * 1000
                if name in GMAIL_TOOLS:
                    gmail_time_ms += call_elapsed_ms

                result_str = _truncate_tool_result(str(result))
                self._messages.append(
                    {"role": "tool", "tool_call_id": fid, "content": result_str}
                )
            tool_time_total += time.perf_counter() - tool_start

        turn_elapsed_ms = (time.perf_counter() - turn_start) * 1000
        logger.debug("Turn completed in %.0f ms (limit reached)", turn_elapsed_ms)
        other_ms = max(0, turn_elapsed_ms - openai_time_ms - gmail_time_ms)
        logger.debug(
            "  Turn: %d ms | OpenAI: %d ms | Gmail: %d ms | Other: %d ms",
            int(turn_elapsed_ms),
            int(openai_time_ms),
            int(gmail_time_ms),
            int(other_ms),
        )
        return "I reached the step limit. Please try a shorter flow or rephrase."
