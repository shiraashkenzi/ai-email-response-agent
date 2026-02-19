"""Gmail Service Module - Handles all Gmail API operations."""

import base64
import os
import re
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials as GoogleCredentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError as GoogleHttpError


# Gmail API OAuth scopes required
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailService:
    """Service for interacting with Gmail API"""
    
    def __init__(self, credentials: GoogleCredentials):
        """Initialize Gmail service with credentials"""
        self.credentials = credentials
        self._service = None
    
    def _get_service(self):
        """Get authenticated Gmail service instance, refreshing if needed"""
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
        if self._service is None:
            self._service = build('gmail', 'v1', credentials=self.credentials)
        return self._service
    
    def search_emails(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for emails matching the query
        
        Args:
            query: Gmail search query (e.g., "subject:meeting")
            max_results: Maximum number of results to return
            
        Returns:
            List of email message dictionaries with id and threadId
            
        Raises:
            GoogleHttpError: If Gmail API call fails
        """
        try:
            service = self._get_service()
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            messages = results.get('messages', [])
            if messages is None:
                messages = []
            return messages
        except GoogleHttpError as e:
            raise GmailError(f"Failed to search emails: {e.error_details if hasattr(e, 'error_details') else str(e)}") from e
        except Exception as e:
            raise GmailError(f"Unexpected error searching emails: {str(e)}") from e
    
    def get_email(self, message_id: str) -> Dict[str, Any]:
        """
        Get full email details by message ID
        
        Args:
            message_id: Gmail message ID
            
        Returns:
            Full email message dictionary
            
        Raises:
            GmailError: If email not found or API call fails
        """
        try:
            service = self._get_service()
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            return message
        except GoogleHttpError as e:
            if e.resp.status == 404:
                raise EmailNotFoundError(f"Email with ID {message_id} not found")
            raise GmailError(f"Failed to get email: {e.error_details if hasattr(e, 'error_details') else str(e)}") from e
    
    def parse_email(self, message: Dict[str, Any]) -> Dict[str, str]:
        """
        Parse email message into readable format
        
        Args:
            message: Full email message dictionary from Gmail API
            
        Returns:
            Dictionary with 'from', 'to', 'subject', 'body', 'date', 'message_id', 'thread_id'
        """
        headers = message.get('payload', {}).get('headers', [])
        
        def get_header(name: str) -> str:
            for header in headers:
                if header['name'].lower() == name.lower():
                    return header['value']
            return ''
        
        from_addr = get_header('From')
        to_addr = get_header('To')
        subject = get_header('Subject')
        date = get_header('Date')
        message_id_header = get_header('Message-ID')
        references = get_header('References')
        in_reply_to = get_header('In-Reply-To')
        
        # Extract body
        body = self._extract_body(message.get('payload', {}))
        
        return {
            'from': from_addr,
            'to': to_addr,
            'subject': subject,
            'body': body,
            'date': date,
            'message_id': message.get('id', ''),
            'thread_id': message.get('threadId', ''),
            'message_id_header': message_id_header,
            'references': references,
            'in_reply_to': in_reply_to,
        }
    
    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Extract email body from payload"""
        body = ""
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        break
                elif part['mimeType'] == 'text/html' and not body:
                    data = part['body'].get('data', '')
                    if data:
                        html_body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        # Simple HTML to text conversion
                        body = re.sub(r'<[^>]+>', '', html_body)
        else:
            if payload.get('mimeType') == 'text/plain':
                data = payload['body'].get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif payload.get('mimeType') == 'text/html':
                data = payload['body'].get('data', '')
                if data:
                    html_body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    body = re.sub(r'<[^>]+>', '', html_body)
        
        return body.strip()
    
    def send_reply(
        self,
        thread_id: str,
        to: str,
        subject: str,
        body: str,
        message_id_header: Optional[str] = None,
        references_header: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a reply email
        
        Args:
            thread_id: Thread ID to reply to
            to: Recipient email address
            subject: Email subject (will add "Re: " if not present)
            body: Email body text
            message_id_header: Original message ID for threading
            references_header: References header for threading
            
        Returns:
            Sent message dictionary
            
        Raises:
            GmailError: If sending fails
        """
        try:
            service = self._get_service()
            
            # Ensure subject has "Re: " prefix
            if not subject.startswith('Re:') and not subject.startswith('RE:'):
                subject = f"Re: {subject}"
            
            # Create message
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            
            # Add threading headers
            if message_id_header:
                if references_header:
                    message['References'] = f"{references_header} {message_id_header}"
                else:
                    message['References'] = message_id_header
                message['In-Reply-To'] = message_id_header
            
            message.attach(MIMEText(body, 'plain'))
            
            # Encode as base64url
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Send
            sent_message = service.users().messages().send(
                userId='me',
                body={'raw': raw, 'threadId': thread_id}
            ).execute()
            
            return sent_message
        except GoogleHttpError as e:
            raise GmailError(f"Failed to send reply: {e.error_details if hasattr(e, 'error_details') else str(e)}") from e
    
    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a draft email
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body text
            thread_id: Optional thread ID for threading
            
        Returns:
            Draft message dictionary
            
        Raises:
            GmailError: If draft creation fails
        """
        try:
            service = self._get_service()
            
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            message.attach(MIMEText(body, 'plain'))
            
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            draft_body = {'message': {'raw': raw}}
            if thread_id:
                draft_body['message']['threadId'] = thread_id
            
            draft = service.users().drafts().create(
                userId='me',
                body=draft_body
            ).execute()
            
            return draft
        except GoogleHttpError as e:
            raise GmailError(f"Failed to create draft: {e.error_details if hasattr(e, 'error_details') else str(e)}") from e


class GmailError(Exception):
    """Base exception for Gmail service errors"""
    pass


class EmailNotFoundError(GmailError):
    """Raised when an email is not found"""
    pass


def authenticate_gmail(token_path: str = 'token.json', credentials_path: str = 'credentials.json') -> GoogleCredentials:
    """
    Authenticate with Gmail API, handling token refresh and re-authorization
    
    Args:
        token_path: Path to token file
        credentials_path: Path to OAuth credentials file
        
    Returns:
        Authenticated GoogleCredentials object
        
    Raises:
        FileNotFoundError: If credentials.json is not found
    """
    creds: GoogleCredentials | None = None
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
        flow = InstalledAppFlow.from_client_secrets_file(absolute_credentials_path, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Verify scopes
        new_token_scopes = set(creds.scopes or [])
        if not required_scopes.issubset(new_token_scopes):
            print(f"⚠️  WARNING: New token missing some scopes!")
            print(f"   Got: {new_token_scopes}")
            print(f"   Required: {required_scopes}")
        else:
            print("✓ Authorization successful! Token has all required scopes")
        with open(absolute_token_path, "w") as token_file:
            token_file.write(creds.to_json())
        print(f"✓ Token saved to {absolute_token_path}\n")
    
    # Final verification
    if creds:
        final_scopes = set(creds.scopes or [])
        if not required_scopes.issubset(final_scopes):
            raise ValueError("Insufficient Gmail API scopes. Delete token.json and re-run.")
    return creds
