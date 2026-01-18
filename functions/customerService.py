# from datetime import datetime, timezone
# import logging
# import json
# import argparse

# from firebase_functions import https_fn
# from firebase_functions.https_fn import Request, Response
# from google.cloud import firestore as gfirestore

# from firebase_setup import get_project_b_firestore


# # -------------------------------
# # Initialize Firestore
# # -------------------------------
# try:
#     db = get_project_b_firestore()
# except Exception as e:
#     db = None
#     logging.exception("Failed to init Firestore client: %s", e)


# # -------------------------------
# # Helper: convert timestamps → ISO
# # -------------------------------
# def _ts_to_iso(ts):
#     if ts is None:
#         return None

#     if isinstance(ts, datetime):
#         if ts.tzinfo is None:
#             return ts.replace(tzinfo=timezone.utc).isoformat()
#         return ts.isoformat()

#     # Firestore timestamp object
#     if hasattr(ts, "seconds"):
#         return datetime.fromtimestamp(
#             ts.seconds + ts.nanos / 1e9, tz=timezone.utc
#         ).isoformat()

#     return str(ts)


# from datetime import datetime

# def _iso_to_readable(iso_ts: str, fmt: str = "%b %d, %Y %I:%M %p") -> str:
#     """Convert ISO timestamp (with 'Z' or offset) to a readable string in local zone.
#     Default format omits the timezone name (no 'India Standard Time')."""
#     if not iso_ts:
#         return None
#     try:
#         # allow both '2025-11-10T10:57:07.330Z' and offset forms
#         dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
#         # convert to local timezone and format (fmt no longer includes %Z)
#         return dt.astimezone().strftime(fmt)
#     except Exception:
#         return iso_ts


# # -------------------------------
# # MAIN FUNCTION:
# # PHONE → USER → LOCATION → CHATS
# # -------------------------------
# def get_user_summary_by_phone(identifier: str) -> dict:
#     """
#     Lookup user by phone or email (identifier). If identifier contains '@' we treat it as email,
#     otherwise we try phone-number fields.
#     """
#     if db is None:
#         return {
#             "found": False,
#             "error": "Firestore client not initialized. Check service-account JSON."
#         }

#     try:    
#         # Decide search type
#         search_by_email = "@" in (identifier or "")

#         user_doc = None
#         if search_by_email:
#             # try common email fields (fixed: use a tuple of field names, not a string)
#             for email_field in ("email", "emailAddress", "userEmail"):
#                 try:
#                     logging.debug("Querying users where %s == %s", email_field, identifier)
#                     q = db.collection("users").where(email_field, "==", identifier).limit(1).get()
#                     if q:
#                         user_doc = q[0]
#                         break
#                 except Exception:
#                     logging.exception("query failed for email_field=%s", email_field)
#                     continue
#         else:
#             # try common phone fields
#             for phone_field in ("phoneNumber", "phone", "phone_number"):
#                 try:
#                     logging.debug("Querying users where %s == %s", phone_field, identifier)
#                     q = db.collection("users").where(phone_field, "==", identifier).limit(1).get()
#                     if q:
#                         user_doc = q[0]
#                         break
#                 except Exception:
#                     logging.exception("query failed for phone_field=%s", phone_field)
#                     continue

#         if not user_doc:
#             return {"found": False, "message": "User not found"}

#         user_data = user_doc.to_dict() or {}
#         user_id = user_data.get("uid") or user_doc.id

#         # --------------------------------------
#         # 2️⃣ FETCH LATEST LOCATION
#         # from top-level collection user_locations
#         # --------------------------------------
#         latest_location = None

#         loc_query = (
#             db.collection("user_locations")
#               .where("user_id", "==", user_id)
#               .order_by("created_at", direction=gfirestore.Query.DESCENDING)
#               .limit(1)
#               .get()
#         )

#         if loc_query:
#             loc_doc = loc_query[0]
#             loc_data = loc_doc.to_dict() or {}
#             loc_data["id"] = loc_doc.id

#             # normalize created_at → ISO and add readable variant
#             if "created_at" in loc_data:
#                 iso = _ts_to_iso(loc_data["created_at"])
#                 loc_data["created_at"] = iso
#                 loc_data["created_at_readable"] = _iso_to_readable(iso)
#             if "createdAt" in loc_data:
#                 iso2 = _ts_to_iso(loc_data["createdAt"])
#                 loc_data["createdAt"] = iso2
#                 loc_data["createdAt_readable"] = _iso_to_readable(iso2)

#             latest_location = loc_data

#         # --------------------------------------
#         # 3️⃣ CHATS FOR THIS USER
#         # participants[] contains userId
#         # --------------------------------------
#         # Count chats
#         chats = (
#             db.collection("chats")
#               .where("participants", "array_contains", user_id)
#               .get()
#         )
#         chat_count = len(chats)

#         # latest created_at
#         latest_chat_created_at = None
#         created_q = (
#             db.collection("chats")
#               .where("participants", "array_contains", user_id)
#               .order_by("created_at", direction=gfirestore.Query.DESCENDING)
#               .limit(1)
#               .get()
#         )
#         if created_q:
#             latest_chat_created_at = _ts_to_iso(
#                 created_q[0].to_dict().get("created_at")
#             )

#         # latest updated_at
#         latest_chat_updated_at = None
#         updated_q = (
#             db.collection("chats")
#               .where("participants", "array_contains", user_id)
#               .order_by("updated_at", direction=gfirestore.Query.DESCENDING)
#               .limit(1)
#               .get()
#         )
#         if updated_q:
#             latest_chat_updated_at = _ts_to_iso(
#                 updated_q[0].to_dict().get("updated_at")
#             )

#         # add readable variants (fix: derive from latest_location fields, not from whole dict)
#         latest_location_created_readable = None
#         if latest_location:
#             iso_loc = latest_location.get("created_at") or latest_location.get("createdAt")
#             latest_location_created_readable = _iso_to_readable(iso_loc) if iso_loc else None

#         # make readable versions for chat timestamps
#         readable_chat_created = _iso_to_readable(latest_chat_created_at) if latest_chat_created_at else None
#         readable_chat_updated = _iso_to_readable(latest_chat_updated_at) if latest_chat_updated_at else None

#         # --------------------------------------
#         # 4️⃣ FINAL JSON RESPONSE
#         # --------------------------------------
#         return {
#             "found": True,
#             "userId": user_id,
#             "user": user_data,
#             "latest_location": latest_location,
#             "chat_count": chat_count,
#             "latest_chat_createdAt": latest_chat_created_at,
#             "latest_chat_updatedAt": latest_chat_updated_at,
#             "latest_location_createdAt_readable": latest_location_created_readable,
#             "latest_chat_createdAt_readable": readable_chat_created,
#             "latest_chat_updatedAt_readable": readable_chat_updated,
#         }

#     except Exception as e:
#         logging.exception("get_user_summary_by_phone error: %s", e)
#         return {"found": False, "error": str(e)}


# # -------------------------------
# # FIREBASE HTTPS ENDPOINT
# # -------------------------------
# @https_fn.on_request()
# def userSummaryByPhoneEndpoint(req: Request) -> Response:
#     try:
#         data = req.get_json(silent=True) or {}
#         # accept either phone or email (or identifier)
#         phone = data.get("phone") or data.get("phoneNumber") or data.get("phone_number")
#         email = data.get("email") or data.get("emailAddress")
#         identifier = email if email else phone

#         if not identifier:
#             return Response("Missing 'phone' or 'email' in request body", status=400)

#         summary = get_user_summary_by_phone(identifier)
#         status = 200 if summary.get("found") else 404

#         return Response(
#             json.dumps(summary, ensure_ascii=False),
#             status=status,
#             content_type="application/json",
#         )

#     except Exception as e:
#         logging.exception("userSummaryByPhoneEndpoint error: %s", e)
#         return Response(f"Error: {e}", status=500)


# # -------------------------------
# # CLI EXECUTION
# # python customerService.py --phone "+91xxxxx"
# # -------------------------------
# def main():
#     parser = argparse.ArgumentParser(
#         description="Lookup user by phone or email and return summary"
#     )
#     group = parser.add_mutually_exclusive_group(required=True)
#     group.add_argument("--phone", help="Phone number (e.g. +919810091221)")
#     group.add_argument("--email", help="Email address (e.g. user@example.com)")
#     args = parser.parse_args()

#     identifier = args.email if args.email else args.phone
#     summary = get_user_summary_by_phone(identifier)
#     print(json.dumps(summary, indent=2, ensure_ascii=False))


# if __name__ == "__main__":
#     main()
