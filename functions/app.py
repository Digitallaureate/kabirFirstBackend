from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import logging
import os
from functools import wraps
from datetime import datetime
from uuid import uuid4
from urllib.parse import quote

# ✅ Import from your package modules
from customerService.user_summary import get_user_summary_by_phone
from customerService.magic_word_summary import (
    get_magicword_requests,
    get_magicword_detail,
    get_user_magicword_requests,
    get_user_completed_orders,
    get_user_payment_history,
)
from google.cloud import firestore as gfirestore

from firebase_setup import get_project_b_firestore, get_project_b_storage_bucket


app = Flask(
    __name__,
    template_folder="customerService/templates"
)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-to-a-long-random-secret")

# ✅ Handle both /support (Hosting rewrite) and /customerService_app (direct Cloud Function URL)
# This ensures Flask sees correct paths and generates correct URLs in both environments.
class MultiSubPathMiddleware:
    def __init__(self, app, prefixes=("/support", "/customerService_app")):
        self.app = app
        self.prefixes = prefixes

    def __call__(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "") or ""

        for prefix in self.prefixes:
            if path_info == prefix or path_info.startswith(prefix + "/"):
                environ["PATH_INFO"] = path_info[len(prefix):] or "/"
                environ["SCRIPT_NAME"] = prefix
                break

        return self.app(environ, start_response)

app.wsgi_app = MultiSubPathMiddleware(app.wsgi_app)


# ---------------------------
# ✅ AUTH HELPERS
# ---------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if request.path.startswith("/api") or request.is_json:
                return jsonify({"success": False, "error": "Unauthorized. Please login."}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def verify_admin_from_firestore(username: str, password: str):
    db = get_project_b_firestore()
    if db is None:
        return {"ok": False, "error": "Firestore client not initialized"}

    try:
        from google.cloud.firestore import FieldFilter

        q = (
            db.collection("vendor_credential")
            .where(filter=FieldFilter("userName", "==", username))
            .limit(1)
            .stream()
        )

        doc = next(q, None)
        if not doc:
            return {"ok": False, "error": "Invalid username or password"}

        data = doc.to_dict() or {}

        if data.get("isActive") is not True:
            return {"ok": False, "error": "Account is inactive"}

        if (data.get("password") or "") != password:
            return {"ok": False, "error": "Invalid username or password"}

        return {"ok": True, "user": {"id": doc.id, "userName": data.get("userName")}}

    except Exception as e:
        logging.exception("Error verifying admin login")
        return {"ok": False, "error": str(e)}


# ---------------------------
# ✅ LOGIN + DASHBOARD ROUTES
# ---------------------------
@app.route("/", methods=["GET"])
def home():
    if session.get("admin_logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("admin_logged_in"):
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    # ✅ Robust JSON detection (works behind Cloud Functions too)
    content_type = (request.headers.get("Content-Type") or "").lower()
    wants_json = (
        "application/json" in content_type
        or (request.headers.get("Accept") or "").lower().find("application/json") != -1
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )

    # ✅ Try to parse JSON even if request.is_json is unreliable
    body = request.get_json(silent=True) or {}

    if wants_json and body:
        username = (body.get("username") or "").strip()
        password = (body.get("password") or "").strip()
    else:
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

    if not username or not password:
        if wants_json:
            return jsonify({"success": False, "error": "Username and password are required"}), 400
        return render_template("index.html", error="Username and password are required")

    result = verify_admin_from_firestore(username, password)

    if not result.get("ok"):
        err = result.get("error", "Login failed")
        if wants_json:
            return jsonify({"success": False, "error": err}), 401
        return render_template("index.html", error=err)

    session["admin_logged_in"] = True
    session["admin_user"] = result.get("user")

    # ✅ Always return JSON for fetch/XHR
    if wants_json:
        return jsonify({"success": True, "message": "Login successful"}), 200

    return redirect(url_for("dashboard"))



@app.route("/logout", methods=["GET"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    return render_template("dashboard.html")


# ---------------------------
# ✅ EXISTING ROUTES
# ---------------------------
@app.route("/user-summary", methods=["GET", "POST"])
@login_required
def user_summary():
    summary = None
    error = None
    identifier = ""

    if request.method == "POST":
        if request.is_json:
            data = request.get_json()
            identifier = data.get("identifier", "").strip()

            if not identifier:
                return jsonify({"error": "Please enter phone number or email."}), 400

            try:
                summary_result = get_user_summary_by_phone(identifier)
                if not summary_result.get("found"):
                    error_msg = summary_result.get("message") or summary_result.get("error") or "User not found."
                    return jsonify({"error": error_msg}), 404

                return jsonify({"summary": summary_result}), 200
            except Exception as e:
                logging.exception("Error while fetching user summary")
                return jsonify({"error": f"Error while fetching data: {e}"}), 500

        identifier = request.form.get("identifier", "").strip()

        if not identifier:
            error = "Please enter phone number or email."
        else:
            try:
                summary = get_user_summary_by_phone(identifier)
                if not summary.get("found"):
                    error = summary.get("message") or summary.get("error") or "User not found."
                    summary = None
            except Exception as e:
                logging.exception("Error while fetching user summary")
                error = f"Error while fetching data: {e}"

    return render_template(
        "user_summary.html",
        identifier=identifier,
        summary=summary,
        error=error
    )


@app.route("/api/magic-words", methods=["GET"])
@login_required
def api_magic_words():
    try:
        limit = int(request.args.get("limit", "1000"))
        user_id = request.args.get("userId")

        if user_id:
            db = get_project_b_firestore()
            if db is None:
                return jsonify({"found": False, "error": "Firestore client not initialized"}), 500

            from customerService.user_summary import _ts_to_iso, _iso_to_readable
            from google.cloud.firestore import FieldFilter

            col = db.collection("magicWordUser")
            q = (
                col.where(filter=FieldFilter("userId", "==", user_id))
                .where(filter=FieldFilter("status", "in", ["requested", "inProgress"]))
                .limit(limit * 2)
                .stream()
            )

            items = []
            for doc in q:
                d = doc.to_dict() or {}
                d["id"] = doc.id

                if "matchedAt" in d:
                    iso = _ts_to_iso(d["matchedAt"])
                    d["matchedAt"] = iso
                    d["matchedAt_readable"] = _iso_to_readable(iso)
                else:
                    d["matchedAt"] = "1970-01-01T00:00:00.000Z"

                items.append(d)

            items.sort(key=lambda x: x.get("matchedAt", ""), reverse=True)
            items = items[:limit]

            return jsonify({"found": True, "count": len(items), "items": items})
        else:
            result = get_magicword_requests(limit=limit)
            return jsonify(result)

    except Exception as e:
        logging.exception("Error fetching magic word requests")
        return jsonify({"found": False, "error": str(e)}), 500


@app.route("/api/magic-words/user/<user_id>", methods=["GET"])
@login_required
def api_user_magic_words(user_id):
    try:
        if not user_id:
            return jsonify({"found": False, "error": "User ID is required"}), 400

        result = get_user_magicword_requests(user_id)
        status_code = 200 if result.get("found") else 500
        return jsonify(result), status_code

    except Exception as e:
        logging.exception("Error fetching user magic word requests")
        return jsonify({"found": False, "error": str(e)}), 500


@app.route("/api/magic-words/user/<user_id>/orders", methods=["GET"])
@login_required
def api_user_completed_orders(user_id):
    try:
        if not user_id:
            return jsonify({"found": False, "error": "User ID is required"}), 400

        result = get_user_completed_orders(user_id)
        status_code = 200 if result.get("found") else 500
        return jsonify(result), status_code

    except Exception as e:
        logging.exception("Error fetching user orders")
        return jsonify({"found": False, "error": str(e)}), 500


@app.route("/api/magic-words/user/<user_id>/payments", methods=["GET"])
@login_required
def api_user_payment_history(user_id):
    try:
        if not user_id:
            return jsonify({"found": False, "error": "User ID is required"}), 400

        result = get_user_payment_history(user_id)
        status_code = 200 if result.get("found") else 500
        return jsonify(result), status_code

    except Exception as e:
        logging.exception("Error fetching payment history")
        return jsonify({"found": False, "error": str(e)}), 500


@app.route("/api/magic-words/<magic_word_user_id>", methods=["GET"])
@login_required
def api_magic_word_detail(magic_word_user_id):
    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable

        result = get_magicword_detail(magic_word_user_id)

        if result.get("found"):
            chat_id = result.get("chat", {}).get("id")
            if chat_id:
                try:
                    db = get_project_b_firestore()
                    messages = (
                        db.collection("chats")
                        .document(chat_id)
                        .collection("messages")
                        .order_by("created_at", direction=gfirestore.Query.DESCENDING)
                        .limit(10)
                        .get()
                    )

                    chat_history = []
                    for msg_doc in reversed(messages):
                        msg_data = msg_doc.to_dict() or {}
                        if "created_at" in msg_data:
                            iso = _ts_to_iso(msg_data["created_at"])
                            msg_data["created_at"] = iso
                            msg_data["created_at_readable"] = _iso_to_readable(iso)
                        chat_history.append(msg_data)

                    result["chat_history"] = chat_history
                except Exception as e:
                    logging.warning(f"Error fetching chat history: {e}")
                    result["chat_history"] = []

        status_code = 200 if result.get("found") else 404
        return jsonify(result), status_code

    except Exception as e:
        logging.exception("Error fetching magic word detail")
        return jsonify({"found": False, "error": str(e)}), 500


# ---------------------------
# ✅ UPDATED: SEND MESSAGE (supports image_url)
# ---------------------------
@app.route("/api/magic-words/<magic_word_user_id>/send-message", methods=["POST"])
@login_required
def send_message_to_user(magic_word_user_id):
    """
    Sends message to chats/<chatId>/messages
    - text -> content
    - image url -> image_url (only)
    """
    try:
        request_body = request.get_json() or {}
        message_type = request_body.get("messageType")
        message_content = (request_body.get("message") or "").strip()
        image_url = (request_body.get("imageUrl") or request_body.get("image_url") or "").strip()
        chat_id = (request_body.get("chatId") or "").strip()

        if not chat_id:
            return jsonify({"success": False, "error": "Chat ID is required"}), 400

        # ✅ allow: text only, image only, or both
        if not message_content and not image_url:
            return jsonify({"success": False, "error": "Message text or image is required"}), 400

        if not message_type:
            message_type = "custom"

        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        chat_doc = db.collection("chats").document(chat_id).get()
        if not chat_doc.exists:
            return jsonify({"success": False, "error": "Chat not found"}), 404

        chat_location = (chat_doc.to_dict() or {}).get("location")

        message_data = {
            "role": "assistant",
            "content": message_content,  # ✅ text only
            "image_url": image_url or None,
            "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "location": chat_location,
            "user_id": "CustomerService"  # ✅ Identify sender so listener skips processing
        }

        # remove None keys (clean Firestore doc)
        message_data = {k: v for k, v in message_data.items() if v is not None}

        db.collection("chats").document(chat_id).collection("messages").add(message_data)

        return jsonify({
            "success": True,
            "message": "Message sent successfully",
            "messageType": message_type,
            "chatId": chat_id,
            "saved": message_data
        }), 200

    except Exception as e:
        logging.exception("Error in send_message_to_user endpoint")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chats/<chat_id>/toggle-interaction", methods=["PUT"])
@login_required
def toggle_interaction(chat_id):
    try:
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        if not chat_id:
            return jsonify({"success": False, "error": "Chat ID is required"}), 400

        data = request.get_json() or {}
        is_human = data.get("isHumanInteraction", False)

        doc_ref = db.collection("chats").document(chat_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({"success": False, "error": "Chat not found"}), 404

        doc_ref.update({"isHumanInteraction": is_human})

        return jsonify({"success": True, "chatId": chat_id, "isHumanInteraction": is_human}), 200

    except Exception as e:
        logging.exception("Error toggling interaction mode")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------
# ✅ GET CHAT MESSAGES (POLLING)
# ---------------------------
@app.route("/api/chats/<chat_id>/messages", methods=["GET"])
@login_required
def api_chat_messages(chat_id):
    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable
        
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        messages_ref = (
            db.collection("chats")
            .document(chat_id)
            .collection("messages")
            .order_by("created_at", direction=gfirestore.Query.DESCENDING)
            .limit(50)
        )
        
        docs = messages_ref.stream()
        messages = []
        for doc in docs:
            d = doc.to_dict() or {}
            d["id"] = doc.id
            
            if "created_at" in d:
                iso = _ts_to_iso(d["created_at"])
                d["created_at"] = iso
                d["created_at_readable"] = _iso_to_readable(iso)
            
            messages.append(d)
        
        # Reverse to show oldest first (chronological order for chat UI)
        messages.reverse()

        return jsonify({"success": True, "messages": messages}), 200

    except Exception as e:
        logging.exception("Error fetching chat messages")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------
# ✅ UPDATE STATUS / CREATE SERVICE REQUEST
# ---------------------------
@app.route("/api/magic-words/<magic_word_id>/status", methods=["PUT"])
@login_required
def update_magic_word_status(magic_word_id):
    """Update magic word request status and user details"""
    magic_word_user_id = magic_word_id
    try:
        from customerService.magic_word_summary import (
            create_service_request, 
            send_service_request_message,
            create_service_order,
            send_booking_confirmation_message
        )
        from datetime import datetime
        
        db = get_project_b_firestore()
        
        # Get current status
        magic_doc = db.collection("magicWordUser").document(magic_word_user_id).get()
        if not magic_doc.exists:
            return jsonify({"success": False, "error": "Magic word not found"}), 404
        
        current_data = magic_doc.to_dict()
        current_status = current_data.get("status", "requested")
        chat_id = current_data.get("chatId")
        user_id = current_data.get("userId")
        magic_word = current_data.get("magicWord")
        service_request_id = current_data.get("serviceRequestId")
        
        # Determine next status
        request_body = request.get_json() or {}
        explicit_status = request_body.get("status")

        if explicit_status:
             new_status = explicit_status
        elif current_status == "requested":
            new_status = "inProgress"
        elif current_status == "inProgress":
            # If we are just updating details (booking_details present), stay in inProgress
            # Otherwise (no details, just button click), move to completed
            if request_body.get("details"):
                 new_status = "inProgress"
            else:
                 new_status = "completed"
        else:
            return jsonify({"success": False, "error": "Status cannot be changed"}), 400
        
        # Get booking details from request body (already fetched above for explicit_status check, but keeping structure)
        booking_details = request_body.get("details", {})
        
        # ✅ Get payment status from booking details
        payment_status = booking_details.get("paymentStatus", "pending")
        
        # ✅ Get user details if provided
        if booking_details.get("userId") and booking_details.get("userUpdate"):
            user_update = booking_details.get("userUpdate")
            db.collection("users").document(booking_details.get("userId")).update({
                "firstName": user_update.get("firstName", ""),
                "lastName": user_update.get("lastName", ""),
                "phoneNumber": user_update.get("phoneNumber", ""),
                "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
            })
            logging.info(f"✅ User {booking_details.get('userId')} updated")
            print(f"👤 USER UPDATE: Phone={user_update.get('phoneNumber')}, Name={user_update.get('firstName')} {user_update.get('lastName')}")
        
        # Prepare update data
        update_data = {
            "status": new_status,
            "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        }

        # ✅ Save completion reason if provided
        if new_status == "completed":
            reason = request_body.get("reason") or booking_details.get("completionReason")
            if reason:
                update_data["completionReason"] = reason

        # Update status in Firestore
        db.collection("magicWordUser").document(magic_word_user_id).update(update_data)
        
        logging.info(f"✅ Magic word {magic_word_user_id} status changed: {current_status} → {new_status}")
        
        # ✅ NEW: Disable human interaction if completed
        if new_status == "completed" and chat_id:
             try:
                 db.collection("chats").document(chat_id).update({"isHumanInteraction": False})
                 print(f"🤖 Automation Restored: isHumanInteraction set to False for chat {chat_id}")
             except Exception as e:
                 logging.error(f"❌ Failed to disable human interaction for chat {chat_id}: {e}")
        
        # 📝 Create service request when status changes to inProgress
        if new_status == "inProgress":
            # ✅ ONLY create service request/send message if we have actual details
            # (Avoids sending message when just viewing/auto-updating status)
            if booking_details:
                print(f"📝 Creating service request with details...")
                print(f"💳 Payment Status: {payment_status}")
                
                sr_result = create_service_request(magic_word_user_id, current_data, booking_details)
                print(f"📝 Service request result: {sr_result}")
                
                if sr_result.get("success"):
                    service_request_id = sr_result.get("service_request_id")
                    
                    # ✅ Check if payment is successful
                    if payment_status == "success":
                        print(f"✅ PAYMENT SUCCESS - Creating service order...")
                        
                        # 🎫 Create booking order immediately
                        order_result = create_service_order(
                            magic_word_user_id, 
                            service_request_id,
                            booking_details
                        )
                        print(f"🎫 Order result: {order_result}")
                        
                        if order_result.get("success"):
                            # ✅ Update magic word status to reflect payment success
                            db.collection("magicWordUser").document(magic_word_user_id).update({
                                "paymentStatus": "success",
                                "orderStatus": "booked",
                                "serviceOrderId": order_result.get("service_order_id"),
                                "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
                            })
                            
                            # Send confirmation message
                            # msg_result = send_booking_confirmation_message(chat_id, booking_details)
                            # print(f"📨 Confirmation message sent: {msg_result}")
                            print("📨 Skipping confirmation message as per user request")
                        else:
                            logging.warning(f"⚠️ Booking order creation failed: {order_result.get('error')}")
                    else:
                        print(f"⏳ Payment pending/failed - Order not created yet")
                        # Send service request confirmation (not booking confirmation)
                        # msg_result = send_service_request_message(chat_id, magic_word, booking_details)
                        # print(f"📨 Service request message sent: {msg_result}")
                        print("📨 Skipping service request message as per user request")
                else:
                    logging.warning(f"⚠️ Service request creation failed: {sr_result.get('error')}")
            else:
                print(f"👀 Status updated to inProgress (View Mode) - Skipping service request creation/message")
        
        # 🎫 Create booking order when status changes to completed (if not already created via payment)
        if new_status == "completed" and service_request_id:
            print(f"🎫 Creating booking order from completed status...")
            order_result = create_service_order(
                magic_word_user_id, 
                service_request_id,
                booking_details
            )
            print(f"🎫 Order result: {order_result}")
            
            if order_result.get("success"):
                # msg_result = send_booking_confirmation_message(chat_id, booking_details)
                # print(f"📨 Confirmation message sent: {msg_result}")
                print("📨 Skipping completion message as per user request")
            else:
                logging.warning(f"⚠️ Booking order creation failed: {order_result.get('error')}")
        
        return jsonify({
            "success": True,
            "new_status": new_status,
            "payment_status": payment_status,
            "message": f"Status updated to {new_status} with payment status: {payment_status}"
        })
        
    except Exception as e:
        logging.exception("Error updating magic word status")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------
# ✅ MONUMENTS & SERVICES
# ---------------------------
@app.route("/api/monuments", methods=["GET"])
@login_required
def api_monuments():
    try:
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        docs = db.collection("serviceMonument").stream()
        items = []
        for doc in docs:
            d = doc.to_dict() or {}
            d["id"] = doc.id
            items.append(d)

        return jsonify({"success": True, "monuments": items}), 200
    except Exception as e:
        logging.exception("Error fetching monuments")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/service-languages", methods=["GET"])
@login_required
def api_service_languages():
    try:
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        # Assuming 'serviceLanguage' is the collection name
        docs = db.collection("serviceLanguage").stream()
        items = []
        for doc in docs:
            d = doc.to_dict() or {}
            d["id"] = doc.id
            items.append(d)
        
        return jsonify({"success": True, "languages": items}), 200
    except Exception as e:
        logging.exception("Error fetching languages")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/monuments/<monument_id>/services", methods=["GET"])
@login_required
def get_services_by_monument(monument_id):
    """Get services available for a specific monument - ONLY isAvailable=true"""
    try:
        db = get_project_b_firestore()
        
        print(f"🏛️ Fetching services for monument: {monument_id}")
        
        # Get the monument document
        monument_doc = db.collection("serviceMonument").document(monument_id).get()
        if not monument_doc.exists:
            print(f"⚠️ Monument {monument_id} not found")
            return jsonify({
                "success": False,
                "services": [],
                "error": f"Monument not found"
            }), 404
        
        monument_data = monument_doc.to_dict() or {}
        print(f"🏛️ Monument data keys:", list(monument_data.keys()))
        
        # ✅ Get serviceAvilable array from monument document
        service_available = monument_data.get("serviceAvilable", [])
        
        if not service_available:
            print(f"⚠️ No serviceAvilable array found in monument")
            return jsonify({
                "success": True,
                "services": [],
                "message": "No services available for this monument"
            })
        
        print(f"📦 Total services in serviceAvilable: {len(service_available)}")
        
        # ✅ Debug: Print all services and their isAvailable status
        for idx, service in enumerate(service_available):
            is_avail = service.get("isAvilable")
            print(f"   Service {idx}: title={service.get('title')}, isAvailable={is_avail}, type={type(is_avail)}, serviceId={service.get('id')} ")
        
        # ✅ Filter ONLY services where isAvailable is true
        available_services = []
        for service in service_available:
            is_available = service.get("isAvilable", False)
            # Only include if isAvailable is boolean True
            if is_available is True:
                available_services.append(service)
                print(f"   ✅ Including: {service.get('title')}")
            else:
                print(f"   ❌ Skipping: {service.get('title')} (isAvailable={is_available})")
        
        print(f"✅ Found {len(available_services)} AVAILABLE services out of {len(service_available)} total")
        
        if not available_services:
            print(f"⚠️ NO services have isAvailable=true")
            return jsonify({
                "success": True,
                "services": [],
                "message": "No available services for this monument"
            })
        
        # ✅ Format services for dropdown - ONLY available ones
        formatted_services = [
            {
                "id": service.get("id", ""),
                "title": service.get("title", ""),
                "name": service.get("name", ""),
                "description": service.get("description", ""),
                "isAvilable": True  # ✅ Confirmed these are all true
            }
            for service in available_services
        ]
        
        print(f"✅ Returning {len(formatted_services)} formatted services:")
        for svc in formatted_services:
            print(f"   - {svc['title']}")
        
        return jsonify({
            "success": True,
            "services": formatted_services
        })
        
    except Exception as e:
        logging.exception(f"Error fetching services for monument {monument_id}")
        print(f"❌ Error: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "services": []
        }), 500


# ---------------------------
# ✅ UPLOAD IMAGE (NO login_required)
# ---------------------------
@app.route("/api/upload-customer-service-image", methods=["POST"])
def upload_customer_service_image():
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"success": False, "error": "Empty filename"}), 400

        chat_id = (request.form.get("chatId") or "unknown").strip()

        ext = (file.filename.rsplit(".", 1)[-1] or "jpg").lower()
        if ext not in ["jpg", "jpeg", "png", "webp"]:
            return jsonify({"success": False, "error": "Only jpg/jpeg/png/webp allowed"}), 400

        filename = f"{uuid4().hex}.{ext}"
        storage_path = f"customer_service/{filename}"

        bucket = get_project_b_storage_bucket()
        blob = bucket.blob(storage_path)

        token = str(uuid4())
        blob.metadata = {"firebaseStorageDownloadTokens": token}

        blob.upload_from_file(file, content_type=file.mimetype or "image/jpeg")

        encoded_path = quote(storage_path, safe="")
        image_url = (
            f"https://firebasestorage.googleapis.com/v0/b/"
            f"{bucket.name}/o/{encoded_path}?alt=media&token={token}"
        )

        return jsonify({
            "success": True,
            "imageUrl": image_url,
            "storagePath": storage_path,
        }), 200

    except Exception as e:
        logging.exception("Upload failed")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
