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


def resolve_tip_type(tip_data):
    difficulty = normalize_text(tip_data.get("difficulty_level"))

    if difficulty == "easy":
        return "event"

    if difficulty == "medium":
        return "restaurant"

    return "tip"


def generate_keywords(tip_data, tip_type):
    keyword_set = set()

    add_keyword(keyword_set, tip_data.get("title"))
    add_keyword(keyword_set, tip_data.get("content"))
    add_keyword(keyword_set, tip_data.get("location"))
    add_keyword(keyword_set, tip_data.get("id"))
    add_keyword(keyword_set, tip_data.get("difficulty_level"))

    tags = tip_data.get("tags", [])

    if isinstance(tags, list):
        for tag in tags:
            add_keyword(keyword_set, tag)

    fixed_keywords = [
        "tip",
        "tips",
        "local tip",
        "local experience",
        "travel",
        "visit",
        "place",
        "explore",
    ]

    if tip_type == "event":
        fixed_keywords.extend(
            [
                "event",
                "events",
                "activity",
                "things to do",
                "experience",
                "local event",
            ]
        )

    if tip_type == "restaurant":
        fixed_keywords.extend(
            [
                "restaurant",
                "restaurants",
                "food",
                "eat",
                "dining",
                "cafe",
                "local food",
                "place to eat",
            ]
        )

    for keyword in fixed_keywords:
        add_keyword(keyword_set, keyword)

    return sorted(list(keyword_set))


def resolve_image_url(tip_data):
    image_url = (
        tip_data.get("imageUrl")
        or tip_data.get("image_url")
        or tip_data.get("image")
        or tip_data.get("thumbnail")
    )

    if image_url:
        return str(image_url).strip()

    category = tip_data.get("category")

    if isinstance(category, str) and category.strip().startswith(
        ("http://", "https://")
    ):
        return category.strip()

    return None


def resolve_active_status(tip_data):
    if "isActive" in tip_data:
        value = tip_data.get("isActive", True)
    elif "is_active" in tip_data:
        value = tip_data.get("is_active", True)
    else:
        value = True

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() == "true"

    return bool(value)


def resolve_priority(tip_type):
    if tip_type == "restaurant":
        return 65

    if tip_type == "event":
        return 60

    return 50


def backfill_tips_search_index(dry_run=False, limit=None):
    tips_ref = db.collection("tips")
    search_index_ref = db.collection("search_index")

    docs = tips_ref.stream()

    batch = db.batch() if not dry_run else None
    operation_count = 0
    total_count = 0

    for doc in docs:
        if limit is not None and total_count >= limit:
            break

        data = doc.to_dict()

        source_id = str(data.get("id") or doc.id).strip()
        title = str(data.get("title") or "").strip()
        content = str(data.get("content") or "").strip()

        if not source_id:
            print(f"Skipping tip {doc.id}: missing id")
            continue

        if not title:
            print(f"Skipping tip {doc.id}: missing title")
            continue

        tip_type = resolve_tip_type(data)

        search_doc_id = f"tip_{source_id}"
        search_doc_ref = search_index_ref.document(search_doc_id)

        keywords = generate_keywords(data, tip_type)

        search_data = {
            "title": title,
            "content": content,
            "type": tip_type,
            "keywords": keywords,
            "sourceCollection": "tips",
            "sourceId": source_id,
            "route": f"/tips/{source_id}",
            "imageUrl": resolve_image_url(data),
            "location": data.get("location"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "priority": resolve_priority(tip_type),
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
            print(f"Committed {total_count} tips records...")

            batch = db.batch()
            operation_count = 0

        if total_count % 100 == 0:
            print(f"Processed {total_count} tips records...")

    if not dry_run and operation_count > 0:
        batch.commit()

    mode_label = "validated" if dry_run else "indexed"
    print(f"Done. Total tips records {mode_label}: {total_count}")


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Backfill tips documents into search_index as events/restaurants."
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
            help="Process only the first N tips documents.",
        )

        args = parser.parse_args()

        backfill_tips_search_index(
            dry_run=args.dry_run,
            limit=args.limit,
        )

    except Exception as e:
        print("Tips search index backfill failed:", e)