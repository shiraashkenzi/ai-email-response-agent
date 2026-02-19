"""CLI Interface Module - Handles user interaction"""

from typing import Optional, Dict, Any
from email_agent.gmail_service import GmailService, EmailNotFoundError, GmailError
from email_agent.llm_service import LLMService, LLMError


class CLI:
    """Command-line interface for AI Email Response Agent"""
    
    def __init__(self, gmail_service: GmailService, llm_service: LLMService):
        """Initialize CLI with Gmail and LLM services"""
        self.gmail_service = gmail_service
        self.llm_service = llm_service
    
    def run(self):
        """Main CLI loop"""
        print("=" * 60)
        print("AI Email Response Agent - CLI")
        print("=" * 60)
        print()
        
        while True:
            try:
                # Get email subject from user
                subject_query = self._get_subject_query()
                if not subject_query:
                    print("Exiting...")
                    break
                
                # Search for emails
                emails = self._search_emails(subject_query)
                if not emails:
                    continue
                
                # Select email
                email = self._select_email(emails)
                if not email:
                    continue
                
                # Display email
                self._display_email(email)
                
                # Generate and handle reply
                self._handle_reply(email)
                
                # Ask if user wants to continue
                if not self._ask_yes_no("Do you want to process another email? (y/n): "):
                    break
                    
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"\n❌ Error: {str(e)}")
                if not self._ask_yes_no("Continue? (y/n): "):
                    break
    
    def _get_subject_query(self) -> Optional[str]:
        """Get email subject search query from user"""
        print("\n" + "-" * 60)
        query = input("Enter email subject to search (or 'quit' to exit): ").strip()
        
        if query.lower() in ('quit', 'exit', 'q'):
            return None
        
        if not query:
            print("⚠️  Please enter a subject to search.")
            return self._get_subject_query()
        
        return query
    
    def _search_emails(self, query: str) -> list:
        """Search for emails matching the query"""
        print(f"\n🔍 Searching for emails matching: '{query}'...")
        
        try:
            # Build Gmail search query - handle multi-word subjects with quotes
            if ' ' in query:
                gmail_query = f'subject:"{query}"'
            else:
                gmail_query = f"subject:{query}"
            messages = self.gmail_service.search_emails(gmail_query, max_results=10)
            
            if not messages:
                print(f"❌ No emails found matching '{query}'")
                return []
            
            print(f"✓ Found {len(messages)} email(s)")
            return messages
            
        except GmailError as e:
            print(f"❌ Gmail error: {str(e)}")
            return []
        except Exception:
            raise
    
    def _select_email(self, messages: list) -> Optional[Dict[str, Any]]:
        """Let user select an email from search results"""
        if len(messages) == 1:
            print("\n📧 Found 1 email, loading...")
            try:
                full_email = self.gmail_service.get_email(messages[0]['id'])
                return self.gmail_service.parse_email(full_email)
            except EmailNotFoundError:
                print("❌ Email not found")
                return None
            except GmailError as e:
                print(f"❌ Error loading email: {str(e)}")
                return None
        
        # Multiple emails - show list
        print("\n📧 Multiple emails found. Please select one:")
        print()
        
        email_previews = []
        for i, msg in enumerate(messages[:10], 1):
            try:
                full_email = self.gmail_service.get_email(msg['id'])
                parsed = self.gmail_service.parse_email(full_email)
                email_previews.append(parsed)
                print(f"{i}. From: {parsed['from']}")
                print(f"   Subject: {parsed['subject']}")
                print(f"   Date: {parsed['date']}")
                print()
            except Exception as e:
                print(f"{i}. [Error loading email: {str(e)}]")
                print()
        
        while True:
            try:
                choice = input(f"Select email (1-{len(email_previews)}) or 'cancel': ").strip().lower()
                
                if choice in ('cancel', 'c'):
                    return None
                
                index = int(choice) - 1
                if 0 <= index < len(email_previews):
                    return email_previews[index]
                else:
                    print(f"⚠️  Please enter a number between 1 and {len(email_previews)}")
            except ValueError:
                print("⚠️  Please enter a valid number")
            except KeyboardInterrupt:
                return None
    
    def _display_email(self, email: Dict[str, Any]):
        """Display email details"""
        print("\n" + "=" * 60)
        print("EMAIL DETAILS")
        print("=" * 60)
        print(f"From:    {email['from']}")
        print(f"To:      {email['to']}")
        print(f"Subject: {email['subject']}")
        print(f"Date:    {email['date']}")
        print("-" * 60)
        print("BODY:")
        print("-" * 60)
        print(email['body'])
        print("=" * 60)
    
    def _handle_reply(self, email: Dict[str, Any]):
        """Handle reply generation and sending"""
        print("\n🤖 Generating reply suggestion...")
        
        try:
            # Generate reply
            reply = self.llm_service.generate_reply(email)
            
            print("\n" + "=" * 60)
            print("SUGGESTED REPLY")
            print("=" * 60)
            print(reply)
            print("=" * 60)
            
            # Get user decision
            while True:
                action = input("\nWhat would you like to do?\n"
                             "  [s]end - Send this reply\n"
                             "  [e]dit - Modify the reply\n"
                             "  [r]egenerate - Generate a new reply\n"
                             "  [d]raft - Save as draft\n"
                             "  [c]ancel - Cancel\n"
                             "Choice: ").strip().lower()
                
                if action in ('s', 'send'):
                    self._send_reply(email, reply)
                    break
                elif action in ('e', 'edit'):
                    reply = self._edit_reply(reply)
                    if reply:
                        self._send_reply(email, reply)
                    break
                elif action in ('r', 'regenerate'):
                    reply = self.llm_service.generate_reply(email)
                    print("\n" + "=" * 60)
                    print("NEW SUGGESTED REPLY")
                    print("=" * 60)
                    print(reply)
                    print("=" * 60)
                    continue
                elif action in ('d', 'draft'):
                    self._save_draft(email, reply)
                    break
                elif action in ('c', 'cancel'):
                    print("Cancelled.")
                    break
                else:
                    print("⚠️  Invalid choice. Please enter s, e, r, d, or c.")
            
        except LLMError as e:
            print(f"❌ Error generating reply: {str(e)}")
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)}")
    
    def _send_reply(self, email: Dict[str, Any], reply: str):
        """Send the reply"""
        if not self._ask_yes_no("\n⚠️  Are you sure you want to send this reply? (y/n): "):
            print("Cancelled.")
            return
        
        try:
            # Extract recipient (reply to sender)
            from_addr = email['from']
            # Extract email address from "Name <email@example.com>" format
            if '<' in from_addr:
                to_addr = from_addr.split('<')[1].split('>')[0].strip()
            else:
                to_addr = from_addr.strip()
            
            sent = self.gmail_service.send_reply(
                thread_id=email['thread_id'],
                to=to_addr,
                subject=email['subject'],
                body=reply,
                message_id_header=email.get('message_id_header'),
                references_header=email.get('references')
            )
            
            print(f"\n✓ Reply sent successfully! Message ID: {sent.get('id', 'unknown')}")
            
        except GmailError as e:
            print(f"\n❌ Error sending reply: {str(e)}")
    
    def _edit_reply(self, original_reply: str) -> Optional[str]:
        """Let user edit the reply"""
        print("\n" + "=" * 60)
        print("EDIT REPLY")
        print("=" * 60)
        print("Current reply:")
        print(original_reply)
        print("=" * 60)
        print("\nEnter your edited reply (or 'cancel' to cancel):")
        print("(You can also ask for AI improvements by starting with 'improve:')")
        
        edited = input("\n> ").strip()
        
        if edited.lower() == 'cancel':
            return None
        
        if edited.lower().startswith('improve:'):
            feedback = edited[8:].strip()
            try:
                improved = self.llm_service.improve_reply(original_reply, feedback)
                print("\n✓ Improved reply:")
                print("=" * 60)
                print(improved)
                print("=" * 60)
                if self._ask_yes_no("Use this improved version? (y/n): "):
                    return improved
                return original_reply
            except LLMError as e:
                print(f"❌ Error improving reply: {str(e)}")
                return original_reply
        
        return edited if edited else original_reply
    
    def _save_draft(self, email: Dict[str, Any], reply: str):
        """Save reply as draft"""
        try:
            from_addr = email['from']
            if '<' in from_addr:
                to_addr = from_addr.split('<')[1].split('>')[0].strip()
            else:
                to_addr = from_addr.strip()
            
            draft = self.gmail_service.create_draft(
                to=to_addr,
                subject=email['subject'],
                body=reply,
                thread_id=email['thread_id']
            )
            
            print(f"\n✓ Draft saved successfully! Draft ID: {draft.get('id', 'unknown')}")
            
        except GmailError as e:
            print(f"\n❌ Error saving draft: {str(e)}")
    
    def _ask_yes_no(self, prompt: str) -> bool:
        """Ask user a yes/no question"""
        while True:
            response = input(prompt).strip().lower()
            if response in ('y', 'yes'):
                return True
            elif response in ('n', 'no'):
                return False
            else:
                print("⚠️  Please enter 'y' or 'n'")
