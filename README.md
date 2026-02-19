# AI Email Response Agent

A CLI tool that connects Gmail and OpenAI so you can search emails by subject, view them, and get AI-generated reply suggestions. You choose whether to send, edit, save as draft, or cancel—no automatic sending.

---

## Features

- **Subject search** — Find Gmail messages by subject (multi-word supported).
- **View email** — See From, To, Subject, Date, and body (plain text).
- **AI reply suggestions** — Generate replies with OpenAI; optionally edit or ask for an improved version with feedback.
- **Send or draft** — Send the reply (with confirmation) or save as a Gmail draft.
- **Threading** — Replies use correct Gmail threading (In-Reply-To / References).
- **OAuth** — Gmail access via OAuth; token refresh and scope checks.

---

## Tech Stack

| Layer        | Technology                          |
|-------------|--------------------------------------|
| Language    | Python 3.8+                          |
| Gmail       | Gmail API (google-api-python-client), OAuth (google-auth-oauthlib) |
| LLM         | OpenAI API (openai)                  |
| Config      | python-dotenv                        |

---

## Project Structure

```
.
├── main.py                 # Entry point: config, auth, services, CLI
├── email_agent/
│   ├── __init__.py
│   ├── config.py           # Environment and settings (.env)
│   ├── cli.py              # User prompts, menus, display
│   ├── gmail_service.py    # Gmail API: search, get, parse, send, draft, OAuth
│   └── llm_service.py      # OpenAI: generate reply, improve from feedback
├── requirements.txt
├── .env.example            # Template; copy to .env
├── .gitignore
├── README.md
└── archive/                # Optional (e.g. get_tokens script)
    ├── README.md
    └── get_tokens.py
```

---

## Setup

### 1. Clone and enter project

```bash
git clone <repo-url> .
# or unpack the project and:
cd /path/to/Pydantic-AI-Gmail-Agent-main
```

### 2. Virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment variables

```bash
cp .env.example .env
```

Edit `.env` and set:

- **OPENAI_API_KEY** (required) — Your OpenAI API key.
- **OPENAI_MODEL** (optional) — e.g. `gpt-4` or `gpt-3.5-turbo`. Default: `gpt-4`.
- **GMAIL_TOKEN_PATH** (optional) — Default: `token.json`.
- **GMAIL_CREDENTIALS_PATH** (optional) — Default: `credentials.json`.

### 5. Gmail credentials

1. **Google Cloud** — [Google Cloud Console](https://console.cloud.google.com/) → create or select a project.
2. **Gmail API** — APIs & Services → Library → enable **Gmail API**.
3. **OAuth consent** — APIs & Services → OAuth consent screen → configure (External or Internal), add scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/gmail.send`
4. **OAuth client** — Credentials → Create Credentials → OAuth client ID → **Desktop app** → download JSON.
5. Save the JSON in the project root as `credentials.json` (or the path in `GMAIL_CREDENTIALS_PATH`).

On first run, the app will open a browser for sign-in and save a token to `token.json`.

---

## How to Run

From the project root (with the virtualenv activated if you use it):

```bash
python main.py
```

You’ll see a short banner and a prompt to enter an email subject.

---

## Example Flow

```
============================================================
AI Email Response Agent - CLI
============================================================

------------------------------------------------------------
Enter email subject to search (or 'quit' to exit): project update

🔍 Searching for emails matching: 'project update'...
✓ Found 2 email(s)

1. From: alice@example.com | Subject: Project update | Date: ...
2. From: bob@example.com   | Subject: Re: Project update | Date: ...
Enter number (or 'cancel'): 1

--- Email ---
From: alice@example.com
To: you@example.com
Subject: Project update
...

--- Suggested reply ---
[AI-generated reply text]

[s]end  [e]dit  [r]egenerate  [d]raft  [c]ancel: s
Send this reply? (y/n): y
✓ Reply sent.

Do you want to process another email? (y/n): n
Exiting...
```

---

## Error Handling

- **Missing OPENAI_API_KEY** — Exits with a clear message; set it in `.env`.
- **Gmail API errors** — Shown to the user; you can retry or continue.
- **OpenAI errors** — Rate limit, connection, and API errors are caught and reported; retry or cancel.
- **Email not found / invalid choice** — Message and return to subject prompt or menu.
- **Invalid input** — Prompts repeated with a short hint (e.g. “Please enter a number”, “y/n”).
- **KeyboardInterrupt** — Clean exit.

No uncaught exceptions for normal use; stack traces only for unexpected errors.

---

## Security Notes

- **No hardcoded secrets** — API keys and paths come from `.env` or the OAuth flow.
- **Do not commit** — `.env`, `token.json`, and `credentials.json` are in `.gitignore`. Never commit them.
- **`.env.example`** — Contains only placeholder names and brief instructions; no real keys.

---

## Future Improvements

- Full-text or date filters for search (beyond subject).
- Optional batch processing (e.g. “reply to all matching”).
- Richer body display (e.g. HTML preview).
- Optional persistence for conversation context across runs.
- Support for other LLM providers (e.g. OpenRouter) behind the same interface.

---

## License

This project is open source and available under the MIT License.
