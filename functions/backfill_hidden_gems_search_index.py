import re
import argparse
from firebase_admin import firestore

from firebase_setup import get_project_b_firestore


db = get_project_b_firestore()


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

    keyword_set.add(normalized)

    words = normalized.split(" ")

    for word in words:
        if len(word) > 1 and not word.isdigit():
            keyword_set.add(word)


def generate_keywords(trivia_data):
    keyword_set = set()

    add_keyword(keyword_set, trivia_data.get("title"))
    add_keyword(keyword_set, trivia_data.get("content"))
    add_keyword(keyword_set, trivia_data.get("location"))
    add_keyword(keyword_set, trivia_data.get("id"))

    tags = trivia_data.get("tags", [])

    if isinstance(tags, list):
        for tag in tags:
            add_keyword(keyword_set, tag)

    fixed_keywords = [
        "hidden gems",
        "hidden gem",
        "trivia",
        "facts",
        "interesting facts",
        "history",
        "travel",
        "place",
        "monument",
        "explore",
    ]

    for keyword in fixed_keywords:
        add_keyword(keyword_set, keyword)

    return sorted(list(keyword_set))


def resolve_image_url(trivia_data):
    image_url = (
        trivia_data.get("imageUrl")
        or trivia_data.get("image_url")
        or trivia_data.get("image")
        or trivia_data.get("thumbnail")
    )

    if image_url:
        return image_url

    category = trivia_data.get("category")

    if isinstance(category, str) and category.startswith(("http://", "https://")):
        return category

    return None


def resolve_active_status(trivia_data):
    if "isActive" in trivia_data:
        return trivia_data.get("isActive", True)

    if "is_active" in trivia_data:
        return trivia_data.get("is_active", True)

    return True


def backfill_hidden_gems_search_index(dry_run=False, limit=None):
    trivia_ref = db.collection("trivia")
    search_index_ref = db.collection("search_index")

    docs = trivia_ref.stream()

    batch = db.batch() if not dry_run else None
    operation_count = 0
    total_count = 0

    for doc in docs:
        if limit is not None and total_count >= limit:
            break

        data = doc.to_dict()

        source_id = data.get("id") or doc.id
        title = data.get("title") or ""
        content = str(data.get("content") or "").strip()

        if not title:
            print(f"Skipping trivia {doc.id}: missing title")
            continue

        search_doc_id = f"hidden_gems_{source_id}"
        search_doc_ref = search_index_ref.document(search_doc_id)

        keywords = generate_keywords(data)

        search_data = {
            "title": title,
            "content":content,
            "type": "hidden_gems",

            "keywords": keywords,

            "sourceCollection": "trivia",
            "sourceId": source_id,
            "route": f"/hidden-gems/{source_id}",

            "imageUrl": resolve_image_url(data),
            "location": data.get("location"),

            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),

            "priority": 70,
            "isActive": resolve_active_status(data),

            "updatedAt": firestore.SERVER_TIMESTAMP,
        }

        if dry_run:
            print(
                f"[DRY RUN] Would index {search_doc_id}: "
                f"title='{title}', "
                f"type='{search_data['type']}', "
                f"route='{search_data['route']}', "
                f"isActive={search_data['isActive']}, "
                f"keywords={len(keywords)}"
            )
        else:
            batch.set(search_doc_ref, search_data, merge=True)

        operation_count += 1
        total_count += 1

        if not dry_run and operation_count >= 450:
            batch.commit()
            print(f"Committed {total_count} hidden gems records...")

            batch = db.batch()
            operation_count = 0

        if total_count % 100 == 0:
            print(f"Processed {total_count} hidden gems records...")

    if not dry_run and operation_count > 0:
        batch.commit()

    mode_label = "validated" if dry_run else "indexed"
    print(f"Done. Total hidden gems records {mode_label}: {total_count}")


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Backfill trivia documents into search_index as hidden_gems."
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
            help="Process only the first N trivia documents.",
        )

        args = parser.parse_args()

        backfill_hidden_gems_search_index(
            dry_run=args.dry_run,
            limit=args.limit,
        )

    except Exception as e:
        print("Hidden gems search index backfill failed:", e)