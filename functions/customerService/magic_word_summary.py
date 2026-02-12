# magicwordService.py
import logging
from google.cloud import firestore as gfirestore
from google.cloud.firestore import FieldFilter
from firebase_setup import get_project_b_firestore
from customerService.user_summary import _ts_to_iso, _iso_to_readable  # reuse helpers

try:
    db = get_project_b_firestore()
except Exception as e:
    db = None
    logging.exception("Failed to init Firestore client: %s", e)


def get_magicword_requests(limit: int = 1000) -> dict:
    """
    Fetch magic word triggers from magicWordUser where status is "requested" OR "inProgress".
    Returns a list sorted by matchedAt desc (newest first).
    """
    if db is None:
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

        print(f"✅ Fetched {len(items)} magic word requests with status in ['requested', 'inProgress']")
        
        # ✅ Debug: Show all documents if none found
        if len(items) == 0:
            print("⚠️ No items found with status=['requested', 'inProgress']")
            all_docs = col.stream()
            all_items = []
            for doc in all_docs:
                all_items.append({"id": doc.id, "status": doc.get("status")})
            print(f"📋 All documents in magicWordUser: {all_items[:10]}")  # Show first 10
        
        return {"found": True, "count": len(items), "items": items}

    except Exception as e:
        logging.exception("get_magicword_requests error: %s", e)
        print(f"❌ ERROR: {str(e)}")  # ✅ Print error
        return {"found": False, "error": str(e)}


def get_magicword_detail(magic_word_user_id: str) -> dict:
    """
    Fetch full details for a magic word request by ID.
    Chain: magicWordUser → chat (get userId from participants) → user + user_locations
    """
    if db is None:
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

        print(f"✅ Returning details for {magic_word_user_id}. Found=True")
        
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
    if db is None:
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
    if db is None:
        return {"found": False, "error": "Firestore client not initialized"}

    try:
        col = db.collection("serviceOrder")
        
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

            # Ensure fields exist for frontend
            d["item_id"] = d.get("item_id", "N/A")
            d["product_type"] = d.get("product_type", "N/A")
            d["status"] = d.get("status", "N/A")

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
    if db is None:
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
    if db is None:
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
        print(f"📋 CREATE ORDER: Order ID={order_id}, Magic Word={magic_word}, User ID={user_id}")
        print(f"📋 LINKED: Magic Word User ID={magic_word_user_id} now has orderId={order_id}")

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
    if db is None:
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
        print(f"📨 SEND MESSAGE: Chat ID={chat_id}, Message ID={message_id}, Magic Word='{magic_word}'")

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
    if db is None:
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
            print(f"✅ CUSTOM SERVICE: {service_name}")
        
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
            # "user_id": "CustomerService",  # ✅ Identify sender
        }
        
        db.collection("chats").document(chat_id).collection("messages").add(message_data)
        
        logging.info(f"✅ Service request message sent to chat {chat_id}")
        print(f"📨 SERVICE REQUEST MESSAGE: Chat={chat_id}, Service={service_name}")
        
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
    if db is None:
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
        print(f"📨 BOOKING CONFIRMATION: Chat={chat_id}, Service={service_type}, Total=₹{total_price}")
        
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


def _get_selected_service_types(cart_items: list) -> list:
    service_types = set()
    for item in cart_items or []:
        # ✅ in the new schema we store item_id
        item_id = item.get("item_id", "")
        if item_id:
            service_types.add(_get_service_type(item_id))
    return list(service_types)


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
    if db is None or not monument_id:
        return ""
    
    try:
        monument_doc = db.collection("serviceMonument").document(monument_id).get()
        if monument_doc.exists:
            monument_data = monument_doc.to_dict() or {}
            return monument_data.get("title") or monument_data.get("name") or ""
        return ""
    except Exception as e:
        logging.warning(f"⚠️ Error fetching monument title for {monument_id}: {e}")
        return ""


def create_service_request(magic_word_user_id: str, magic_word_data: dict, service_details: dict = None) -> dict:
    """
    ✅ Creates service request - Status depends on payment
    - If payment_status = "success" → status = "OrderSuccess"
    - Otherwise → status = "draft"
    """
    if db is None:
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        magic_data = magic_word_data or {}
        chat_id = magic_data.get("chatId") or magic_data.get("chat_id")
        user_id = magic_data.get("userId") or magic_data.get("user_id")
        magic_word = magic_data.get("magicWord") or magic_data.get("magic_word")

        if not all([chat_id, user_id, magic_word]):
            return {"success": False, "error": "Missing required data for service request"}

        sd = service_details or {}
        payment_status = sd.get("paymentStatus", "pending")
        
        # ✅ Set service request status based on payment
        if payment_status == "success":
            sr_status = "Ordered Success"  # ✅ Payment successful
            print(f"✅ Payment successful - Setting status to: Ordered Success")
        else:
            sr_status = "draft"  # Default status
            print(f"⏳ Payment pending - Setting status to: draft")
        
        # -----------------------------
        # ✅ Build cart (accept both old + new keys)
        # -----------------------------
        raw_cart = _pick(sd, "cartItems", "cart_items", "cart", default=[]) or []
        cart_items = []

        for item in raw_cart:
            # support both key styles
            item_id = _pick(item, "item_id", "itemId", default="")
            unit_price = int(_pick(item, "unit_price", "unitPrice", default=0) or 0)
            quantity = int(_pick(item, "quantity", default=1) or 1)
            total_price = int(_pick(item, "total_price", "totalPrice", default=(unit_price * quantity)) or 0)

            # name building (optional enrichment)
            base_name = _pick(item, "name", default=None)
            if not base_name:
                base_name = _get_service_name(item_id)

            # If old payload contains details, enrich the name
            details = item.get("details", {}) or {}
            if isinstance(details, dict):
                if details.get("languages"):
                    base_name += f" ({', '.join(details.get('languages', []))})"
                elif details.get("photoCount"):
                    base_name += f" ({int(details.get('photoCount', 0))} photos)"
                elif details.get("souvenirs"):
                    souvenir_names = [s.get("name", "Item") for s in (details.get("souvenirs") or []) if isinstance(s, dict)]
                    if souvenir_names:
                        base_name += f" ({', '.join(souvenir_names)})"

            cart_items.append(
                {
                    "item_id": item_id,
                    "name": base_name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_price": total_price,
                }
            )

        # fallback: if no cart provided, create single item from type_of_service
        if not cart_items:
            tos = _pick(sd, "typeOfService", "type_of_service", default="")
            cart_total_guess = int(_pick(sd, "price", "cart_total", "cartTotal", default=0) or 0)
            service_name = _pick(sd, "serviceName", "service_name", default="") or ""
            cart_items = [{
                "item_id": tos,
                "name": _get_service_name(tos),
                "details": service_name,
                # **({"other_specify": other_specify} if other_specify else {}),  # ✅ ONLY include if custom service

                "quantity": 1,
                "unit_price": cart_total_guess,
                "total_price": cart_total_guess,
            }]

        service_types = _get_selected_service_types(cart_items)

        # -----------------------------
        # ✅ Pricing (prefer explicit pricing object if present)
        # -----------------------------
        pricing_in = _pick(sd, "pricing", default={}) or {}

        # ✅ Get cart_total as int first
        cart_total = int(_pick(pricing_in, "cart_total", "cartTotal", default=None) or
                  _pick(sd, "cart_total", "cartTotal", "price", default=0) or 0)

        # ✅ Convert float calculations to int immediately
        convenience_fee = int(cart_total * 0.05)  # ← Direct calculation, then convert to int
        tax_amount = int(cart_total * 0.18)       # ← Direct calculation, then convert to int

        coupon_discount = int(_pick(pricing_in, "coupon_discount", "couponDiscount", default=0) or 0)
        discount_amount = int(_pick(pricing_in, "discount_amount", "discountAmount", default=0) or 0)

        coupon_code = _pick(pricing_in, "coupon_code", "couponCode", default=None)

        # ✅ Calculate total_payable as int
        total_payable = int(max(0, cart_total + convenience_fee + tax_amount - coupon_discount - discount_amount))

        # -----------------------------
        # ✅ Guide details / traveler
        # -----------------------------
        guide_details_in = _pick(sd, "guide_details", "guideDetails", default={}) or {}

        # Get selected language preferences from frontend
        language_preference = _pick(sd, "language_preference", "languagePreference", default=[]) or []
        
        # ✅ Calculate guide_count from language preferences (like Flutter)
        # If user selected 3 languages, guide_count = 3
        guide_count = len(language_preference) if language_preference else 1

        # is_foreign_national comes from sd or guide_details or travelerFrom
        is_foreign = _to_bool(
            _pick(guide_details_in, "is_foreign_national", "isForeignNational", default=None)
            or _pick(sd, "isForeignNational", "is_foreign_national", default=None)
        )

        # also support travelerFrom logic if used
        traveler_from = _pick(sd, "travelerFrom", "from_location", "fromLocation", default="")
        if traveler_from and isinstance(traveler_from, str):
            # only override if is_foreign wasn't explicitly set
            if _pick(guide_details_in, "is_foreign_national", "isForeignNational", default=None) is None and \
               _pick(sd, "isForeignNational", "is_foreign_national", default=None) is None:
                is_foreign = traveler_from.strip().lower() != "india"

        number_of_travelers = int(_pick(sd, "number_of_travelers", "numberOfTravelers", default=1) or 1)

        # -----------------------------
        # ✅ time_slot
        # -----------------------------
        time_slot_in = _pick(sd, "time_slot", "timeSlot", default={}) or {}
        time_slot = {
            "label": _pick(time_slot_in, "label", default="Custom") or "Custom",
            "start_time": _pick(time_slot_in, "start_time", "startTime", default="") or "",
            "end_time": _pick(time_slot_in, "end_time", "endTime", default="") or "",
        }

        # -----------------------------
        # ✅ Billing info
        # -----------------------------
        billing_in = _pick(sd, "billing_info", "billingInfo", default={}) or {}
        billing_info = {
            "billing_address": _pick(billing_in, "billing_address", "billingAddress", default="") or "",
            "company_name": _pick(billing_in, "company_name", "companyName", default="") or "",
            "contact_email": _pick(billing_in, "contact_email", "contactEmail", default="") or "",
            "contact_person": _pick(billing_in, "contact_person", "contactPerson", default="") or "",
            "gst_number": _pick(billing_in, "gst_number", "gstNumber", default="") or "",
            "is_corporate_booking": _to_bool(_pick(billing_in, "is_corporate_booking", "isCorporateBooking", default=False)),
        }

        # ✅ Get monument ID and fetch its TITLE
        monument_id = _pick(sd, "monument_to_visit", "monumentToVisit", default="") or ""
        monument_title = _get_monument_title(monument_id) if monument_id else ""

        # -----------------------------
        # ✅ Build final MASTER schema (right-side)
        # -----------------------------
        service_request_data = {
            "serviceId": "",  # will be set after Firestore add()

            # identity / linkage
            "user_id": user_id,
            "chat_id": chat_id,
            "magic_word_user_id": magic_word_user_id,
            "magic_word": magic_word,

            # core
            "status": sr_status,
            # "order_status": _pick(sd, "order_status", "orderStatus", default="pending") or "pending",

            # traveler
            "traveler_name": _pick(sd, "traveler_name", "travelerName", default="") or "",
            "traveler_phone_number": _pick(sd, "traveler_phone_number", "travelerPhoneNumber", default="") or "",
            "from_location": traveler_from or "",

            # trip
            "date_of_travel": _pick(sd, "date_of_travel", "dateOfTravel", default="") or "",
            "time_slot": time_slot,
            "start_otp": _pick(sd, "startOtp", "start_otp", default="") or "",
            "end_otp": _pick(sd, "endOtp", "end_otp", default="") or "",
            "number_of_travelers": number_of_travelers,
            "language_preference": language_preference,  # ✅ STORE LANGUAGES HERE
            "monument_to_visit": monument_title,

            # cart
            "cart": cart_items,
            "service_types": service_types,

            # guide_details (ONLY guide_count + gender_preference)
            "guide_details": {
                "gender_preference": _pick(guide_details_in, "gender_preference", "genderPreference", default="Any") or "Any",
                "guide_count": guide_count,  # ✅ AUTO-CALCULATED FROM LANGUAGES
                
            },


            # pricing
            "pricing": {
                "cart_total": cart_total,
                "convenience_fee": convenience_fee,
                "coupon_code": coupon_code,
                "coupon_discount": coupon_discount,
                "discount_amount": discount_amount,
                "tax_amount": tax_amount,
                "total_payable": total_payable,
            },

            # payments
            "payment_method": _pick(sd, "payment_method", "paymentMethod", default="") or "",
            "payment_status": _pick(sd, "payment_status", "paymentStatus", default="pending") or "pending",
            "payment_timestamp": _pick(sd, "payment_timestamp", "paymentTimestamp", default=None),
            "razorpayOrderId": _pick(sd, "razorpayOrderId", default=None),
            "transaction_id": _pick(sd, "transaction_id", "transactionId", default=None),

            # billing
            "billing_info": billing_info,

            # misc
            "additional_notes": _pick(sd, "additional_notes", "additionalNotes", "description", default=None),
            "feedback": _pick(sd, "feedback", default=None),
            "rating": int(_pick(sd, "rating", default=0) or 0),
            "is_foreign_national": is_foreign,
            # timestamps
            "created_at": _get_iso_timestamp(),
            "updated_at": _get_iso_timestamp(),
            "submitted_at": None,
        }

        # ✅ Save
        service_ref = db.collection("service_requests").add(service_request_data)
        service_request_id = service_ref[1].id

        db.collection("service_requests").document(service_request_id).update({
            "serviceId": service_request_id,
            "updated_at": _get_iso_timestamp(),
        })

        # If you still want to link back:
        db.collection("magicWordUser").document(magic_word_user_id).update({
            "serviceRequestId": service_request_id,
            "updated_at": _get_iso_timestamp(),
        })

        return {
            "success": True,
            "service_request_id": service_request_id,
            "status": sr_status,  # ✅ Return status
            "payment_status": payment_status,
        }

    except Exception as e:
        logging.exception(f"Error creating service request: {e}")
        return {"success": False, "error": str(e)}



def create_service_order(magic_word_user_id: str, service_request_id: str, booking_details: dict) -> dict:
    """
    ✅ Create a service order - Save ONLY fields that exist in serviceOrder collection
    Fetches data from service_requests and booking_details
    """
    if db is None:
        return {"success": False, "error": "Firestore client not initialized"}

    try:
        # ✅ Fetch the service request data
        service_doc = db.collection("service_requests").document(service_request_id).get()
        if not service_doc.exists:
            return {"success": False, "error": f"Service request {service_request_id} not found"}

        service_data = service_doc.to_dict() or {}
        
        # Extract pricing details
        pricing = service_data.get("pricing", {})
        
        # ✅ Build order document - ONLY WITH FIELDS FROM serviceOrder COLLECTION
        order_data = {
            # Core IDs
            "user_id": service_data.get("user_id"),
            "chat_id": service_data.get("chat_id"),
            "magic_word_user_id": magic_word_user_id,
            "service_id": service_request_id,
            "date_of_service": service_data.get("date_of_travel"),
            
            # ✅ Status = "booked"
            "status": "booked",
            
            # ✅ OTP Fields (from booking_details)
            "start_otp": booking_details.get("startOtp", "") if booking_details else "",
            "end_otp": booking_details.get("endOtp", "") if booking_details else "",
            "start_otp_verified": False,
            "end_otp_verified": False,
            
            # ✅ Item/Service Info (from service_requests)
            "item_id": service_data.get("service_types", [""])[0] if service_data.get("service_types") else "",
            "monument_id": service_data.get("monument_to_visit", ""),
            "product_type": "guide",
            
            # ✅ Pricing (from service_requests)
            "price": int(pricing.get("total_payable", 0)),
            "commission_amount": float(booking_details.get("commission", 0)) if booking_details else 0.0,
            "commission_percent": 5,
            
            # ✅ Payment (from booking_details)
            "payment_status": booking_details.get("paymentStatus", "pending") if booking_details else "pending",
            "payment_detail": booking_details.get("paymentDetail", "") if booking_details else "",
            
            # ✅ Vendor (from booking_details)
            "vendor_id": booking_details.get("vendor_id") if booking_details else None,
            "vendor_price": float(booking_details.get("vendor_price", 0)) if booking_details else 0.0,
            
            # ✅ Timestamps
            "created_at": _get_iso_timestamp(),
            "updated_at": _get_iso_timestamp(),
        }

        # ✅ Save to serviceOrder collection
        order_ref = db.collection("serviceOrder").add(order_data)
        order_id = order_ref[1].id

        # ✅ Update document with order_id
        db.collection("serviceOrder").document(order_id).update({
            "order_id": order_id,
            "uid": order_id,
            "updated_at": _get_iso_timestamp(),
        })

        # ✅ Update magicWordUser with order_id
        db.collection("magicWordUser").document(magic_word_user_id).update({
            "order_id": order_id,
            "service_order_id": order_id,
            "order_status": "booked",
            "updated_at": _get_iso_timestamp()
        })

        # ✅ Update service_request status
        db.collection("service_requests").document(service_request_id).update({
            "order_id": order_id,
            "updated_at": _get_iso_timestamp(),
        })

        logging.info(f"✅ Service order created: {order_id}")
        logging.info(f"✅ Status: booked, Price: ₹{order_data['price']}, Payment: {order_data['payment_status']}")
        print(f"🎫 SERVICE ORDER CREATED")
        print(f"   Order ID: {order_id}")
        print(f"   Status: booked")
        print(f"   Price: ₹{order_data['price']}")
        print(f"   Start OTP: {order_data['start_otp']}")
        print(f"   Payment Status: {order_data['payment_status']}")

        return {
            "success": True,
            "service_order_id": order_id,
            "status": "booked",
            "price": order_data['price'],
        }

    except Exception as e:
        logging.exception(f"Error creating service order: {e}")
        return {"success": False, "error": str(e)}


def _get_iso_timestamp() -> str:
    """Get current timestamp in ISO format"""
    from datetime import datetime
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


