"""Gmail service module: Gmail API operations, OAuth, and message handling."""

import base64
import logging
import os
import re
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials as GoogleCredentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError as GoogleHttpError

logger = logging.getLogger(__name__)

# Gmail API OAuth scopes required
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


def build_subject_query(keywords: str) -> str:
    """Build a Gmail search query string from subject/keywords.

    Multi-word keywords are wrapped in quotes (subject:"..."); single-word
    uses subject:word. Use the result with GmailService.search_emails().

    Args:
        keywords: Search terms (e.g. "project proposal", "meeting").

    Returns:
        Gmail query string (e.g. subject:"project proposal" or subject:meeting).
    """
    s = (keywords or "").strip()
    if not s:
        return "subject:"
    if " " in s:
        return f'subject:"{s}"'
    return f"subject:{s}"


class GmailService:
    """Service for Gmail API: search, get, parse, send, and draft operations."""

    def __init__(self, credentials: GoogleCredentials) -> None:
        """Initialize with OAuth credentials.

        Args:
            credentials: Valid Google OAuth2 credentials with Gmail scopes.
        """
        self.credentials = credentials
        self._service: Any = None

    def _get_service(self) -> Any:
        """Return authenticated Gmail API service, refreshing token if expired.

        Returns:
            Gmail API users().messages() resource (googleapiclient Resource).
        """
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
        if self._service is None:
            self._service = build("gmail", "v1", credentials=self.credentials)
        return self._service

    def search_emails(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for emails matching the given Gmail query.

        Args:
            query: Gmail search query (e.g. "subject:meeting").
            max_results: Maximum number of messages to return.

        Returns:
            List of message dicts with 'id' and 'threadId'.

        Raises:
            GmailError: If the API call fails.
        """
        try:
            service = self._get_service()
            results = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=max_results,
                )
                .execute()
            )
            messages = results.get("messages", [])
            if messages is None:
                messages = []
            return messages
        except GoogleHttpError as e:
            raise GmailError(
                f"Failed to search emails: {e.error_details if hasattr(e, 'error_details') else str(e)}"
            ) from e
        except Exception as e:
            raise GmailError(f"Unexpected error searching emails: {str(e)}") from e

    def get_email(self, message_id: str) -> Dict[str, Any]:
        """Fetch full email message by ID.

        Args:
            message_id: Gmail message ID.

        Returns:
            Full message dict from Gmail API.

        Raises:
            GmailError: If message_id is empty or API call fails.
            EmailNotFoundError: If the message does not exist.
        """
        if not (message_id and str(message_id).strip()):
            raise GmailError("message_id must be non-empty.")
        try:
            service = self._get_service()
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return message
        except GoogleHttpError as e:
            if e.resp.status == 404:
                raise EmailNotFoundError(
                    f"Email with ID {message_id} not found"
                ) from e
            raise GmailError(
                f"Failed to get email: {e.error_details if hasattr(e, 'error_details') else str(e)}"
            ) from e

    def parse_email(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a Gmail API message into a flat dict for display and reply.

        Args:
            message: Full message dict from get_email.

        Returns:
            Dict with keys: from, to, subject, body, date, message_id, thread_id,
            message_id_header, references, in_reply_to.
        """
        headers = message.get("payload", {}).get("headers", [])

        def get_header(name: str) -> str:
            for header in headers:
                if header["name"].lower() == name.lower():
                    return header["value"]
            return ""

        from_addr = get_header("From")
        to_addr = get_header("To")
        subject = get_header("Subject")
        date = get_header("Date")
        message_id_header = get_header("Message-ID")
        references = get_header("References")
        in_reply_to = get_header("In-Reply-To")

        body = self._extract_body(message.get("payload", {}))

        return {
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "body": body,
            "date": date,
            "message_id": message.get("id", ""),
            "thread_id": message.get("threadId", ""),
            "message_id_header": message_id_header,
            "references": references,
            "in_reply_to": in_reply_to,
        }

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Extract plain-text body from a Gmail message payload.

        Args:
            payload: Message payload dict (may have 'parts' or direct body).

        Returns:
            Decoded and stripped body text; HTML is stripped to text.
        """
        body = ""

        if "parts" in payload:
            for part in payload["parts"]:
                part_body = part.get("body") or {}
                if part.get("mimeType") == "text/plain":
                    data = part_body.get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="ignore"
                        )
                        break
                elif part.get("mimeType") == "text/html" and not body:
                    data = part_body.get("data", "")
                    if data:
                        html_body = base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="ignore"
                        )
                        body = re.sub(r"<[^>]+>", "", html_body)
        else:
            top_body = payload.get("body") or {}
            if payload.get("mimeType") == "text/plain":
                data = top_body.get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode(
                        "utf-8", errors="ignore"
                    )
            elif payload.get("mimeType") == "text/html":
                data = top_body.get("data", "")
                if data:
                    html_body = base64.urlsafe_b64decode(data).decode(
                        "utf-8", errors="ignore"
                    )
                    body = re.sub(r"<[^>]+>", "", html_body)

        return body.strip()

    def _build_reply_message(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_email: Optional[Dict[str, Any]] = None,
        message_id_header: Optional[str] = None,
        references_header: Optional[str] = None,
    ) -> str:
        """Build a MIME reply message and return its base64-encoded raw body.

        Extracts and validates recipient using parseaddr; preserves threading
        headers (In-Reply-To, References). Does not set threadId (caller adds it to API payload).

        Args:
            to: Ignored for recipient; kept for API compatibility.
            subject: Subject line (caller may add Re: for send_reply).
            body: Plain-text body.
            reply_to_email: Required parsed original email; recipient is taken from "from" only.
            message_id_header: Optional Message-ID for In-Reply-To / References.
            references_header: Optional References header value.

        Returns:
            Base64-encoded raw message string for Gmail API.

        Raises:
            GmailError: If reply_to_email is missing or no valid recipient can be determined.
        """
        if not reply_to_email or not isinstance(reply_to_email, dict):
            raise GmailError(
                "reply_to_email is required: the parsed email object (with 'from') must be provided."
            )
        from_val = reply_to_email.get("from")
        to_email = self._normalize_recipient(from_val)
        if not to_email or "@" not in to_email:
            raise GmailError(
                "Invalid or missing recipient: reply_to_email must contain a valid 'from' address."
            )
        message = MIMEMultipart()
        message["to"] = to_email
        message["subject"] = subject
        if message_id_header:
            if references_header:
                message["References"] = f"{references_header} {message_id_header}"
            else:
                message["References"] = message_id_header
            message["In-Reply-To"] = message_id_header
        message.attach(MIMEText(body, "plain"))
        return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    def send_reply(
        self,
        thread_id: str,
        to: str,
        subject: str,
        body: str,
        message_id_header: Optional[str] = None,
        references_header: Optional[str] = None,
        reply_to_email: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a reply in the given thread with proper threading headers.

        Args:
            thread_id: Gmail thread ID.
            to: Recipient email address (fallback if reply_to_email not provided).
            subject: Subject line (Re: prefix added if missing).
            body: Plain-text body.
            message_id_header: Message-ID of the message being replied to.
            references_header: References header for threading.
            reply_to_email: Optional parsed original email; if provided, To is taken from its "from" field.

        Returns:
            Sent message dict from Gmail API.

        Raises:
            GmailError: If send fails or no valid recipient (To) can be determined.
        """
        if not subject.startswith("Re:") and not subject.startswith("RE:"):
            subject = f"Re: {subject}"
        raw = self._build_reply_message(
            to=to,
            subject=subject,
            body=body,
            reply_to_email=reply_to_email,
            message_id_header=message_id_header,
            references_header=references_header,
        )
        try:
            service = self._get_service()
            api_start = time.perf_counter()
            sent_message = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw, "threadId": thread_id})
                .execute()
            )
            api_elapsed_ms = (time.perf_counter() - api_start) * 1000
            logger.debug("Gmail API call took %.0f ms (messages.send)", api_elapsed_ms)
            return sent_message
        except GoogleHttpError as e:
            raise GmailError(
                f"Failed to send reply: {e.error_details if hasattr(e, 'error_details') else str(e)}"
            ) from e

    def _normalize_recipient(self, value: Any) -> Optional[str]:
        """Return a valid recipient string (must contain '@'), or None if invalid.
        Accepts 'email@domain.com' or 'Name <email@domain.com>' from headers.
        """
        if value is None:
            return None
        s = (str(value)).strip()
        if not s or "@" not in s:
            return None
        _, email_addr = parseaddr(s)
        email_addr = (email_addr or s).strip()
        if not email_addr or "@" not in email_addr:
            return None
        return email_addr

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        reply_to_email: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a draft message, optionally in an existing thread.

        Args:
            to: Recipient email address.
            subject: Subject line.
            body: Plain-text body.
            thread_id: Optional thread ID for threading.
            reply_to_email: Optional parsed email dict; if to is invalid, its "from" is used as recipient.

        Returns:
            Draft dict from Gmail API.

        Raises:
            GmailError: If draft creation fails or no valid recipient is available.
        """
        raw = self._build_reply_message(
            to=to,
            subject=subject,
            body=body,
            reply_to_email=reply_to_email,
        )
        try:
            service = self._get_service()
            draft_body: Dict[str, Any] = {"message": {"raw": raw}}
            if thread_id:
                draft_body["message"]["threadId"] = thread_id
            api_start = time.perf_counter()
            draft = (
                service.users().drafts().create(userId="me", body=draft_body).execute()
            )
            api_elapsed_ms = (time.perf_counter() - api_start) * 1000
            logger.debug("Gmail API call took %.0f ms (drafts.create)", api_elapsed_ms)
            return draft
        except GoogleHttpError as e:
            raise GmailError(
                f"Failed to create draft: {e.error_details if hasattr(e, 'error_details') else str(e)}"
            ) from e


class GmailError(Exception):
    """Base exception for Gmail service errors."""


class EmailNotFoundError(GmailError):
    """Raised when a requested email is not found."""


def authenticate_gmail(
    token_path: str = "token.json",
    credentials_path: str = "credentials.json",
) -> GoogleCredentials:
    """Authenticate with Gmail API: load or refresh token, or run OAuth flow.

    Args:
        token_path: Path to the saved token file (relative to project root).
        credentials_path: Path to OAuth client JSON (relative to project root).

    Returns:
        Valid GoogleCredentials with Gmail scopes.

    Raises:
        FileNotFoundError: If credentials_path file does not exist.
        ValueError: If token has insufficient scopes after verification.
    """
    creds: Optional[GoogleCredentials] = None
    needs_auth = False
    required_scopes = set(GMAIL_SCOPES)
    project_root = Path(__file__).resolve().parent.parent
    absolute_token_path = str(project_root / token_path)
    absolute_credentials_path = str(project_root / credentials_path)

    if os.path.exists(absolute_token_path):
        creds = GoogleCredentials.from_authorized_user_file(absolute_token_path)
        token_scopes = set(creds.scopes or [])
        missing_scopes = required_scopes - token_scopes
        if missing_scopes:
            print(f"\n⚠️  Token found but missing required Gmail scopes: {missing_scopes}")
            print("   Deleting old token and re-authorizing...\n")
            os.remove(absolute_token_path)
            creds = None
            needs_auth = True
        elif creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print("✓ Token refreshed successfully")
            except Exception as e:
                print(f"Failed to refresh token: {e}")
                print("Re-authorizing to get a fresh token...\n")
                needs_auth = True
                os.remove(absolute_token_path)
                creds = None
        else:
            print("✓ Token loaded with required scopes")
    else:
        print("No token file found. Starting OAuth authorization...\n")
        needs_auth = True

    if needs_auth or creds is None:
        if not os.path.exists(absolute_credentials_path):
            raise FileNotFoundError(
                f"OAuth client file not found at {absolute_credentials_path}. "
                "Download OAuth 'Desktop app' credentials from Google Cloud and save as credentials.json."
            )
        print(f"Requesting authorization with scopes: {GMAIL_SCOPES}\n")
        flow = InstalledAppFlow.from_client_secrets_file(
            absolute_credentials_path, GMAIL_SCOPES
        )
        creds = flow.run_local_server(port=0)

        new_token_scopes = set(creds.scopes or [])
        if not required_scopes.issubset(new_token_scopes):
            print("⚠️  WARNING: New token missing some scopes!")
            print(f"   Got: {new_token_scopes}")
            print(f"   Required: {required_scopes}")
        else:
            print("✓ Authorization successful! Token has all required scopes")
        with open(absolute_token_path, "w") as token_file:
            token_file.write(creds.to_json())
        try:
            os.chmod(absolute_token_path, 0o600)
        except OSError:
            pass
        print(f"✓ Token saved to {absolute_token_path}\n")

    if creds:
        final_scopes = set(creds.scopes or [])
        if not required_scopes.issubset(final_scopes):
            raise ValueError(
                "Insufficient Gmail API scopes. Delete token.json and re-run."
            )
    return creds
