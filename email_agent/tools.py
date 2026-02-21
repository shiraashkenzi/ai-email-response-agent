"""Tool abstraction and registry for the agent-with-tools architecture."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from email_agent.gmail_service import GmailService
from email_agent.llm_service import LLMService


@dataclass
class Tool:
    """A single tool: name, description, parameter schema, and handler."""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for parameters
    handler: Callable[..., Any]


def _build_search_emails(gmail: GmailService) -> Tool:
    def handler(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        if " " in query.strip():
            gmail_query = f'subject:"{query}"'
        else:
            gmail_query = f"subject:{query}"
        return gmail.search_emails(gmail_query, max_results=max_results)

    return Tool(
        name="search_emails",
        description="Search Gmail by subject or query. Returns message summaries with id and threadId.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (subject or keywords)"},
                "max_results": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["query"],
        },
        handler=handler,
    )


def _build_list_emails_summary(gmail: GmailService) -> Tool:
    def handler(
        messages: Optional[List[Dict[str, Any]]] = None,
        max_entries: int = 10,
        **kwargs: Any,
    ) -> str:
        """Build a short numbered summary for message refs from search_emails."""
        # Accept list under common names the LLM might use
        msg_list = messages
        if msg_list is None:
            msg_list = kwargs.get("message_list") or kwargs.get("emails") or kwargs.get("search_results")
        if not isinstance(msg_list, list):
            return "Error: messages must be a list of message refs from search_emails."
        lines: List[str] = []
        for i, ref in enumerate(msg_list[:max_entries], 1):
            msg_id = ref.get("id") or ref.get("message_id")
            if not msg_id:
                lines.append(f"{i}. [no id]")
                continue
            try:
                full = gmail.get_email(str(msg_id))
                parsed = gmail.parse_email(full)
                subject = (parsed.get("subject") or "")[:60]
                from_ = (parsed.get("from") or "")[:40]
                date = parsed.get("date") or ""
                lines.append(f"{i}. {subject} | {from_} | {date} (id: {msg_id})")
            except Exception:
                lines.append(f"{i}. [error loading] (id: {msg_id})")
        return "\n".join(lines) if lines else "No messages to summarize."

    return Tool(
        name="list_emails_summary",
        description=(
            "Given message refs from search_emails (id, threadId), return a numbered summary: "
            "index, subject, sender, date, id. Use that line's id for get_email(id) when user picks."
        ),
        parameters={
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of message refs from search_emails (id, threadId)",
                },
                "max_entries": {"type": "integer", "description": "Max entries to include (default 10)", "default": 10},
            },
            "required": ["messages"],
        },
        handler=handler,
    )


def _build_get_email(gmail: GmailService) -> Tool:
    return Tool(
        name="get_email",
        description="Fetch the full raw email message by its Gmail message ID.",
        parameters={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID"},
            },
            "required": ["message_id"],
        },
        handler=gmail.get_email,
    )


def _build_parse_email(gmail: GmailService) -> Tool:
    def handler(
        message: Optional[Any] = None,
        message_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # LLM may send full "message" dict, or "message_id" string, or "email"/"msg"
        msg = message or kwargs.get("email") or kwargs.get("msg")
        if msg is None and len(kwargs) == 1:
            msg = next(iter(kwargs.values()))
        if msg is None:
            msg = message_id
        if isinstance(msg, str):
            # Treat as message_id: fetch then parse
            full = gmail.get_email(msg)
            return gmail.parse_email(full)
        if isinstance(msg, dict) and msg.get("payload") is not None:
            return gmail.parse_email(msg)
        if isinstance(msg, dict):
            # Might be a parsed summary or ref; try parsing as-is (e.g. from get_email)
            return gmail.parse_email(msg)
        raise ValueError(
            "parse_email requires a message dict from get_email or a message_id string"
        )

    return Tool(
        name="parse_email",
        description="Parse a Gmail message. Pass full message from get_email or a message_id string.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "object", "description": "Full message dict from get_email"},
                "message_id": {"type": "string", "description": "Gmail message ID (alternative to message)"},
            },
            "required": [],
        },
        handler=handler,
    )


def _build_generate_reply(llm: LLMService) -> Tool:
    # Safe default so handler never crashes when original_email is missing (LLM uses .get() on keys)
    _SAFE_EMAIL = {"from": "Unknown", "to": "", "subject": "No Subject", "body": "No body content", "date": "Unknown"}

    def handler(
        original_email: Optional[Dict[str, Any]] = None,
        context: Optional[str] = None,
        tone: str = "professional",
        language: str = "en",
        **kwargs: Any,
    ) -> str:
        if original_email is None:
            original_email = kwargs.get("original_email")
        if not isinstance(original_email, dict):
            original_email = _SAFE_EMAIL.copy()
        return llm.generate_reply(
            original_email, context=context, tone=tone, language=language
        )

    return Tool(
        name="generate_reply",
        description="Generate an AI reply for a parsed email. Returns reply body text only.",
        parameters={
            "type": "object",
            "properties": {
                "original_email": {"type": "object", "description": "Parsed email dict (from, to, subject, body)"},
                "context": {"type": "string", "description": "Optional extra context for the reply"},
                "tone": {
                    "type": "string",
                    "description": "Tone: professional, friendly, casual",
                    "default": "professional",
                },
                "language": {"type": "string", "description": "en or he", "default": "en"},
            },
            "required": ["original_email"],
        },
        handler=handler,
    )


def _build_improve_reply(llm: LLMService) -> Tool:
    def handler(
        original_reply: str,
        feedback: str,
        language: str = "en",
    ) -> str:
        return llm.improve_reply(original_reply, feedback, language=language)

    return Tool(
        name="improve_reply",
        description="Improve an existing reply from user feedback. Returns improved reply body.",
        parameters={
            "type": "object",
            "properties": {
                "original_reply": {"type": "string", "description": "Current reply text"},
                "feedback": {"type": "string", "description": "User feedback on how to improve"},
                "language": {"type": "string", "description": "en or he", "default": "en"},
            },
            "required": ["original_reply", "feedback"],
        },
        handler=handler,
    )


def _build_send_reply(gmail: GmailService) -> Tool:
    def handler(
        thread_id: str,
        subject: str,
        body: str,
        reply_to_email: Dict[str, Any],
        to: str = "",
        message_id_header: Optional[str] = None,
        references_header: Optional[str] = None,
    ) -> Dict[str, Any]:
        return gmail.send_reply(
            thread_id=thread_id,
            to=to,
            subject=subject,
            body=body,
            message_id_header=message_id_header,
            references_header=references_header,
            reply_to_email=reply_to_email,
        )

    return Tool(
        name="send_reply",
        description="Send an email reply in a thread. Use thread_id, subject, body from parsed email.",
        parameters={
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Gmail thread ID"},
                "to": {"type": "string", "description": "Ignored; recipient from reply_to_email"},
                "subject": {"type": "string", "description": "Subject (Re: added if missing)"},
                "body": {"type": "string", "description": "Plain text body of the reply"},
                "reply_to_email": {"type": "object", "description": "Parsed email being replied to"},
                "message_id_header": {"type": "string", "description": "Message-ID for threading"},
                "references_header": {"type": "string", "description": "References header (optional)"},
            },
            "required": ["thread_id", "to", "subject", "body", "reply_to_email"],
        },
        handler=handler,
    )


def _build_create_draft(gmail: GmailService) -> Tool:
    def handler(
        subject: str,
        body: str,
        reply_to_email: Dict[str, Any],
        to: str = "",
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return gmail.create_draft(
            to=to,
            subject=subject,
            body=body,
            thread_id=thread_id,
            reply_to_email=reply_to_email,
        )

    return Tool(
        name="create_draft",
        description="Create a draft (do not send). Optionally provide thread_id.",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Ignored; recipient from reply_to_email"},
                "subject": {"type": "string", "description": "Subject line"},
                "body": {"type": "string", "description": "Plain text body"},
                "reply_to_email": {"type": "object", "description": "Parsed email being replied to"},
                "thread_id": {"type": "string", "description": "Optional Gmail thread ID"},
            },
            "required": ["to", "subject", "body", "reply_to_email"],
        },
        handler=handler,
    )


def build_tool_registry(
    gmail_service: GmailService,
    llm_service: LLMService,
) -> Dict[str, Tool]:
    """Build the registry of tools from existing Gmail and LLM services."""
    return {
        "search_emails": _build_search_emails(gmail_service),
        "list_emails_summary": _build_list_emails_summary(gmail_service),
        "get_email": _build_get_email(gmail_service),
        "parse_email": _build_parse_email(gmail_service),
        "generate_reply": _build_generate_reply(llm_service),
        "improve_reply": _build_improve_reply(llm_service),
        "send_reply": _build_send_reply(gmail_service),
        "create_draft": _build_create_draft(gmail_service),
    }


def tools_to_openai_schema(tools: Dict[str, Tool]) -> List[Dict[str, Any]]:
    """Convert tool registry to OpenAI tools format for chat completions."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools.values()
    ]


def execute_tool(tools: Dict[str, Tool], name: str, arguments: Dict[str, Any]) -> Any:
    """Execute a tool by name with the given arguments.

    Returns:
        The tool handler's return value (may be str or dict).

    Raises:
        ValueError: If the tool name is not in the registry.
    """
    if name not in tools:
        raise ValueError(f"Unknown tool: {name}")
    tool = tools[name]
    return tool.handler(**arguments)
