
import argparse
from collections import Counter
import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from firebase_functions import https_fn
from firebase_functions.https_fn import Request, Response

from firebase_setup import get_project_b_firestore

try:
    import pandas as pd
except Exception:
    pd = None


load_dotenv(".env.dev")


def _get_project_b_db():
    return get_project_b_firestore()


def _ts_to_iso(ts):
    if ts is None:
        return None

    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc).isoformat()
        return ts.isoformat()

    if hasattr(ts, "seconds"):
        return datetime.fromtimestamp(
            ts.seconds + ts.nanos / 1e9, tz=timezone.utc
        ).isoformat()

    return str(ts)


def _iso_to_readable(iso_ts: str, fmt: str = "%b %d, %Y %I:%M %p") -> str | None:
    if not iso_ts:
        return None

    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime(fmt)
    except Exception:
        return iso_ts


def _normalize_firestore_value(value):
    if isinstance(value, dict):
        normalized = {
            key: _normalize_firestore_value(val) for key, val in value.items()
        }

        readable_field_map = {
            "createdAt": "createdAt_readable",
            "updatedAt": "updatedAt_readable",
            "created_at": "created_at_readable",
            "updated_at": "updated_at_readable",
        }

        for raw_field, readable_field in readable_field_map.items():
            raw_value = normalized.get(raw_field)
            if isinstance(raw_value, str):
                normalized[readable_field] = _iso_to_readable(raw_value)

        return normalized

    if isinstance(value, list):
        return [_normalize_firestore_value(item) for item in value]

    if isinstance(value, datetime) or hasattr(value, "seconds"):
        return _ts_to_iso(value)

    return value


def _serialize_doc(doc):
    data = doc.to_dict() or {}
    normalized = _normalize_firestore_value(data)
    normalized["docId"] = doc.id
    return normalized


def _is_single_participant_chat(chat_data: dict) -> bool:
    participants = chat_data.get("participants") or []
    if not isinstance(participants, list):
        participants = [participants]
    return len(participants) <= 1


def _get_chat_message_summary(db, chat_id: str) -> dict:
    message_docs = (
        db.collection("chats")
        .document(chat_id)
        .collection("messages")
        .get()
    )

    text_count = len(message_docs)
    image_count = 0

    for message_doc in message_docs:
        data = message_doc.to_dict() or {}
        image_url = str(data.get("image_url") or data.get("imageUrl") or "").strip()
        if image_url:
            image_count += 1

    return {
        "messageCount": len(message_docs),
        "textCount": text_count,
        "imageCount": image_count,
    }


def _is_blog_qualified_chat(
    message_summary: dict,
    min_text_count: int,
    min_image_count: int,
) -> bool:
    return (
        message_summary.get("textCount", 0) >= min_text_count
        and message_summary.get("imageCount", 0) >= min_image_count
    )


def _get_user_blogs(db, uid: str) -> list[dict]:
    blog_docs = db.collection("blogs").where("uid", "==", uid).get()
    return [_serialize_doc(blog_doc) for blog_doc in blog_docs]


def _build_summary(result: dict) -> dict:
    reports = result.get("reports") or []
    user_count = len(reports)
    total_creatable_chat_count = sum(
        report.get("creatableChatCount", 0) for report in reports
    )
    total_created_blog_count = sum(
        report.get("createdBlogCount", 0) for report in reports
    )
    total_qualified_chat_count = sum(
        report.get("qualifiedChatCount", 0) for report in reports
    )

    return {
        "eligibleUserCount": user_count,
        "totalQualifiedChatCount": total_qualified_chat_count,
        "totalCreatedBlogCount": total_created_blog_count,
        "totalCreatableChatCount": total_creatable_chat_count,
        "avgCreatableChatsPerUser": round(
            total_creatable_chat_count / user_count, 2
        ) if user_count else 0,
        "qualificationRules": result.get("qualificationRules", {}),
    }


def _build_excel_rows(result: dict) -> tuple[list[dict], list[dict], list[dict]]:
    summary = _build_summary(result)
    summary_rows = [
        {"metric": "eligibleUserCount", "value": summary["eligibleUserCount"]},
        {"metric": "totalQualifiedChatCount", "value": summary["totalQualifiedChatCount"]},
        {"metric": "totalCreatedBlogCount", "value": summary["totalCreatedBlogCount"]},
        {"metric": "totalCreatableChatCount", "value": summary["totalCreatableChatCount"]},
        {"metric": "avgCreatableChatsPerUser", "value": summary["avgCreatableChatsPerUser"]},
        {
            "metric": "minTextCount",
            "value": summary["qualificationRules"].get("minTextCount"),
        },
        {
            "metric": "minImageCount",
            "value": summary["qualificationRules"].get("minImageCount"),
        },
    ]

    user_rows = []
    chat_rows = []

    for report in result.get("reports", []):
        user_data = report.get("user") or {}
        user_rows.append(
            {
                "uid": report.get("uid"),
                "name": " ".join(
                    part for part in [
                        str(user_data.get("firstName") or "").strip(),
                        str(user_data.get("lastName") or "").strip(),
                    ] if part
                ),
                "email": user_data.get("email"),
                "phoneNumber": user_data.get("phoneNumber"),
                "createdBlogCount": report.get("createdBlogCount", 0),
                "qualifiedChatCount": report.get("qualifiedChatCount", 0),
                "creatableChatCount": report.get("creatableChatCount", 0),
            }
        )

        for chat in report.get("creatableChats", []):
            chat_rows.append(
                {
                    "uid": report.get("uid"),
                    "chatId": chat.get("id") or chat.get("docId"),
                    "chatName": chat.get("chat_name") or chat.get("chatName"),
                    "chatType": chat.get("chat_type") or chat.get("chatType"),
                    "createdAt": chat.get("created_at") or chat.get("createdAt"),
                    "createdAtReadable": (
                        chat.get("created_at_readable") or chat.get("createdAt_readable")
                    ),
                    "updatedAt": chat.get("updated_at") or chat.get("updatedAt"),
                    "updatedAtReadable": (
                        chat.get("updated_at_readable") or chat.get("updatedAt_readable")
                    ),
                    "messageCount": chat.get("messageCount", 0),
                    "textCount": chat.get("textCount", 0),
                    "imageCount": chat.get("imageCount", 0),
                    "location": chat.get("location"),
                }
            )

    return summary_rows, user_rows, chat_rows


def _write_excel_report(result: dict, output_path: str | None = None) -> str:
    if pd is None:
        raise RuntimeError("pandas/openpyxl is not available for Excel export")

    if output_path:
        final_path = output_path
    else:
        final_path = os.path.join(os.getcwd(), "user_blog_report_summary.xlsx")

    summary_rows, user_rows, chat_rows = _build_excel_rows(result)

    with pd.ExcelWriter(final_path, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame(user_rows).to_excel(writer, sheet_name="Users", index=False)
        pd.DataFrame(chat_rows).to_excel(writer, sheet_name="Creatable Chats", index=False)
        pd.DataFrame(result.get("qualifiedChatUserDistribution", [])).to_excel(
            writer, sheet_name="Distribution", index=False
        )

    return final_path


def get_user_blog_report_summary(
    uid: str,
    min_text_count: int = 10,
    min_image_count: int = 4,
) -> dict:
    try:
        db = _get_project_b_db()
    except Exception as exc:
        logging.exception("Failed to initialize Firestore client: %s", exc)
        return {
            "found": False,
            "error": "Firestore client not initialized. Check service-account JSON.",
        }

    uid = (uid or "").strip()
    if not uid:
        return {"found": False, "error": "Missing uid"}

    try:
        user_doc = db.collection("users").document(uid).get()

        if not user_doc.exists:
            query = db.collection("users").where("uid", "==", uid).limit(1).get()
            user_doc = query[0] if query else None

        if not user_doc or not user_doc.exists:
            return {"found": False, "message": f"User not found for uid '{uid}'"}

        user_data = _serialize_doc(user_doc)
        resolved_uid = user_data.get("uid") or user_doc.id

        chat_docs = (
            db.collection("chats")
            .where("participants", "array_contains", resolved_uid)
            .get()
        )

        chats = []
        qualified_chats = []

        for chat_doc in chat_docs:
            chat_data = _serialize_doc(chat_doc)
            if not _is_single_participant_chat(chat_data):
                continue

            message_summary = _get_chat_message_summary(db, chat_doc.id)
            qualifies_for_blog = _is_blog_qualified_chat(
                message_summary,
                min_text_count=min_text_count,
                min_image_count=min_image_count,
            )

            chat_data.update(message_summary)
            chat_data["qualifiesForBlog"] = qualifies_for_blog
            chats.append(chat_data)

            if qualifies_for_blog:
                qualified_chats.append(chat_data)

        blogs = _get_user_blogs(db, resolved_uid)
        blog_chat_ids = {
            str(blog.get("chatId")).strip()
            for blog in blogs
            if str(blog.get("chatId") or "").strip()
        }
        creatable_chats = [
            chat for chat in qualified_chats
            if str(chat.get("id") or chat.get("docId") or "").strip() not in blog_chat_ids
        ]

        return {
            "found": True,
            "uid": resolved_uid,
            "user": user_data,
            "creatableChatCount": len(creatable_chats),
            "qualifiedChatCount": len(qualified_chats),
            "qualificationRules": {
                "minTextCount": min_text_count,
                "minImageCount": min_image_count,
            },
            "createdBlogCount": len(blogs),
            "creatableBlogCount": len(creatable_chats),
            "creatableChats": creatable_chats,
        }
    except Exception as exc:
        logging.exception("get_user_blog_report_summary error: %s", exc)
        return {"found": False, "error": str(exc)}


def get_all_user_blog_report_summaries(
    limit: int | None = None,
    min_text_count: int = 10,
    min_image_count: int = 4,
) -> dict:
    try:
        db = _get_project_b_db()
    except Exception as exc:
        logging.exception("Failed to initialize Firestore client: %s", exc)
        return {
            "found": False,
            "error": "Firestore client not initialized. Check service-account JSON.",
        }

    try:
        user_docs = db.collection("users").stream()
        reports = []
        processed = 0
        total_qualified_chat_count = 0
        total_created_blog_count = 0
        total_creatable_blog_count = 0
        qualified_chat_distribution = Counter()

        for user_doc in user_docs:
            if limit is not None and processed >= limit:
                break

            user_data = _serialize_doc(user_doc)
            resolved_uid = user_data.get("uid") or user_doc.id

            chat_docs = (
                db.collection("chats")
                .where("participants", "array_contains", resolved_uid)
                .get()
            )
            chats = []
            qualified_chats = []

            for chat_doc in chat_docs:
                chat_data = _serialize_doc(chat_doc)
                if not _is_single_participant_chat(chat_data):
                    continue

                message_summary = _get_chat_message_summary(db, chat_doc.id)
                qualifies_for_blog = _is_blog_qualified_chat(
                    message_summary,
                    min_text_count=min_text_count,
                    min_image_count=min_image_count,
                )

                chat_data.update(message_summary)
                chat_data["qualifiesForBlog"] = qualifies_for_blog
                chats.append(chat_data)

                if qualifies_for_blog:
                    qualified_chats.append(chat_data)

            total_qualified_chat_count += len(qualified_chats)

            if not qualified_chats:
                processed += 1
                continue

            blogs = _get_user_blogs(db, resolved_uid)
            blog_chat_ids = {
                str(blog.get("chatId")).strip()
                for blog in blogs
                if str(blog.get("chatId") or "").strip()
            }
            creatable_chats = [
                chat for chat in qualified_chats
                if str(chat.get("id") or chat.get("docId") or "").strip() not in blog_chat_ids
            ]

            total_created_blog_count += len(blogs)
            total_creatable_blog_count += len(creatable_chats)

            if not creatable_chats:
                processed += 1
                continue

            qualified_chat_distribution[len(creatable_chats)] += 1

            reports.append(
                {
                    "uid": resolved_uid,
                    "user": user_data,
                    "creatableChatCount": len(creatable_chats),
                    "qualifiedChatCount": len(qualified_chats),
                    "createdBlogCount": len(blogs),
                    "creatableBlogCount": len(creatable_chats),
                    "creatableChats": creatable_chats,
                }
            )
            processed += 1

        return {
            "found": True,
            "userCount": len(reports),
            "totalQualifiedChatCount": total_qualified_chat_count,
            "totalCreatedBlogCount": total_created_blog_count,
            "totalCreatableBlogCount": total_creatable_blog_count,
            "summary": {},
            "qualifiedChatUserDistribution": [
                {
                    "qualifiedChatCount": qualified_chat_count,
                    "userCount": user_count,
                }
                for qualified_chat_count, user_count in sorted(
                    qualified_chat_distribution.items()
                )
            ],
            "qualificationRules": {
                "minTextCount": min_text_count,
                "minImageCount": min_image_count,
            },
            "reports": reports,
        }
    except Exception as exc:
        logging.exception("get_all_user_blog_report_summaries error: %s", exc)
        return {"found": False, "error": str(exc)}


def _write_report_file(result: dict, output_path: str | None = None) -> str:
    if output_path:
        final_path = output_path
    else:
        final_path = os.path.join(os.getcwd(), "user_blog_report_summary.json")

    with open(final_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)

    return final_path


@https_fn.on_request()
def exportUserReport(req: Request) -> Response:
    try:
        data = req.get_json(silent=True) or {}
        uid = data.get("uid") or req.args.get("uid") or req.args.get("userId")
        export_all = data.get("all") or req.args.get("all")
        limit_raw = data.get("limit") or req.args.get("limit")
        min_text_raw = data.get("minTextCount") or req.args.get("minTextCount")
        min_image_raw = data.get("minImageCount") or req.args.get("minImageCount")

        limit = None
        if limit_raw not in (None, ""):
            limit = int(limit_raw)

        min_text_count = int(min_text_raw) if min_text_raw not in (None, "") else 10
        min_image_count = int(min_image_raw) if min_image_raw not in (None, "") else 4

        if export_all in (True, "true", "1", "yes"):
            result = get_all_user_blog_report_summaries(
                limit=limit,
                min_text_count=min_text_count,
                min_image_count=min_image_count,
            )
            status = 200 if result.get("found") else 500
            return Response(
                json.dumps(result, ensure_ascii=False),
                status=status,
                content_type="application/json",
            )

        if not uid:
            return Response(
                json.dumps({"found": False, "error": "Missing 'uid' or set 'all=true'"}),
                status=400,
                content_type="application/json",
            )

        result = get_user_blog_report_summary(
            uid,
            min_text_count=min_text_count,
            min_image_count=min_image_count,
        )
        status = 200 if result.get("found") else 404

        return Response(
            json.dumps(result, ensure_ascii=False),
            status=status,
            content_type="application/json",
        )
    except Exception as exc:
        logging.exception("exportUserReport error: %s", exc)
        return Response(
            json.dumps({"found": False, "error": str(exc)}),
            status=500,
            content_type="application/json",
        )


def main():
    parser = argparse.ArgumentParser(
        description="Export user blog report summaries from Firestore."
    )
    parser.add_argument("--uid", help="Firestore user uid")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export report for all users from the users collection",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit when using --all",
    )
    parser.add_argument(
        "--min-text-count",
        type=int,
        default=10,
        help="Minimum text message count for a chat to qualify for blog export",
    )
    parser.add_argument(
        "--min-image-count",
        type=int,
        default=4,
        help="Minimum image message count for a chat to qualify for blog export",
    )
    parser.add_argument(
        "--output",
        help="Optional output JSON file path",
    )
    parser.add_argument(
        "--format",
        choices=["json", "excel"],
        default="excel",
        help="Export format. Default is excel for team sharing.",
    )
    args = parser.parse_args()

    if args.all:
        result = get_all_user_blog_report_summaries(
            limit=args.limit,
            min_text_count=args.min_text_count,
            min_image_count=args.min_image_count,
        )
    elif args.uid:
        result = get_user_blog_report_summary(
            args.uid,
            min_text_count=args.min_text_count,
            min_image_count=args.min_image_count,
        )
    else:
        raise SystemExit("Provide either --uid <USER_UID> or --all")

    if result.get("found") and result.get("reports") is not None:
        result["summary"] = _build_summary(result)

    if args.format == "excel":
        output_path = _write_excel_report(result, args.output)
    else:
        output_path = _write_report_file(result, args.output)

    print(json.dumps(result.get("summary", result), indent=2, ensure_ascii=False))
    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    main()


