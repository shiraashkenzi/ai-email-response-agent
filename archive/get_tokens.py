"""Optional: Generate Gmail OAuth token. Main app does this on first run."""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_credentials():
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    return flow.run_local_server(port=0)


if __name__ == "__main__":
    creds = get_credentials()
    with open("token.json", "w") as f:
        f.write(creds.to_json())
    print("Token saved to token.json")
