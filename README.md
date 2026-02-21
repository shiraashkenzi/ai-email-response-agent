# AI Email Response Agent

A Command-Line Interface (CLI) tool that integrates the Gmail API and OpenAI to help you manage and respond to emails efficiently.

The agent allows you to:

- Search emails from your Gmail inbox
- View full email content
- Generate AI-powered reply suggestions
- Approve, edit, send, or save replies as drafts

Emails are never sent automatically — user approval is always required.

---

## Requirements

- Python 3.8+
- Gmail API credentials (OAuth Desktop App)
- OpenAI API key

Dependencies (see `requirements.txt`):

- google-auth
- google-auth-oauthlib
- google-auth-httplib2
- google-api-python-client
- openai
- python-dotenv

---

## Project Structure

```
.
├── main.py                 # Application entry point
├── email_agent/
│   ├── config.py           # Environment configuration
│   ├── cli.py              # CLI interaction logic
│   ├── gmail_service.py    # Gmail API integration
│   ├── llm_service.py      # OpenAI integration
│   ├── agent.py            # Agent orchestration logic
│   └── tools.py            # Tool definitions
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Create a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set:

```
OPENAI_API_KEY=your_openai_key_here
OPENAI_MODEL=gpt-4o-mini
GMAIL_TOKEN_PATH=token.json
GMAIL_CREDENTIALS_PATH=credentials.json
```

---

## Gmail API Setup

1. Go to Google Cloud Console  
2. Create or select a project  
3. Enable Gmail API  
4. Configure OAuth consent screen  
5. Create Credentials → OAuth Client ID → Desktop App  
6. Download `credentials.json`  
7. Place it in the project root  

On first run, the application will open a browser for authentication and generate `token.json` automatically.

Do not commit:
- `.env`
- `credentials.json`
- `token.json`

---

## Run the Application

```bash
python main.py
```

Application flow:

1. Search for an email
2. Select an email
3. Generate AI reply
4. Choose:
   - Send
   - Modify
   - Save as Draft

Type `quit` or `exit` at any time to stop.

---

## Error Handling

The application handles:

- Missing API key
- Gmail authentication errors
- OpenAI API errors
- Invalid email selection
- Keyboard interruption (Ctrl+C)

No unhandled exceptions during normal usage.

---

## Security

- No hardcoded secrets
- Environment-based configuration
- Sensitive files excluded via `.gitignore`

---

## Future Improvements

- Conversation memory
- HTML email preview
- Batch reply functionality
- Multi-LLM support
- Gmail API optimization and caching

---

## License

MIT License