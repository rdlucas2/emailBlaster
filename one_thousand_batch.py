import argparse
import os.path
import time
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

    Checks for the presence of a token.json file to load existing credentials. If not found or credentials are invalid,
    initiates the authentication flow by opening a browser window for the user to log in and grant access. The credentials
    are then saved to token.json for future use.

    Returns:
        Credentials: The OAuth2 credentials for accessing the Gmail API.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "./volume/credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
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
        yield iterable[i : i + size]


def search_messages(service, user_id, query):
    """Search for messages in Gmail."""
    try:
        response = (
            service.users()
            .messages()
            .list(userId=user_id, q=query, maxResults=1000)
            .execute()
        )
        messages = response.get("messages", [])
        nextPageToken = response.get("nextPageToken")
        print_batch_and_ask_for_deletion(messages, service, user_id)
        while nextPageToken:
            response = (
                service.users()
                .messages()
                .list(userId=user_id, q=query, pageToken=nextPageToken, maxResults=1000)
                .execute()
            )
            messages.extend(response.get("messages", []))
            nextPageToken = response.get("nextPageToken")
            print_batch_and_ask_for_deletion(messages, service, user_id)
            if len(messages) >= 1000:
                break
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def print_batch_and_ask_for_deletion(messages, service, user_id):
    """
    Prints message details for a batch and asks the user if they want to delete them.

    Args:
        messages: List of message details.
        service: The Gmail API service instance.
        user_id: The user's email address or 'me' to indicate the authenticated user.
    """
    start_time = time.time()
    # for message in messages:
    #     print(
    #         f"ID: {message['id']}, Sender: {message.get('sender', 'N/A')}, Subject: {message.get('subject', 'N/A')}"
    #     )
    if messages:
        message_ids = [message["id"] for message in messages]
        batch_delete_messages(service, user_id, message_ids)

    end_time = time.time()  # End stopwatch
    print(
        f"Print batch and ask for delete completed in {end_time - start_time:.2f} seconds"
    )


def batch_delete_messages(service, user_id, message_ids):
    """
    Deletes messages in batches from the user's Gmail account.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me' to indicate the authenticated user.
        message_ids: A list of message IDs to be deleted.

    This function splits the list of message IDs into chunks of 1000 (the API limit for batch operations) and sends a
    batch delete request for each chunk. It handles any HTTP errors that occur during the process.
    """
    start_time = time.time()
    try:
        # Split the message_ids into chunks of 1000, the api limit
        for chunk in chunked(message_ids, 1000):
            body = {"ids": chunk}
            service.users().messages().batchDelete(userId=user_id, body=body).execute()
            print(f"Deleted {len(chunk)} messages.")
    except HttpError as error:
        print(f"An error occurred: {error}")
    finally:
        end_time = time.time()  # End stopwatch
        print(f"Batch delete completed in {end_time - start_time:.2f} seconds")


def main():
    """
    Main function to handle command-line arguments for searching and optionally deleting Gmail messages.

    This function parses command-line arguments to search for messages that match a given query string and, if specified,
    deletes those messages. It uses the `authenticate_gmail` function to authenticate the user and then performs the
    search and delete operations as requested. The total execution time for the script is printed at the end.
    """
    start_time = time.time()
    parser = argparse.ArgumentParser(description="Gmail API Python Quickstart")
    parser.add_argument(
        "--search", type=str, help="Search filter for the Gmail messages"
    )
    args = parser.parse_args()
    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)
    if args.search:
        search_messages(service, "me", args.search)
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    main()
