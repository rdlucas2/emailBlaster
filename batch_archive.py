import argparse
import os.path
import time
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these SCOPES, delete the file token.json.
SCOPES = [
    "https://mail.google.com/"
]  # Allows full control, read and write access, including deletion


def authenticate_gmail():
    """
    Authenticates the user with the Gmail API using OAuth2 credentials.

    Checks for the presence of a token.json file to load existing credentials.
    If not found or credentials are invalid, initiates the authentication flow
    by opening a browser window for the user to log in and grant access.
    The credentials are then saved to token.json for future use.

    Returns:
        Credentials: The OAuth2 credentials for accessing the Gmail API.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "./volume/credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


def chunked(iterable, size):
    """
    Splits an iterable into chunks of a specified size.

    Args:
        iterable: The iterable to be chunked.
        size: The size of each chunk.

    Yields:
        Iterable: A chunk of the original iterable of the specified size.
    """
    for i in range(0, len(iterable), size):
        yield iterable[i: i + size]


def get_or_create_label(service, user_id, label_name):
    """
    Retrieves an existing Gmail label by name, or creates it if it doesn't exist.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        label_name: The name of the label to find or create.

    Returns:
        str: The label ID.
    """
    try:
        response = service.users().labels().list(userId=user_id).execute()
        for label in response.get("labels", []):
            if label["name"] == label_name:
                print(f"Found existing label '{label_name}' (id: {label['id']})")
                return label["id"]
        # Label not found — create it
        new_label = (
            service.users()
            .labels()
            .create(userId=user_id, body={"name": label_name})
            .execute()
        )
        print(f"Created new label '{label_name}' (id: {new_label['id']})")
        return new_label["id"]
    except HttpError as error:
        print(f"An error occurred getting/creating label: {error}")
        raise


def batch_archive_and_label(service, user_id, message_ids, label_id):
    """
    Archives messages and applies a label in batches of 1000.

    Removes the INBOX label and adds the specified label to each message.
    Uses batchModify which accepts up to 1000 IDs per call.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        message_ids: A list of message IDs to archive and label.
        label_id: The ID of the label to apply.
    """
    start_time = time.time()
    try:
        for chunk in chunked(message_ids, 1000):
            body = {
                "ids": chunk,
                "removeLabelIds": ["INBOX"],
                "addLabelIds": [label_id],
            }
            service.users().messages().batchModify(
                userId=user_id, body=body
            ).execute()
            print(f"Archived and labeled {len(chunk)} messages.")
    except HttpError as error:
        print(f"An error occurred during batch archive: {error}")
    finally:
        end_time = time.time()
        print(f"Batch archive completed in {end_time - start_time:.2f} seconds")


def batch_delete_messages(service, user_id, message_ids):
    """
    Deletes messages in batches from the user's Gmail account.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        message_ids: A list of message IDs to be deleted.
    """
    start_time = time.time()
    try:
        for chunk in chunked(message_ids, 1000):
            body = {"ids": chunk}
            service.users().messages().batchDelete(
                userId=user_id, body=body
            ).execute()
            print(f"Deleted {len(chunk)} messages.")
    except HttpError as error:
        print(f"An error occurred during batch delete: {error}")
    finally:
        end_time = time.time()
        print(f"Batch delete completed in {end_time - start_time:.2f} seconds")


def search_and_archive(service, user_id, query, label_id):
    """
    Searches for messages matching a query and archives them in batches of 1000,
    applying the specified label.

    Paginates through results until no more pages remain or 1000 messages
    have been processed in this run.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        query: Gmail search query string.
        label_id: The label ID to apply to archived messages.
    """
    total_archived = 0
    try:
        response = (
            service.users()
            .messages()
            .list(userId=user_id, q=query, maxResults=1000)
            .execute()
        )
        while True:
            messages = response.get("messages", [])
            if not messages:
                print("No messages found matching the query.")
                break

            message_ids = [m["id"] for m in messages]
            batch_archive_and_label(service, user_id, message_ids, label_id)
            total_archived += len(message_ids)
            print(f"Running total archived: {total_archived}")

            next_page_token = response.get("nextPageToken")
            if not next_page_token or total_archived >= 1000:
                break

            response = (
                service.users()
                .messages()
                .list(
                    userId=user_id,
                    q=query,
                    pageToken=next_page_token,
                    maxResults=1000,
                )
                .execute()
            )

        print(f"Total archived this run: {total_archived} messages.")
    except HttpError as error:
        print(f"An error occurred during search: {error}")


def delete_by_label(service, user_id, label_name):
    """
    Finds all messages with a given label, shows a count, asks for confirmation,
    and then batch-deletes them if the user confirms.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me'.
        label_name: The name of the label whose messages should be deleted.
    """
    try:
        # Resolve label name to ID
        labels_response = service.users().labels().list(userId=user_id).execute()
        label_id = None
        for label in labels_response.get("labels", []):
            if label["name"] == label_name:
                label_id = label["id"]
                break

        if not label_id:
            print(f"Label '{label_name}' not found in your account.")
            return

        print(f"Fetching all messages with label '{label_name}'...")
        all_message_ids = []
        request = (
            service.users()
            .messages()
            .list(userId=user_id, labelIds=[label_id], maxResults=1000)
        )
        while request is not None:
            response = request.execute()
            messages = response.get("messages", [])
            all_message_ids.extend([m["id"] for m in messages])
            request = (
                service.users()
                .messages()
                .list_next(previous_request=request, previous_response=response)
            )

        total = len(all_message_ids)
        if total == 0:
            print(f"No messages found with label '{label_name}'.")
            return

        print(f"\nFound {total} messages with label '{label_name}'.")
        confirm = input(
            f"Are you sure you want to PERMANENTLY DELETE all {total} messages? "
            "This cannot be undone. Type 'yes' to confirm: "
        )
        if confirm.strip().lower() == "yes":
            batch_delete_messages(service, user_id, all_message_ids)
            print(f"Deleted {total} messages with label '{label_name}'.")
        else:
            print("Deletion cancelled.")

    except HttpError as error:
        print(f"An error occurred: {error}")


def main():
    """
    Main function for batch archiving and label-based deletion.

    Usage:
        # Archive all emails matching a search query, applying a timestamped label:
        python batch_archive.py --search "from:canva.com"
        python batch_archive.py --search "category:promotions older_than:30d"

        # Delete all emails that carry a specific label (with confirmation prompt):
        python batch_archive.py --delete-label "claude_auto_archive_20260518"

        # Combine: archive with a custom label name instead of the default timestamp:
        python batch_archive.py --search "from:uphold.com" --label "my_custom_label"
    """
    start_time = time.time()
    parser = argparse.ArgumentParser(
        description="Batch archive Gmail messages with a label, or delete by label."
    )
    parser.add_argument(
        "--search",
        type=str,
        help="Gmail search query — matching messages will be archived and labeled.",
    )
    parser.add_argument(
        "--label",
        type=str,
        default=None,
        help=(
            "Label name to apply when archiving. "
            "Defaults to 'claude_auto_archive_YYYYMMDD' using today's date."
        ),
    )
    parser.add_argument(
        "--delete-label",
        type=str,
        dest="delete_label",
        help="Delete ALL messages carrying this label (will prompt for confirmation).",
    )
    args = parser.parse_args()

    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)

    if args.search:
        label_name = args.label or f"claude_auto_archive_{datetime.now().strftime('%Y%m%d')}"
        print(f"Archiving messages matching: '{args.search}'")
        print(f"Applying label: '{label_name}'")
        label_id = get_or_create_label(service, "me", label_name)
        search_and_archive(service, "me", args.search, label_id)

    if args.delete_label:
        delete_by_label(service, "me", args.delete_label)

    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    main()
