import argparse
import json
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Creating filters needs the settings scope, which the full-access token used by
# main.py and batch_archive.py does not include. Keep a separate token file so
# signing in here never replaces the token those scripts use.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.labels",
]
TOKEN_FILE = "token_filters.json"


def authenticate_gmail():
    """
    Authenticates with the scopes needed to manage labels and filters.

    Uses token_filters.json if present, otherwise opens a browser to sign in
    with ./volume/credentials.json and saves the new token to token_filters.json.

    Returns:
        Credentials: The OAuth2 credentials for accessing the Gmail API.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "./volume/credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return creds


def get_label_ids(service, user_id):
    """Returns a dict of label name to label ID."""
    response = service.users().labels().list(userId=user_id).execute()
    return {label["name"]: label["id"] for label in response.get("labels", [])}


def get_or_create_label(service, user_id, label_name, labels, dry_run):
    """
    Returns the ID of the named label, creating it if needed.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        label_name: The name of the label to find or create.
        labels: Dict of existing label names to IDs, updated in place.
        dry_run: If True, report the label that would be created instead.
    """
    if label_name in labels:
        return labels[label_name]
    if dry_run:
        print(f"Would create label '{label_name}'")
        labels[label_name] = f"<new:{label_name}>"
        return labels[label_name]
    new_label = (
        service.users()
        .labels()
        .create(userId=user_id, body={"name": label_name})
        .execute()
    )
    print(f"Created label '{label_name}' (id: {new_label['id']})")
    labels[label_name] = new_label["id"]
    return new_label["id"]


def filter_key(query, add_ids, remove_ids):
    return (query, frozenset(add_ids), frozenset(remove_ids))


def existing_filter_keys(service, user_id):
    """Returns the set of (query, add, remove) keys for filters already in place."""
    response = service.users().settings().filters().list(userId=user_id).execute()
    keys = set()
    for f in response.get("filter", []):
        criteria = f.get("criteria", {})
        action = f.get("action", {})
        keys.add(
            filter_key(
                criteria.get("query", ""),
                action.get("addLabelIds", []),
                action.get("removeLabelIds", []),
            )
        )
    return keys


def create_filters(service, user_id, rules, dry_run=False):
    """
    Creates a Gmail filter per rule that labels matching mail and skips the inbox.

    Rules whose filter already exists are skipped, so it is safe to run again.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        rules: List of dicts with 'label', 'query' and optional 'mark_read'.
        dry_run: If True, print what would be created without changing anything.
    """
    labels = get_label_ids(service, user_id)
    existing = existing_filter_keys(service, user_id)
    created = skipped = 0

    for rule in rules:
        label_id = get_or_create_label(
            service, user_id, rule["label"], labels, dry_run
        )
        remove_ids = ["INBOX"] + (["UNREAD"] if rule.get("mark_read") else [])
        key = filter_key(rule["query"], [label_id], remove_ids)
        summary = f"{rule['query']} -> {rule['label']}, skip inbox" + (
            ", mark read" if rule.get("mark_read") else ""
        )

        if key in existing:
            print(f"Already exists: {summary}")
            skipped += 1
            continue
        if dry_run:
            print(f"Would create: {summary}")
            created += 1
            continue

        body = {
            "criteria": {"query": rule["query"]},
            "action": {"addLabelIds": [label_id], "removeLabelIds": remove_ids},
        }
        service.users().settings().filters().create(
            userId=user_id, body=body
        ).execute()
        existing.add(key)
        print(f"Created: {summary}")
        created += 1

    verb = "Would create" if dry_run else "Created"
    print(f"{verb} {created} filters, {skipped} already existed.")


def main():
    parser = argparse.ArgumentParser(
        description="Create Gmail filters that label mail and skip the inbox."
    )
    parser.add_argument(
        "--config",
        default="filters.json",
        help="JSON file with the filter rules (default: filters.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without changing anything",
    )
    args = parser.parse_args()

    with open(args.config) as f:
        rules = json.load(f)["filters"]

    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)
    try:
        create_filters(service, "me", rules, dry_run=args.dry_run)
    except HttpError as error:
        print(f"An error occurred creating filters: {error}")


if __name__ == "__main__":
    main()
