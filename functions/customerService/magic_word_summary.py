# magicwordService.py
import logging
import secrets
from google.cloud import firestore as gfirestore
from google.cloud.firestore import FieldFilter
from firebase_setup import get_project_b_firestore
from customerService.user_summary import _ts_to_iso, _iso_to_readable  # reuse helpers

def _get_db():
    return get_project_b_firestore()


def _attach_traveller_info(db, items: list) -> None:
    """
    Batch-resolve display name/phone for a list of magicWordUser items via
    their userId, so the frontend doesn't have to fall back to a generic
    "Traveller" label when the request document itself has no name field.
    Mutates `items` in place; safe no-op if there are no userIds or lookups fail.
    """
    user_ids = sorted({d.get("userId") for d in items if d.get("userId")})
    if not user_ids:
        return

    try:
        refs = [db.collection("users").document(uid) for uid in user_ids]
        user_map = {}
        for snap in db.get_all(refs):
            if not snap.exists:
                continue
            u = snap.to_dict() or {}
            full_name = f"{u.get('firstName', '')} {u.get('lastName', '')}".strip()
            user_map[snap.id] = {
                "name": full_name or u.get("name") or "",
                "phone": u.get("phoneNumber") or u.get("phone") or u.get("phone_number") or "",
            }

        for d in items:
            info = user_map.get(d.get("userId"))
            if not info:
                continue
            if info["name"]:
                d["traveller_name"] = info["name"]
            if info["phone"]:
                d["traveller_phone"] = info["phone"]
    except Exception as e:
        logging.warning("Could not resolve traveller info for magic word items: %s", e)


def get_magicword_requests(limit: int = 1000) -> dict:
    """
    Fetch magic word triggers from magicWordUser where status is "requested" OR "inProgress".
    Returns a list sorted by matchedAt desc (newest first).
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"found": False, "error": "Firestore client not initialized"}

    try:
        col = db.collection("magicWordUser")
        
        # ✅ Fetch documents where status is "requested" OR "inProgress"
        q = (
        col.where(filter=FieldFilter("status", "in", ["requested", "inProgress"]))
       .order_by("matchedAt", direction=gfirestore.Query.DESCENDING)
       .limit(limit)
       .get()   
            )

        items = []
        for doc in q:
            d = doc.to_dict() or {}
            d["id"] = doc.id

            # normalize matchedAt timestamp
            if "matchedAt" in d:
                iso = _ts_to_iso(d["matchedAt"])
                d["matchedAt"] = iso
                d["matchedAt_readable"] = _iso_to_readable(iso)

            # normalize timestamp fields if present
            if "created_at" in d:
                iso = _ts_to_iso(d["created_at"])
                d["created_at"] = iso
                d["created_at_readable"] = _iso_to_readable(iso)

            if "updated_at" in d:
                iso2 = _ts_to_iso(d["updated_at"])
                d["updated_at"] = iso2
                d["updated_at_readable"] = _iso_to_readable(iso2)

            items.append(d)

        _attach_traveller_info(db, items)

        logging.info(
            "Fetched %s magic word requests with status in ['requested', 'inProgress']",
            len(items),
        )
        
        # ✅ Debug: Show all documents if none found
        if len(items) == 0:
            logging.warning("No items found with status=['requested', 'inProgress']")
            all_docs = col.stream()
            all_items = []
            for doc in all_docs:
                all_items.append({"id": doc.id, "status": doc.get("status")})
            logging.info("Sample magicWordUser documents: %s", all_items[:10])
        
        return {"found": True, "count": len(items), "items": items}

    except Exception as e:
        logging.exception("get_magicword_requests error: %s", e)
        return {"found": False, "error": str(e)}


def get_magicword_detail(magic_word_user_id: str) -> dict:
    """
    Fetch full details for a magic word request by ID.
    Chain: magicWordUser → chat (get userId from participants) → user + user_locations
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"found": False, "error": "Firestore client not initialized"}

    try:
        # 1️⃣ Get magicWordUser document
        magic_doc = db.collection("magicWordUser").document(magic_word_user_id).get()
        if not magic_doc.exists:
            return {"found": False, "error": "Magic word user record not found"}

        magic_data = magic_doc.to_dict() or {}
        chat_id = magic_data.get("chatId")

        if not chat_id:
            return {"found": False, "error": "Chat ID not found in magic word record"}

        # 2️⃣ Get chat document to find user_id from participants
        chat_doc = db.collection("chats").document(chat_id).get()
        if not chat_doc.exists:
            return {"found": False, "error": "Chat not found"}

        chat_data = chat_doc.to_dict() or {}
        chat_data["id"] = chat_doc.id
        
        # 3️⃣ Get User ID
        participants = chat_data.get("participants", [])
        user_id = None
        for p in participants:
            if p not in ["System", "system", "CustomerService"]:
                user_id = p
                break

        if user_id:
            # 4️⃣ Get User Details
            user_doc = db.collection("users").document(user_id).get()
            if user_doc.exists:
                user_data = user_doc.to_dict() or {}
                user_data["id"] = user_id

            # 5️⃣ Get User Location
            try:
                location_query = (
                    db.collection("user_locations")
                    .where(filter=FieldFilter("user_id", "==", user_id))
                    .order_by("created_at", direction=gfirestore.Query.DESCENDING)
                    .limit(1)
                )
                location_docs = location_query.get()
                if location_docs:
                    user_location_data = location_docs[0].to_dict() or {}
                    if "created_at" in user_location_data:
                        iso = _ts_to_iso(user_location_data["created_at"])
                        user_location_data["created_at"] = iso
                        user_location_data["created_at_readable"] = _iso_to_readable(iso)
            except Exception as loc_error:
                logging.warning(f"⚠️ Error fetching user location: {loc_error}")

        # 5️⃣ Normalize magic word timestamps
        if "matchedAt" in magic_data:
            iso = _ts_to_iso(magic_data["matchedAt"])
            magic_data["matchedAt"] = iso
            magic_data["matchedAt_readable"] = _iso_to_readable(iso)

        logging.info("Returning details for %s. Found=True", magic_word_user_id)
        
        # 6️⃣ Return complete detail
        return {
            "found": True,
            "id": magic_word_user_id,
            "magic_word_request": magic_data,
            "chat": {
                "id": chat_id,
                "type": chat_data.get("chat_type"),
                "location": chat_data.get("location"),
                "created_at": chat_data.get("created_at"),
            },
            "user": {
                "id": user_id,
                "email": user_data.get("email"),
                "firstName": user_data.get("firstName"),
                "lastName": user_data.get("lastName"),
                "phoneNumber": user_data.get("phoneNumber"),
                "photoURL": user_data.get("photoURL"),
            },
            "user_location": user_location_data,
        }

    except Exception as e:
        logging.exception(f"get_magicword_detail error: %s", e)
        return {"found": False, "error": str(e)}


def get_user_magicword_requests(user_id: str, limit: int = 50) -> dict:
    """
    Fetch magic word requests for a specific user where status is NOT completed.
    (status in ["requested", "inProgress"])
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"found": False, "error": "Firestore client not initialized"}

    try:
        col = db.collection("magicWordUser")
        
        # Filter by userId AND status
        # ⚠️ Removed order_by to avoid creating a composite index for now. Sorting in memory.
        q = (
            col.where(filter=FieldFilter("userId", "==", user_id))
            .where(filter=FieldFilter("status", "in", ["requested", "inProgress"]))
            .limit(limit)
            .get()
        )

        items = []
        for doc in q:
            d = doc.to_dict() or {}
            d["id"] = doc.id

            if "matchedAt" in d:
                iso = _ts_to_iso(d["matchedAt"])
                d["matchedAt"] = iso
                d["matchedAt_readable"] = _iso_to_readable(iso)
            
            if "created_at" in d:
                iso = _ts_to_iso(d["created_at"])
                d["created_at"] = iso
                d["created_at_readable"] = _iso_to_readable(iso)

            items.append(d)

        # ✅ Sort in memory (newest first)
        items.sort(key=lambda x: x.get("matchedAt", "") or "", reverse=True)

        return {"found": True, "count": len(items), "requests": items}

    except Exception as e:
        logging.exception(f"get_user_magicword_requests error: %s", e)
        return {"found": False, "error": str(e)}


def get_user_completed_orders(user_id: str, limit: int = 50) -> dict:
    """
    Fetch orders from 'serviceOrder' collection.
    Filter: uid == user_id
    Sort: updated_at desc (or created_at if updated_at missing)
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"found": False, "error": "Firestore client not initialized"}

    try:
        col = db.collection("serviceJsonOrder")
        
        # Filter by uid
        q = (
            col.where(filter=FieldFilter("user_id", "==", user_id))
            .limit(limit)
            .get()
        )

        items = []
        for doc in q:
            d = doc.to_dict() or {}
            d["id"] = doc.id

            # Normalize timestamp for display
            # User asked for 'updateAt' (updated_at). Fallback to created_at if needed.
            ts_val = d.get("updated_at") or d.get("created_at")
            if ts_val:
                iso_val = _ts_to_iso(ts_val)
                d["timestamp"] = _iso_to_readable(iso_val)
                d["timestamp_iso"] = iso_val
            else:
                d["timestamp"] = "N/A"
                d["timestamp_iso"] = None

            # Ensure fields exist for frontend - fall back to the
            # serviceRequest/serviceJsonOrder field names (service_id,
            # service_name, booking_status) for orders created via the
            # dynamic per-service form.
            d["item_id"] = d.get("item_id") or d.get("service_id") or "N/A"
            d["product_type"] = d.get("product_type") or d.get("service_name") or "N/A"
            d["status"] = d.get("status") or d.get("booking_status") or "N/A"

            items.append(d)

        # ✅ Sort in memory (newest first) by updated_at (or created_at as fallback)
        items.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)

        return {"found": True, "count": len(items), "orders": items}

    except Exception as e:
        logging.exception(f"get_user_completed_orders error: %s", e)
        return {"found": False, "error": str(e)}


def get_user_payment_history(user_id: str, limit: int = 50) -> dict:
    """
    Fetch payment history from 'order' collection.
    Filter: uid == user_id AND paymentStatus == 'Success'
    Sort: createdAt desc
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"found": False, "error": "Firestore client not initialized"}

    try:
        col = db.collection("order")
        
        # Filter by uid AND paymentStatus == 'Success'
        q = (
            col.where(filter=FieldFilter("uid", "==", user_id))
            .where(filter=FieldFilter("paymentStatus", "==", "Success"))
            .limit(limit)
            .get()
        )

        items = []
        for doc in q:
            d = doc.to_dict() or {}
            d["id"] = doc.id
            
            # Normalize timestamp for display if needed
            # createdAt in 'order' seems to be a string based on the screenshot, but we can try to parse if needed or just use it.
            # Ideally rely on client side formatting or simple string usage if it's ISO.
            
            items.append(d)

        # ✅ Sort in memory (newest first)
        # createdAt format in screenshot: "2025-08-12T17:42:54.224528Z" -> Lexicographical sort works for ISO strings
        items.sort(key=lambda x: str(x.get("createdAt", "") or ""), reverse=True)

        return {"found": True, "count": len(items), "payments": items}

    except Exception as e:
        logging.exception(f"get_user_payment_history error: %s", e)
        return {"found": False, "error": str(e)}


def create_order_for_magic_word(magic_word_user_id: str, magic_word_data: dict) -> dict:
    """
    Create an order in the 'order' collection when magic word status changes to inProgress.
    Also updates the magicWordUser document with the orderId.
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        # Get magic word details
        magic_doc = db.collection("magicWordUser").document(magic_word_user_id).get()
        if not magic_doc.exists:
            return {"success": False, "error": "Magic word user record not found"}

        magic_data = magic_doc.to_dict() or {}
        chat_id = magic_data.get("chatId")
        user_id = magic_data.get("userId")
        magic_word = magic_data.get("magicWord")

        if not all([chat_id, user_id, magic_word]):
            return {"success": False, "error": "Missing required data for order creation"}

        # Create order document
        order_data = {
            "chatId": chat_id,
            "userId": user_id,
            "magicWordId": magic_data.get("magicWordId"),
            "magicWord": magic_word,
            "location": magic_data.get("location"),
            "status": "pending",
            "created_at": _get_iso_timestamp(),
            "magic_word_user_id": magic_word_user_id,
            "userMessage": magic_data.get("userMessage"),
            "assistantMessage": magic_data.get("assistantMessage"),
        }

        # Add order to collection (auto-generate ID)
        order_ref = db.collection("magicOrder").add(order_data)
        order_id = order_ref[1].id

        # ✅ Update magicWordUser document with orderId
        db.collection("magicWordUser").document(magic_word_user_id).update({
            "orderId": order_id,
            "updated_at": _get_iso_timestamp()
        })

        logging.info(f"✅ Order created: {order_id} for magic word {magic_word_user_id}")
        logging.info(f"✅ Updated magicWordUser {magic_word_user_id} with orderId: {order_id}")
        logging.info(
            "Created order %s for magic word %s and linked magicWordUser %s",
            order_id,
            magic_word,
            magic_word_user_id,
        )

        return {
            "success": True,
            "order_id": order_id,
            "message": "Order created successfully and linked to magic word user"
        }

    except Exception as e:
        logging.exception(f"Error creating order: {e}")
        return {"success": False, "error": str(e)}


def send_message_to_chat(chat_id: str, user_id: str, magic_word: str) -> dict:
    """
    Send a message to the chat when magic word status changes to completed.
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"success": False, "error": "Firestore client not initialized"}

    try:

        chat_doc = db.collection("chats").document(chat_id).get()
        chat_location = None
        if chat_doc.exists:
            chat_data = chat_doc.to_dict() or {}
            chat_location = chat_data.get("location")

        message_data = {
            "role": "assistant",
            "content": f"Your '{magic_word}' request has been processed and completed. Our team will contact you shortly with updates.",
            "created_at": _get_iso_timestamp(),
            "location": chat_location,
            "user_id": "CustomerService",  # ✅ Identify sender
        }

        # Add message to chat's messages subcollection
        message_ref = db.collection("chats").document(chat_id).collection("messages").add(message_data)
        message_id = message_ref[1].id

        logging.info(f"✅ Message sent to chat {chat_id}: {message_id}")
        logging.info(
            "Sent completion message to chat %s with message %s for magic word '%s'",
            chat_id,
            message_id,
            magic_word,
        )

        return {
            "success": True,
            "message_id": message_id,
            "message": "Message sent successfully"
        }

    except Exception as e:
        logging.exception(f"Error sending message: {e}")
        return {"success": False, "error": str(e)}
    
def send_service_request_message(chat_id: str, magic_word: str, booking_details: dict = None) -> dict:
    """
    Send a confirmation message to the chat when service request is created.
    ✅ Now handles otherSpecify for custom services
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        from datetime import datetime
        sd = booking_details or {}
        service_id = sd.get("typeOfService", "")
        service_name = sd.get("serviceName") or _get_service_name(service_id) or "Service"
        
        # ✅ NEW: Handle otherSpecify for custom services
        other_specify = sd.get("otherSpecify", "")
        if service_id == "other" and other_specify:
            service_name = f"{service_name} - {other_specify}"
            logging.info("Custom service specified: %s", service_name)
        
        date_of_travel = sd.get("dateOfTravel", "N/A")

        ts = sd.get("timeSlot", {}) if isinstance(sd.get("timeSlot"), dict) else {}
        slot_label = ts.get("label", "N/A")

        message_text = (
            f"We've logged your request, and it's all set on our end.\n\n"
            f"🧾 Service: {service_name}\n\n"
            f"To move ahead, just follow these quick steps in the app:\n\n"
            f"👤 Profile → 🛒 Cart → 👜 My Order\n\n"
            f"-👤 Profile - check or update your details\n\n"
            f"-🛒 Cart - place your order\n\n"
            f"-👜 My Order - track the status once your order is placed\n\n"
            f"Our team will take it from here and keep you updated. If you need any help, just let me know 🙂"
        )
        
        chat_doc = db.collection("chats").document(chat_id).get()
        chat_location = chat_doc.to_dict().get("location") if chat_doc.exists else None
        
        message_data = {
            "role": "assistant",
            "content": message_text,
            "created_at": _get_iso_timestamp(),
            "location": chat_location,
            "user_id": "CustomerService",
        }
        
        db.collection("chats").document(chat_id).collection("messages").add(message_data)
        
        logging.info(f"✅ Service request message sent to chat {chat_id}")
        logging.info("Sent service request message to chat %s for service %s", chat_id, service_name)
        
        return {"success": True, "message": "Service request message sent"}
    
    except Exception as e:
        logging.exception(f"Error sending service request message: {e}")
        return {"success": False, "error": str(e)}


# def send_service_request_message(chat_id: str, magic_word: str, booking_details: dict = None) -> dict:
#     """
#     Send a confirmation message to the chat when service request is created.
#     """
#     if db is None:
#         return {"success": False, "error": "Firestore client not initialized"}

#     try:
#         from datetime import datetime
#         sd = booking_details or {}
#         service_id = sd.get("typeOfService", "")
#         service_name = sd.get("serviceName") or _get_service_name(service_id) or "Service"
#         date_of_travel = sd.get("dateOfTravel", "N/A")

#         ts = sd.get("timeSlot", {}) if isinstance(sd.get("timeSlot"), dict) else {}
#         slot_label = ts.get("label", "N/A")
#         start_time = ts.get("startTime") or ts.get("start_time") or ""
#         end_time = ts.get("endTime") or ts.get("end_time") or ""

#         message_text = (
#             f"✅ Your request has been created\n\n"
#             f"🧾 Service: {service_name} or {service_id}\n"
#             f"Our team will contact you shortly."
#             )
        
#         # message_text = f"✅ Service request created for magic word: {magic_word}\n\nYour service request has been submitted and is being processed. You will receive updates shortly."
        
#         chat_doc = db.collection("chats").document(chat_id).get()
#         chat_location = chat_doc.to_dict().get("location") if chat_doc.exists else None
#         # Add message to chat
#         message_data = {
#             "role": "assistant",
#             "content": message_text,
#             "user_id": "SystemG",  # System message sender
#             "created_at": _get_iso_timestamp(),
#             "location": chat_location,
#         }

        
           
        
#         db.collection("chats").document(chat_id).collection("messages").add(message_data)
        
#         logging.info(f"✅ Service request message sent to chat {chat_id}")
#         print(f"📨 SERVICE REQUEST MESSAGE: Chat={chat_id}, Magic Word={magic_word}")
        
#         return {"success": True, "message": "Service request message sent"}
    
#     except Exception as e:
#         logging.exception(f"Error sending service request message: {e}")
#         return {"success": False, "error": str(e)}


def send_booking_confirmation_message(chat_id: str, booking_details: dict) -> dict:
    """
    Send a booking confirmation message to the chat when order is created.
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        from datetime import datetime
        
        # Build confirmation message
        service_type = booking_details.get("typeOfService", "Service")
        service_name = booking_details.get("serviceName") or "Service"
        total_price = booking_details.get("pricing", {}).get("totalPayable", 0) if isinstance(booking_details.get("pricing"), dict) else 0
        
        message_text = f"""
🎫 Booking Confirmed!

📋 Service Type: {service_type}
📋 Service: {service_name}
💰 Total Amount: ₹{total_price}
📅 Date: {booking_details.get('dateOfTravel', 'N/A')}
🕐 Time Slot: {booking_details.get('timeSlot', {}).get('label', 'N/A') if isinstance(booking_details.get('timeSlot'), dict) else 'N/A'}

Your booking has been confirmed! Thank you for choosing our service.
"""
        
        # # Add message to chat
        # message_data = {
        #     "sender_id": "system",
        #     "sender_name": "System",
        #     "message": message_text.strip(),
        #     "message_type": "text",
        #     "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        #     "read": False,
        # }

        chat_doc = db.collection("chats").document(chat_id).get()
        chat_location = chat_doc.to_dict().get("location") if chat_doc.exists else None

        message_data = {
            "role": "assistant",
            "content": message_text,
            "created_at": _get_iso_timestamp(),
            "location": chat_location,
            # "user_id": "CustomerService",  # ✅ Identify sender
        }
        
        db.collection("chats").document(chat_id).collection("messages").add(message_data)
        
        logging.info(f"✅ Booking confirmation message sent to chat {chat_id}")
        logging.info(
            "Sent booking confirmation to chat %s for service %s with total %s",
            chat_id,
            service_type,
            total_price,
        )
        
        return {"success": True, "message": "Booking confirmation message sent"}
    
    except Exception as e:
        logging.exception(f"Error sending booking confirmation message: {e}")
        return {"success": False, "error": str(e)}

def _get_service_name(service_id: str) -> str:
    service_type_map = {
        "guide": "Tour Guide Service",
        "photographer": "Photography Service",
        "blog": "Blog/Postcard Service",
        "souvenir": "Souvenir Package",
        "other": "Other",
    }
    service_type = service_id.split("_")[0].lower() if "_" in service_id else str(service_id).lower()
    return service_type_map.get(service_type, "Service")


def _get_service_type(service_id: str) -> str:
    if "_" in str(service_id):
        return str(service_id).split("_")[0].lower()
    return str(service_id).lower()


def _get_primary_service(cart_items: list, fallback_service_id: str = "", fallback_service_name: str = "") -> dict:
    primary_item = (cart_items or [None])[0] or {}
    service_id = primary_item.get("item_id") or fallback_service_id or ""
    service_name = primary_item.get("name") or fallback_service_name or _get_service_name(service_id)
    service_type = _get_service_type(service_id) if service_id else ""
    return {
        "service_id": service_id,
        "service_name": service_name,
        "service_type": service_type,
    }


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y")
    return False


def _pick(d: dict, *keys, default=None):
    """Pick first non-None value from multiple possible keys."""
    for k in keys:
        if d is None:
            break
        if k in d and d.get(k) is not None:
            return d.get(k)
    return default

def _get_monument_title(monument_id: str) -> str:
    """
    ✅ Fetch monument title from serviceMonument collection by ID
    """
    if not monument_id:
        return ""
    
    try:
        db = _get_db()
        monument_doc = db.collection("serviceMonument").document(monument_id).get()
        if monument_doc.exists:
            monument_data = monument_doc.to_dict() or {}
            return monument_data.get("title") or monument_data.get("name") or ""
        return ""
    except Exception as e:
        logging.warning(f"⚠️ Error fetching monument title for {monument_id}: {e}")
        return ""


def _generate_otp() -> str:
    """4-digit OTP, randomly generated server-side so support agents never
    set (or accidentally reuse) an OTP by hand."""
    return f"{secrets.randbelow(10000):04d}"


def _load_service_catalog_entry(service_id: str) -> dict:
    """Look up a concierge service's display info (name/description/formTemplate)
    from service.json, so it's always sourced from the catalog rather than
    trusted from the request body."""
    if not service_id:
        return {}
    try:
        import json
        import os

        catalog_path = os.path.join(
            os.path.dirname(__file__),
            "templates", "customer_support", "data", "service.json",
        )
        with open(catalog_path, "r", encoding="utf-8") as f:
            services = (json.load(f) or {}).get("services", [])
        return next((s for s in services if s.get("serviceId") == service_id), {}) or {}
    except Exception as e:
        logging.warning("⚠️ Could not load service catalog entry for %s: %s", service_id, e)
        return {}


def create_service_request(magic_word_user_id: str, magic_word_data: dict, service_details: dict = None) -> dict:
    """
    ✅ Creates a serviceRequest document from the support panel's dynamic,
    per-service form (service dropdown -> formFields from data/form/<id>.json).
    The chat conversation already confirmed this request with the customer,
    so booking_status is always "booked" - payment_status separately tracks
    whether support has collected/confirmed payment yet.
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        magic_data = magic_word_data or {}
        chat_id = magic_data.get("chatId") or magic_data.get("chat_id")
        user_id = magic_data.get("userId") or magic_data.get("user_id")
        magic_word = magic_data.get("magicWord") or magic_data.get("magic_word")

        if not all([chat_id, user_id, magic_word]):
            return {"success": False, "error": "Missing required data for service request"}

        sd = service_details or {}
        service_id = _pick(sd, "serviceId", "typeOfService", default="") or ""
        payment_status = sd.get("paymentStatus", "pending")
        field_values = sd.get("fieldValues") or {}
        price_summary = sd.get("priceSummary") or {"items": [], "total": 0}

        catalog_entry = _load_service_catalog_entry(service_id)

        now = _get_iso_timestamp()
        request_data = {
            "action": "Create Service Request",
            "booking_status": "booked",
            "created_at": now,
            "updated_at": now,

            "user_id": user_id,
            "service_id": service_id,
            "service_name": catalog_entry.get("serviceName", ""),
            "service_description": catalog_entry.get("serviceDescription", ""),
            "form_template": catalog_entry.get("formTemplate", ""),

            "payment_status": payment_status,
            "field_values": field_values,
            "price_summary": price_summary,

            "start_otp": _generate_otp(),
            "end_otp": _generate_otp(),
        }

        doc_ref = db.collection("serviceRequest").document()
        doc_ref.set({**request_data, "request_id": doc_ref.id})
        service_request_id = doc_ref.id

        db.collection("magicWordUser").document(magic_word_user_id).update({
            "serviceRequestId": service_request_id,
            "updated_at": now,
        })

        return {
            "success": True,
            "service_request_id": service_request_id,
            "payment_status": payment_status,
        }

    except Exception as e:
        logging.exception(f"Error creating service request: {e}")
        return {"success": False, "error": str(e)}


def create_service_order(magic_word_user_id: str, service_request_id: str, booking_details: dict = None) -> dict:
    """
    ✅ Creates a serviceJsonOrder document, carrying the field_values,
    price_summary and OTPs over from its serviceRequest as-is (the OTPs are
    generated once, at request time, and stay the same on the order - never
    regenerated or hand-entered here).
    """
    try:
        db = _get_db()
    except Exception as e:
        logging.exception("Failed to init Firestore client: %s", e)
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        request_doc = db.collection("serviceRequest").document(service_request_id).get()
        if not request_doc.exists:
            return {"success": False, "error": f"Service request {service_request_id} not found"}

        request_data = request_doc.to_dict() or {}
        price_summary = request_data.get("price_summary") or {"items": [], "total": 0}

        now = _get_iso_timestamp()
        order_data = {
            "action": "Create Service Order",
            "booking_status": "booked",
            "created_at": now,
            "updated_at": now,

            "request_id": service_request_id,
            "user_id": request_data.get("user_id"),
            "service_id": request_data.get("service_id"),
            "service_name": request_data.get("service_name"),
            "service_description": request_data.get("service_description"),
            "form_template": request_data.get("form_template"),

            # An order is only ever created once payment has succeeded, so this
            # is always "Success" here (matching payment_details.payment_status
            # below).
            "payment_status": "Success",

            "field_values": request_data.get("field_values", {}),
            "price_summary": price_summary,

            "start_otp": request_data.get("start_otp", ""),
            "end_otp": request_data.get("end_otp", ""),

            # No real payment gateway call happens from the support panel -
            # support just confirms payment was received, so this is a manual
            # placeholder rather than a real Razorpay payment record.
            "payment_details": {
                "amount": price_summary.get("total", 0),
                "order_id": None,
                "payment_id": None,
                "provider": "manual",
                "signature": None,
                "status": "Success",
                "payment_status": "Success",
            },
            "vendor_id": None,
        }

        doc_ref = db.collection("serviceJsonOrder").document()
        doc_ref.set({**order_data, "order_id": doc_ref.id})
        order_id = doc_ref.id

        logging.info(
            "Service order created: order_id=%s request_id=%s total=%s",
            order_id, service_request_id, price_summary.get("total", 0),
        )

        return {
            "success": True,
            "service_order_id": order_id,
            "price": price_summary.get("total", 0),
        }

    except Exception as e:
        logging.exception(f"Error creating service order: {e}")
        return {"success": False, "error": str(e)}


def _get_iso_timestamp() -> str:
    """Get current timestamp in ISO format"""
    from datetime import datetime
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


