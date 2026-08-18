import re
import argparse
from firebase_admin import firestore

from firebase_setup import get_project_b_firestore


# Reuse the shared Firestore configuration so the backfill writes to the
# same Firebase project as the rest of the app.
db = get_project_b_firestore()


# --------------------------------------------------
# Text Normalization
# --------------------------------------------------
def normalize_text(value):
    if value is None:
        return ""

    text = str(value).lower()
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def add_keyword(keyword_set, value):
    normalized = normalize_text(value)

    if not normalized:
        return

    # Add full phrase
    keyword_set.add(normalized)

    # Add individual words
    words = normalized.split(" ")

    for word in words:
        if len(word) > 1 and not word.isdigit():
            keyword_set.add(word)


def generate_keywords(site_data):
    keyword_set = set()

    # Main searchable fields
    add_keyword(keyword_set, site_data.get("site_name"))
    add_keyword(keyword_set, site_data.get("location"))
    add_keyword(keyword_set, site_data.get("id"))

    # Services array
    services = site_data.get("services", [])

    if isinstance(services, list):
        for service in services:
            add_keyword(keyword_set, service)

    # Fixed keywords for all monuments
    fixed_keywords = [
        "monument",
        "historical site",
        "tourist place",
        "travel",
        "visit",
        "place",
    ]

    for keyword in fixed_keywords:
        add_keyword(keyword_set, keyword)

    return sorted(list(keyword_set))


def resolve_image_url(site_data):
    # Historical records are not fully consistent, so prefer explicit image
    # fields and fall back to prompt only if it already contains a URL.
    image_url = (
        site_data.get("imageUrl")
        or site_data.get("image_url")
        or site_data.get("image")
    )

    if image_url:
        return image_url

    prompt = site_data.get("prompt")
    if isinstance(prompt, str) and prompt.startswith(("http://", "https://")):
        return prompt

    return None


# --------------------------------------------------
# Backfill Function
# --------------------------------------------------
def backfill_historical_sites_search_index(dry_run=False, limit=None):
    historical_sites_ref = db.collection("historical_sites")
    search_index_ref = db.collection("search_index")

    docs = historical_sites_ref.stream()

    batch = db.batch() if not dry_run else None
    operation_count = 0
    total_count = 0

    for doc in docs:
        if limit is not None and total_count >= limit:
            break

        data = doc.to_dict()

        source_id = data.get("id") or doc.id
        title = data.get("site_name") or ""
        content = str(data.get("site_description") or "").strip()

        search_doc_id = f"monument_{source_id}"
        search_doc_ref = search_index_ref.document(search_doc_id)

        keywords = generate_keywords(data)
        

        search_data = {
            "title": title,
            "content": content,
            "type": "monument",

            "keywords": keywords,

            "sourceCollection": "historical_sites",
            "sourceId": source_id,
            "route": f"/historical-site/{source_id}",

            "imageUrl": resolve_image_url(data),
            "location": data.get("location"),

            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),

            "priority": 100,
            "isActive": data.get("is_active", True),

            "updatedAt": firestore.SERVER_TIMESTAMP,
        }



        if dry_run:
            print(
                f"[DRY RUN] Would index {search_doc_id}: "
                f"title='{title}', route='{search_data['route']}', "
                f"keywords={len(keywords)}"
            )
        else:
            batch.set(search_doc_ref, search_data, merge=True)

            wrong_search_doc_id = f"monument_{doc.id}"

            if wrong_search_doc_id != search_doc_id:
             wrong_search_doc_ref = search_index_ref.document(wrong_search_doc_id)
             batch.delete(wrong_search_doc_ref)
             operation_count += 1

        operation_count += 1
        total_count += 1

        if not dry_run and operation_count >= 450:
            batch.commit()
            print(f"Committed {total_count} monuments...")

            batch = db.batch()
            operation_count = 0

        if total_count % 100 == 0:
            print(f"Processed {total_count} historical sites...")

    if not dry_run and operation_count > 0:
        batch.commit()

    mode_label = "validated" if dry_run else "indexed"
    print(f"Done. Total monuments {mode_label}: {total_count}")


# --------------------------------------------------
# Run Script
# --------------------------------------------------
if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Backfill historical_sites into the search_index collection."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview indexed documents without writing to Firestore.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process only the first N historical site documents.",
        )
        args = parser.parse_args()

        backfill_historical_sites_search_index(
            dry_run=args.dry_run,
            limit=args.limit,
        )
    except Exception as e:
        print("Search index backfill failed:", e)
