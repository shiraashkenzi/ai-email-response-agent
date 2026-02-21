"""CLI module: guided flow for the AI Email Response Agent (Search → Preview → Draft → Approve)."""

import logging
from typing import Any, Dict, List, Optional

from email_agent.gmail_service import (
    EmailNotFoundError,
    GmailError,
    GmailService,
)
from email_agent.llm_service import LLMError, LLMService

logger = logging.getLogger(__name__)

BANNER = "AI Email Response Agent - CLI"
MAX_SEARCH_RESULTS = 10
PROMPT_SEND_OPTIONS = "Would you like to send this reply? (yes / modify / save as draft)"


class CLI:
    """Guided CLI that runs the TA flow: search → display list → preview → draft → approve/send."""

    def __init__(self, gmail_service: GmailService, llm_service: LLMService) -> None:
        """Initialize CLI with Gmail and LLM services.

        Args:
            gmail_service: Service for Gmail API (search, get, parse, send, draft).
            llm_service: Service for OpenAI (generate_reply, improve_reply).
        """
        self._gmail = gmail_service
        self._llm = llm_service

    def run(self) -> None:
        """Run the interactive guided flow. Handles errors without crashing."""
        self._print_banner()
        while True:
            try:
                if not self._run_guided_flow():
                    break
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                logger.exception("Unexpected error in CLI")
                print(f"Error: {e}")
                if not self._ask_yes_no("Continue? (y/n): "):
                    break

    def _print_banner(self) -> None:
        """Print welcome banner and instructions."""
        print("=" * 60)
        print(BANNER)
        print("=" * 60)
        print()
        print("You can ask to respond to an email (e.g. 'the email about the project proposal').")
        print("Type 'quit' or 'exit' at any prompt to stop.")
        print()

    def _extract_search_query(self, user_message: str) -> str:
        """Extract search keywords from a user message like 'help me respond to the email about X'.

        Args:
            user_message: Raw user input.

        Returns:
            Extracted phrase or the whole message stripped.
        """
        s = user_message.strip()
        lower = s.lower()
        if "about the " in lower:
            idx = lower.index("about the ") + len("about the ")
            return s[idx:].strip() or s
        if "about " in lower:
            idx = lower.index("about ") + len("about ")
            return s[idx:].strip() or s
        return s

    def _run_guided_flow(self) -> bool:
        """Run one full cycle: search → list → preview → draft → send/draft.

        Returns:
            True to run another cycle, False to exit.
        """
        query = self._ask_search_query()
        if query is None:
            return False
        query = self._extract_search_query(query)

        search_results = self._run_search(query)
        if search_results is None:
            return True
        if not search_results:
            print("Agent:")
            print("No matching emails found. Try different keywords.")
            return True

        selected = self._run_select_email(search_results)
        if selected is None:
            return False
        parsed_email = selected

        if not self._run_email_preview(parsed_email):
            return True

        reply_body = self._run_draft_reply(parsed_email)
        if reply_body is None:
            return True

        return self._run_approval_flow(parsed_email, reply_body)

    def _ask_search_query(self) -> Optional[str]:
        """Ask user for their request (e.g. respond to the email about X).

        Returns:
            User message (used to extract search keywords), or None if user quits.
        """
        while True:
            raw = input("You: ").strip()
            if raw.lower() in ("quit", "exit", "q"):
                print("Exiting...")
                return None
            if raw:
                return raw
            print("Please enter your request (e.g. 'the email about the project proposal').")

    def _run_search(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Search Gmail and display a numbered list (From, Subject, Date).

        Args:
            query: Search query (subject or keywords).

        Returns:
            List of parsed email dicts (with id, thread_id, from, subject, date, etc.)
            for the displayed results; None on error (caller may continue).
        """
        try:
            if " " in query.strip():
                gmail_query = f'subject:"{query}"'
            else:
                gmail_query = f"subject:{query}"
            messages = self._gmail.search_emails(gmail_query, max_results=MAX_SEARCH_RESULTS)
        except GmailError as e:
            print(f"Search failed: {e}")
            return None

        if not messages:
            return []

        print("Agent:")
        print("I'll search for that email.")
        print()
        entries: List[Dict[str, Any]] = []
        for ref in messages[:MAX_SEARCH_RESULTS]:
            msg_id = ref.get("id")
            if not msg_id:
                continue
            try:
                full = self._gmail.get_email(str(msg_id))
                parsed = self._gmail.parse_email(full)
                entries.append(parsed)
                from_ = (parsed.get("from") or "Unknown")[:60]
                subject = (parsed.get("subject") or "(No subject)")[:60]
                date = parsed.get("date") or ""
                print(f"{len(entries)}. From: {from_} | Subject: {subject} | Date: {date} (id: {msg_id})")
            except (GmailError, EmailNotFoundError):
                pass  # Skip failed items so displayed numbers match selection indices

        if not entries:
            return []
        print()
        return entries

    def _run_select_email(self, search_results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Ask user to select an email by number; return parsed email or None.

        Args:
            search_results: List of parsed email dicts (order matches displayed list).

        Returns:
            Selected parsed email dict, or None if user quits.
        """
        while True:
            raw = input("Enter the number of the email you want to open (or 'quit' to exit): ").strip()
            if raw.lower() in ("quit", "exit", "q"):
                print("Exiting...")
                return None
            if not raw:
                continue
            try:
                num = int(raw)
            except ValueError:
                print("Please enter a number.")
                continue
            if num < 1 or num > len(search_results):
                print(f"Please enter a number between 1 and {len(search_results)}.")
                continue
            return search_results[num - 1]

    def _run_email_preview(self, parsed_email: Dict[str, Any]) -> bool:
        """Display full email (From, Subject, Body) and ask to proceed to draft.

        Returns:
            True if user wants to draft a reply, False otherwise.
        """
        from_ = parsed_email.get("from") or "Unknown"
        subject = parsed_email.get("subject") or "(No subject)"
        body = (parsed_email.get("body") or "").strip() or "(No body)"
        date = parsed_email.get("date") or ""

        print("Agent:")
        print("I found an email from {} sent on {}:".format(from_, date))
        print()
        print("Subject:", subject)
        print("From:", from_)
        print("Body:", body)
        print()

        while True:
            raw = input("Would you like me to draft a reply? (yes / no): ").strip().lower()
            if raw in ("quit", "exit", "q"):
                print("Exiting...")
                return False
            if raw in ("yes", "y"):
                return True
            if raw in ("no", "n"):
                return False
            print("Please enter 'yes' or 'no'.")

    def _run_draft_reply(self, parsed_email: Dict[str, Any]) -> Optional[str]:
        """Generate and display suggested reply; return body text or None on error.

        Args:
            parsed_email: Parsed email dict (from, subject, body, date, etc.).

        Returns:
            Reply body text to use for send/draft, or None on error.
        """
        print("Agent:")
        print("Let me draft a response for you.")
        print()
        try:
            reply_body = self._llm.generate_reply(
                parsed_email,
                context=None,
                tone="professional",
                language="en",
            )
        except LLMError as e:
            print(f"Could not generate reply: {e}")
            return None

        if not (reply_body and reply_body.strip()):
            print("Generated reply was empty.")
            return None

        print("Agent:")
        print("Here's my suggested reply:")
        print("---")
        print(reply_body.strip())
        print("---")
        print()
        print(PROMPT_SEND_OPTIONS)
        print()
        return reply_body.strip()

    def _run_approval_flow(
        self,
        parsed_email: Dict[str, Any],
        initial_reply_body: str,
    ) -> bool:
        """Ask user: send / modify / save as draft; execute and optionally loop (modify).

        Args:
            parsed_email: Parsed email being replied to (for send/draft).
            initial_reply_body: Initial suggested reply body.

        Returns:
            True to run another cycle, False to exit.
        """
        reply_body = initial_reply_body
        while True:
            raw = input("You: ").strip().lower()
            if raw in ("quit", "exit", "q"):
                print("Exiting...")
                return False
            if raw in ("yes", "y"):
                return self._do_send_reply(parsed_email, reply_body)
            if raw in ("modify", "m"):
                reply_body = self._do_modify_reply(reply_body)
                if reply_body is None:
                    return True
                print("Agent:")
                print("Here's the updated reply:")
                print("---")
                print(reply_body)
                print("---")
                print()
                print(PROMPT_SEND_OPTIONS)
                print()
                continue
            if raw in ("save as draft", "draft", "d", "save"):
                return self._do_save_draft(parsed_email, reply_body)
            print("Please enter: yes, modify, or save as draft.")
            print()
            print(PROMPT_SEND_OPTIONS)

    def _do_send_reply(
        self,
        parsed_email: Dict[str, Any],
        body: str,
    ) -> bool:
        """Send the reply via Gmail. Prints success or error. Returns True to continue."""
        subject = parsed_email.get("subject") or ""
        if not subject.startswith("Re:") and not subject.startswith("RE:"):
            subject = f"Re: {subject}"
        thread_id = parsed_email.get("thread_id") or ""
        message_id_header = parsed_email.get("message_id_header")
        references = parsed_email.get("references") or ""

        try:
            self._gmail.send_reply(
                thread_id=thread_id,
                to="",
                subject=subject,
                body=body,
                message_id_header=message_id_header,
                references_header=references,
                reply_to_email=parsed_email,
            )
            print("Agent:")
            print("Reply sent successfully!")
            return True
        except GmailError as e:
            print(f"Failed to send reply: {e}")
            return True

    def _do_modify_reply(self, current_reply: str) -> Optional[str]:
        """Ask for feedback, call improve_reply, return new body or None on error."""
        feedback = input("What would you like to change? ").strip()
        if not feedback:
            return current_reply
        try:
            return self._llm.improve_reply(
                current_reply,
                feedback,
                language="en",
            ).strip()
        except LLMError as e:
            print(f"Could not improve reply: {e}")
            return None

    def _do_save_draft(
        self,
        parsed_email: Dict[str, Any],
        body: str,
    ) -> bool:
        """Save reply as Gmail draft. Returns True to continue."""
        subject = parsed_email.get("subject") or ""
        if not subject.startswith("Re:") and not subject.startswith("RE:"):
            subject = f"Re: {subject}"
        thread_id = parsed_email.get("thread_id") or ""

        try:
            self._gmail.create_draft(
                to="",
                subject=subject,
                body=body,
                thread_id=thread_id or None,
                reply_to_email=parsed_email,
            )
            print("Agent:")
            print("Draft saved successfully.")
            return True
        except GmailError as e:
            print(f"Failed to save draft: {e}")
            return True

    def _ask_yes_no(self, prompt: str) -> bool:
        """Ask user for y/n. Returns True for yes, False for no."""
        while True:
            response = input(prompt).strip().lower()
            if response in ("y", "yes"):
                return True
            if response in ("n", "no"):
                return False
            print("Please enter 'y' or 'n'.")
