import argparse
import json
import os.path
import sys
import time
from collections import Counter
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from main import authenticate_gmail, chunked, get_or_create_label

DEFAULT_RULES_FILE = "cleanup_rules.json"
EXAMPLE_RULES_FILE = "cleanup_rules.example.json"


def build_query(rule, keep):
    """
    Builds the Gmail search query for one rule.

    Every rule only touches mail in the inbox, and only unread mail unless the
    rule sets "unread_only": false. The keep settings
    (starred, important, and a list of senders) are excluded from every rule.

    Args:
        rule: Dict with a 'query' key, e.g. "category:promotions older_than:30d".
        keep: Dict with optional 'senders' list, 'starred' and 'important' flags.

    Returns:
        str: The full Gmail search query.
    """
    parts = ["in:inbox"]
    if rule.get("unread_only", True):
        parts.append("is:unread")
    parts.append(f"({rule['query']})")
    if keep.get("starred", True):
        parts.append("-is:starred")
    if keep.get("important", True):
        parts.append("-is:important")
    senders = keep.get("senders", [])
    if senders:
        parts.append("-from:(" + " OR ".join(senders) + ")")
    return " ".join(parts)


def list_message_ids(service, user_id, query):
    """Returns every message ID matching the query, following all pages."""
    ids = []
    request = (
        service.users().messages().list(userId=user_id, q=query, maxResults=500)
    )
    while request is not None:
        response = request.execute()
        ids.extend(m["id"] for m in response.get("messages", []))
        request = (
            service.users()
            .messages()
            .list_next(previous_request=request, previous_response=response)
        )
    return ids


def sample_senders(service, user_id, message_ids, sample_size):
    """Returns a Counter of From headers for the first sample_size messages."""
    senders = Counter()
    for message_id in message_ids[:sample_size]:
        msg = (
            service.users()
            .messages()
            .get(
                userId=user_id,
                id=message_id,
                format="metadata",
                metadataHeaders=["From"],
            )
            .execute()
        )
        for header in msg.get("payload", {}).get("headers", []):
            if header["name"].lower() == "from":
                senders[header["value"]] += 1
    return senders


def apply_rule(service, user_id, message_ids, rule, label_id):
    """
    Marks messages read and/or archives them, in batches of 1000.

    Nothing is deleted. Archived messages get label_id so they are easy to find
    (and to move back to the inbox) later.
    """
    remove_ids = []
    if rule.get("mark_read", True):
        remove_ids.append("UNREAD")
    if rule.get("archive", True):
        remove_ids.append("INBOX")
    body = {"removeLabelIds": remove_ids}
    if rule.get("archive", True) and label_id:
        body["addLabelIds"] = [label_id]

    done = 0
    for chunk in chunked(message_ids, 1000):
        service.users().messages().batchModify(
            userId=user_id, body={**body, "ids": chunk}
        ).execute()
        done += len(chunk)
        print(f"  {done}/{len(message_ids)}")
    return done


def describe(rule):
    actions = []
    if rule.get("mark_read", True):
        actions.append("mark read")
    if rule.get("archive", True):
        actions.append("archive")
    return " + ".join(actions) or "nothing"


def run_cleanup(service, user_id, config, dry_run=False, sample_size=0, assume_yes=False):
    """
    Runs every rule in the config. With dry_run, only counts and samples.

    Messages matched by an earlier rule are not counted again by a later one.

    Returns:
        dict: rule name -> number of messages matched (and changed, if not dry run).
    """
    keep = config.get("keep", {})
    label_name = config.get("label") or f"cleanup_{datetime.now().strftime('%Y%m%d')}"
    rules = config["rules"]

    seen = set()
    plan = []
    for rule in rules:
        query = build_query(rule, keep)
        ids = [i for i in list_message_ids(service, user_id, query) if i not in seen]
        seen.update(ids)
        plan.append((rule, query, ids))
        print(f"\n[{rule['name']}] {describe(rule)}: {len(ids)} messages")
        print(f"  query: {query}")
        if sample_size and ids:
            for sender, count in sample_senders(
                service, user_id, ids, sample_size
            ).most_common(10):
                print(f"    {count:>4}  {sender}")

    total = sum(len(ids) for _, _, ids in plan)
    print(f"\nTotal: {total} messages across {len(plan)} rules.")
    if any(r.get("archive", True) for r in rules):
        print(f"Archived mail gets the label '{label_name}'. Nothing is deleted.")

    if dry_run:
        print("Dry run: nothing was changed.")
        return {rule["name"]: len(ids) for rule, _, ids in plan}
    if total == 0:
        return {rule["name"]: 0 for rule, _, _ in plan}

    if not assume_yes:
        confirm = input(f"Apply these changes to {total} messages? Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Cancelled, nothing was changed.")
            return {rule["name"]: 0 for rule, _, _ in plan}

    label_id = None
    if any(r.get("archive", True) for r in rules):
        label_id = get_or_create_label(service, user_id, label_name)

    results = {}
    for rule, _, ids in plan:
        print(f"\n[{rule['name']}] {describe(rule)}")
        results[rule["name"]] = apply_rule(service, user_id, ids, rule, label_id) if ids else 0
    print(f"\nDone: changed {sum(results.values())} messages.")
    return results


def load_config(path):
    if not os.path.exists(path):
        print(
            f"No rules file at {path}. Copy {EXAMPLE_RULES_FILE} to "
            f"{DEFAULT_RULES_FILE} and edit it first."
        )
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def main():
    """
    Bulk clean up unread inbox mail with the rules in cleanup_rules.json.

    Usage:
        python cleanup.py --dry-run              # count what each rule matches
        python cleanup.py --dry-run --sample 50  # also show top senders per rule
        python cleanup.py                        # apply (asks for 'yes' first)
    """
    start_time = time.time()
    parser = argparse.ArgumentParser(
        description="Mark read and archive unread inbox mail by rule. Never deletes."
    )
    parser.add_argument("--rules", default=DEFAULT_RULES_FILE, help="Rules JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Count only, change nothing")
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Show top senders from this many messages per rule",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    config = load_config(args.rules)
    creds = authenticate_gmail()
    service = build("gmail", "v1", credentials=creds)
    try:
        run_cleanup(service, "me", config, args.dry_run, args.sample, args.yes)
    except HttpError as error:
        print(f"An error occurred: {error}")
    print(f"Total execution time: {time.time() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()
