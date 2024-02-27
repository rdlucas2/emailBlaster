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


def search_messages(service, user_id, search_string):
    """
    Searches for messages in the user's Gmail account that match a given query string.

    Args:
        service: The Gmail API service instance.
        user_id: The user's email address or 'me' to indicate the authenticated user.
        search_string: The query string to filter messages by.

    Returns:
        list: A list of dictionaries where each dictionary contains details of a message matching the search criteria,
              including the message ID, sender, and subject.
    """    
    start_time = time.time()
    try:
        messages = []
        request = service.users().messages().list(userId=user_id, q=search_string)
        while request is not None:
            response = request.execute()
            if "messages" in response:
                for message in response["messages"]:
                    msg = (
                        service.users()
                        .messages()
                        .get(userId=user_id, id=message["id"])
                        .execute()
                    )
                    payload = msg["payload"]
                    headers = payload.get("headers")
                    data = {"id": msg["id"]}
                    for header in headers:
                        if header["name"] == "From":
                            data["sender"] = header["value"]
                        elif header["name"] == "Subject":
                            data["subject"] = header["value"]
                    # Append the detailed data dictionary instead of the ID
                    messages.append(data)
            request = (
                service.users()
                .messages()
                .list_next(previous_request=request, previous_response=response)
            )
        return messages
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
    finally:
        end_time = time.time()
        print(f"Search completed in {end_time - start_time:.2f} seconds")


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
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the messages filtered by the search string",
    )
    args = parser.parse_args()
    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)
    if args.search:
        messages = search_messages(service, "me", args.search)
        total_messages = len(messages)
        print(f"Total number of messages: {total_messages}")
        if total_messages > 0:
            user_input = input(
                "Do you want to print the messages? (y) then ENTER for yes, anything else for no: "
            )
            if user_input.lower() == "y":
                print("Messages:")
                for message in messages:
                    print(
                        f"ID: {message['id']}, Sender: {message.get('sender', 'N/A')}, Subject: {message.get('subject', 'N/A')}"
                    )

        if args.delete and total_messages > 0:
            confirm = input("Are you sure you want to delete the messages? (yes/no): ")
            if confirm.lower() == "yes":
                message_ids = [message["id"] for message in messages]
                batch_delete_messages(service, "me", message_ids)
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")    


if __name__ == "__main__":
    main()
