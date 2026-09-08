import argparse
import csv
import json
import os
from datetime import datetime, timezone

from firebase_setup import get_project_b_firestore


def _timestamp_to_iso(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()

    if hasattr(value, "seconds") and hasattr(value, "nanos"):
        return datetime.fromtimestamp(
            value.seconds + (value.nanos / 1e9),
            tz=timezone.utc,
        ).isoformat()

    return value


def _normalize_firestore_value(value):
    if isinstance(value, dict):
        return {
            key: _normalize_firestore_value(item) for key, item in value.items()
        }

    if isinstance(value, list):
        return [_normalize_firestore_value(item) for item in value]

    return _timestamp_to_iso(value)


def _serialize_document(doc):
    data = doc.to_dict() or {}
    normalized = _normalize_firestore_value(data)
    normalized["docId"] = doc.id
    return normalized


def export_collection(collection_path, limit=None):
    db = get_project_b_firestore()
    query = db.collection(collection_path)

    if limit:
        query = query.limit(limit)

    docs = query.stream()
    return [_serialize_document(doc) for doc in docs]


def _default_output_path(collection_path, export_format):
    safe_name = collection_path.replace("/", "_")
    return os.path.join(os.getcwd(), f"{safe_name}_export.{export_format}")


def write_json(rows, output_path):
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)


def write_csv(rows, output_path):
    flattened_rows = []
    field_names = set()

    for row in rows:
        flat_row = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                flat_row[key] = json.dumps(value, ensure_ascii=False)
            else:
                flat_row[key] = value
            field_names.add(key)
        flattened_rows.append(flat_row)

    ordered_field_names = sorted(field_names)

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered_field_names)
        writer.writeheader()
        writer.writerows(flattened_rows)


def main():
    parser = argparse.ArgumentParser(
        description="Export Firestore collection data to JSON or CSV."
    )
    parser.add_argument(
        "--collection",
        required=True,
        help="Firestore collection name or collection path. Example: users or chats/123/messages",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format. Default is json.",
    )
    parser.add_argument(
        "--output",
        help="Optional output file path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional document limit.",
    )
    args = parser.parse_args()

    rows = export_collection(args.collection, limit=args.limit)
    output_path = args.output or _default_output_path(args.collection, args.format)

    if args.format == "csv":
        write_csv(rows, output_path)
    else:
        write_json(rows, output_path)

    print(f"Exported {len(rows)} documents from '{args.collection}'")
    print(f"Saved file: {output_path}")


if __name__ == "__main__":
    main()
