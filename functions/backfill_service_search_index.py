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


def generate_keywords(service_data):
    keyword_set = set()

    add_keyword(keyword_set, service_data.get("serviceId"))
    add_keyword(keyword_set, service_data.get("serviceName"))
    add_keyword(keyword_set, service_data.get("serviceTitle"))
    add_keyword(keyword_set, service_data.get("serviceDescription"))
    add_keyword(keyword_set, service_data.get("serviceType"))

    fixed_keywords = [
        "service",
        "services",
        "travel service",
        "booking",
        "trip",
        "explore",
        "traviz",
    ]

    service_id = normalize_text(service_data.get("serviceId"))
    service_name = normalize_text(service_data.get("serviceName"))
    service_title = normalize_text(service_data.get("serviceTitle"))
    service_type = normalize_text(service_data.get("serviceType"))
    combined = f"{service_id} {service_name} {service_title} {service_type}"

    if "guide" in combined:
        fixed_keywords.extend(
            [
                "guide",
                "tour guide",
                "local guide",
                "guided tour",
            ]
        )

    if "photo" in combined or "photographer" in combined:
        fixed_keywords.extend(
            [
                "photographer",
                "photo",
                "photoshoot",
                "travel photography",
            ]
        )

    if "cab" in combined or "auto" in combined or "transport" in combined:
        fixed_keywords.extend(
            [
                "cab",
                "auto",
                "taxi",
                "transport",
                "local mobility",
                "ride",
            ]
        )

    if "sightseeing" in combined or "experience" in combined:
        fixed_keywords.extend(
            [
                "sightseeing",
                "tour",
                "attractions",
                "local sightseeing",
            ]
        )

    if "postcard" in combined:
        fixed_keywords.extend(
            [
                "postcard",
                "memory",
                "souvenir",
            ]
        )

    if "other service" in combined or "other_service" in combined or "concierge" in combined or "custom" in combined:
        fixed_keywords.extend(
            [
                "concierge",
                "custom service",
                "special request",
                "help",
                "support",
            ]
        )

    for keyword in fixed_keywords:
        add_keyword(keyword_set, keyword)

    return sorted(list(keyword_set))


def resolve_active_status(service_data):
    if "isActive" in service_data:
        value = service_data.get("isActive", True)
    elif "is_active" in service_data:
        value = service_data.get("is_active", True)
    else:
        value = True

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() == "true"

    return bool(value)


def resolve_priority(service_data):
    ranking = service_data.get("ranking", 90)

    try:
        return int(ranking)
    except Exception:
        return 90


def backfill_services_search_index(dry_run=False, limit=None):
    services_ref = db.collection("services")
    search_index_ref = db.collection("search_index")

    docs = services_ref.stream()

    batch = db.batch() if not dry_run else None
    operation_count = 0
    total_count = 0

    for doc in docs:
        if limit is not None and total_count >= limit:
            break

        data = doc.to_dict()

        source_id = str(data.get("serviceId") or doc.id).strip()
        title = str(
            data.get("serviceTitle")
            or data.get("serviceName")
            or ""
        ).strip()

        content = str(data.get("serviceDescription") or "").strip()


        if not source_id:
            print(f"Skipping service {doc.id}: missing serviceId")
            continue

        if not title:
            print(f"Skipping service {doc.id}: missing title")
            continue

        search_doc_id = f"service_{source_id}"
        search_doc_ref = search_index_ref.document(search_doc_id)

        keywords = generate_keywords(data)

        search_data = {
            "title": title,
            "content": content,
            "type": "service",
            "keywords": keywords,
            "sourceCollection": "services",
            "sourceId": source_id,
            "route": f"/service/{source_id}",
            "imageUrl": data.get("serviceImage"),
            "location": data.get("location"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "priority": resolve_priority(data),
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
            print(f"Committed {total_count} services...")

            batch = db.batch()
            operation_count = 0

        if total_count % 100 == 0:
            print(f"Processed {total_count} services...")

    if not dry_run and operation_count > 0:
        batch.commit()

    mode_label = "validated" if dry_run else "indexed"
    print(f"Done. Total services {mode_label}: {total_count}")


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description="Backfill services into the search_index collection."
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
            help="Process only the first N service documents.",
        )

        args = parser.parse_args()

        backfill_services_search_index(
            dry_run=args.dry_run,
            limit=args.limit,
        )

    except Exception as e:
        print("Service search index backfill failed:", e)