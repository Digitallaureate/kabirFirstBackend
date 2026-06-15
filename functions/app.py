from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import logging
import os
import json
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

        # Firebase Functions emulator prefixes the function path with
        # /<project>/<region>/, so normalize that to /customerService_app first.
        if "/customerService_app" in path_info and not path_info.startswith("/customerService_app"):
            emulator_prefix, _, remainder = path_info.partition("/customerService_app")
            environ["PATH_INFO"] = remainder or "/"
            environ["SCRIPT_NAME"] = f"{environ.get('SCRIPT_NAME', '')}{emulator_prefix}/customerService_app"
            return self.app(environ, start_response)

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
def prefixed_url_for(endpoint, **values):
    target = url_for(endpoint, **values)
    script_root = (request.script_root or "").rstrip("/")
    if script_root and target.startswith("/") and not target.startswith(script_root + "/"):
        return f"{script_root}{target}"
    return target


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if request.path.startswith("/api") or request.is_json:
                return jsonify({"success": False, "error": "Unauthorized. Please login."}), 401
            return redirect(prefixed_url_for("login"))
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
        return redirect(prefixed_url_for("dashboard"))
    return redirect(prefixed_url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("admin_logged_in"):
            return redirect(prefixed_url_for("dashboard"))
        return render_template("index.html")

    # ✅ Robust JSON detection (works behind Cloud Functions too)
    content_type = (request.headers.get("Content-Type") or "").lower()
    wants_json = (
        "application/json" in content_type
        or (request.headers.get("Accept") or "").lower().find("application/json") != -1
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )

    # ✅ Parse request body without depending on request.get_json(), which can
    # behave inconsistently through the local Functions emulator wrapper.
    username = ""
    password = ""

    if "application/json" in content_type:
        raw_body = request.get_data(cache=True, as_text=True) or ""
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            body = {}

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

    return redirect(prefixed_url_for("dashboard"))



@app.route("/logout", methods=["GET"])
@login_required
def logout():
    wants_json = (
        "application/json" in (request.headers.get("Accept") or "").lower()
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    session.clear()
    if wants_json:
        return jsonify({"success": True, "redirect": prefixed_url_for("login")}), 200
    return redirect(prefixed_url_for("login"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/customer-support", methods=["GET"])
@login_required
def customer_support():
    return render_template("customer_support.html")


@app.route("/orders", methods=["GET"])
@login_required
def orders():
    return redirect(prefixed_url_for("customer_support"))


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

        payload, status_code = _create_customer_service_chat_message(
            chat_id=chat_id,
            message_content=message_content,
            image_url=image_url,
            message_type=message_type,
        )
        return jsonify(payload), status_code

    except Exception as e:
        logging.exception("Error in send_message_to_user endpoint")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chats/<chat_id>/send-message", methods=["POST"])
@login_required
def send_message_to_chat(chat_id):
    try:
        request_body = request.get_json() or {}
        message_type = request_body.get("messageType") or "custom"
        message_content = (request_body.get("message") or "").strip()
        image_url = (request_body.get("imageUrl") or request_body.get("image_url") or "").strip()

        if not chat_id:
            return jsonify({"success": False, "error": "Chat ID is required"}), 400

        if not message_content and not image_url:
            return jsonify({"success": False, "error": "Message text or image is required"}), 400

        payload, status_code = _create_customer_service_chat_message(
            chat_id=chat_id,
            message_content=message_content,
            image_url=image_url,
            message_type=message_type,
        )
        return jsonify(payload), status_code

    except Exception as e:
        logging.exception("Error in send_message_to_chat endpoint")
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
            logging.info(
                "User update: phone=%s name=%s %s",
                user_update.get("phoneNumber"),
                user_update.get("firstName"),
                user_update.get("lastName"),
            )
        
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
                 logging.info("Automation restored for chat %s", chat_id)
             except Exception as e:
                 logging.error(f"❌ Failed to disable human interaction for chat {chat_id}: {e}")
        
        # 📝 Create service request when status changes to inProgress
        if new_status == "inProgress":
            # ✅ ONLY create service request/send message if we have actual details
            # (Avoids sending message when just viewing/auto-updating status)
            if booking_details:
                logging.info("Creating service request with details")
                logging.info("Payment status: %s", payment_status)
                
                sr_result = create_service_request(magic_word_user_id, current_data, booking_details)
                logging.info("Service request result: %s", sr_result)
                
                if sr_result.get("success"):
                    service_request_id = sr_result.get("service_request_id")
                    
                    # ✅ Check if payment is successful
                    if payment_status == "success":
                        logging.info("Payment success - creating service order")
                        
                        # 🎫 Create booking order immediately
                        order_result = create_service_order(
                            magic_word_user_id, 
                            service_request_id,
                            booking_details
                        )
                        logging.info("Service order result: %s", order_result)
                        
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
                            logging.info("Skipping confirmation message as requested")
                        else:
                            logging.warning(f"⚠️ Booking order creation failed: {order_result.get('error')}")
                    else:
                        logging.info("Payment pending or failed - order not created yet")
                        # Send service request confirmation (not booking confirmation)
                        # msg_result = send_service_request_message(chat_id, magic_word, booking_details)
                        # print(f"📨 Service request message sent: {msg_result}")
                        logging.info("Skipping service request message as requested")
                else:
                    logging.warning(f"⚠️ Service request creation failed: {sr_result.get('error')}")
            else:
                logging.info("Status updated to inProgress (view mode) - skipping service request creation/message")
        
        # 🎫 Create booking order when status changes to completed (if not already created via payment)
        if new_status == "completed" and service_request_id:
            logging.info("Creating booking order from completed status")
            order_result = create_service_order(
                magic_word_user_id, 
                service_request_id,
                booking_details
            )
            logging.info("Completed-status order result: %s", order_result)
            
            if order_result.get("success"):
                # msg_result = send_booking_confirmation_message(chat_id, booking_details)
                # print(f"📨 Confirmation message sent: {msg_result}")
                logging.info("Skipping completion message as requested")
            else:
                logging.warning(f"⚠️ Booking order creation failed: {order_result.get('error')}")
        
        vendor_id = vendor_user_name
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
        
        logging.info("Fetching services for monument: %s", monument_id)
        
        # Get the monument document
        monument_doc = db.collection("serviceMonument").document(monument_id).get()
        if not monument_doc.exists:
            logging.warning("Monument %s not found", monument_id)
            return jsonify({
                "success": False,
                "services": [],
                "error": f"Monument not found"
            }), 404
        
        monument_data = monument_doc.to_dict() or {}
        logging.info("Monument data keys: %s", list(monument_data.keys()))
        
        # ✅ Get serviceAvilable array from monument document
        service_available = monument_data.get("serviceAvilable", [])
        
        if not service_available:
            logging.warning("No serviceAvilable array found in monument %s", monument_id)
            return jsonify({
                "success": True,
                "services": [],
                "message": "No services available for this monument"
            })
        
        logging.info("Total services in serviceAvilable: %s", len(service_available))
        
        # ✅ Debug: Print all services and their isAvailable status
        for idx, service in enumerate(service_available):
            is_avail = service.get("isAvilable")
            logging.info(
                "Service %s: title=%s isAvailable=%s type=%s serviceId=%s",
                idx,
                service.get("title"),
                is_avail,
                type(is_avail),
                service.get("id"),
            )
        
        # ✅ Filter ONLY services where isAvailable is true
        available_services = []
        for service in service_available:
            is_available = service.get("isAvilable", False)
            # Only include if isAvailable is boolean True
            if is_available is True:
                available_services.append(service)
                logging.info("Including available service: %s", service.get("title"))
            else:
                logging.info(
                    "Skipping unavailable service: %s (isAvailable=%s)",
                    service.get("title"),
                    is_available,
                )
        
        logging.info(
            "Found %s available services out of %s total",
            len(available_services),
            len(service_available),
        )
        
        if not available_services:
            logging.warning("No services have isAvailable=true for monument %s", monument_id)
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
        
        logging.info("Returning %s formatted services", len(formatted_services))
        for svc in formatted_services:
            logging.info("Formatted service: %s", svc["title"])
        
        return jsonify({
            "success": True,
            "services": formatted_services
        })
        
    except Exception as e:
        logging.exception(f"Error fetching services for monument {monument_id}")
        logging.error("Error fetching services for monument %s: %s", monument_id, str(e))
        return jsonify({
            "success": False,
            "error": str(e),
            "services": []
        }), 500


# ---------------------------
# ✅ SERVICE JSON ORDERS (serviceJsonOrder collection)
# ---------------------------
def _service_order_value(value):
    """Normalize Firestore field_values entries that may be scalars or {label, value} maps."""
    if isinstance(value, dict):
        return value.get("label") or value.get("value") or ""
    if isinstance(value, list):
        parts = [_service_order_value(v) for v in value]
        parts = [str(p).strip() for p in parts if str(p).strip()]
        return ", ".join(parts)
    return value if value is not None else ""


def _service_order_number(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _humanize_field_key(key: str) -> str:
    return (key or "").replace("_", " ").strip().title()


def _get_latest_chat_for_user(db, user_id: str, explicit_chat_id: str = "") -> dict:
    if not user_id and not explicit_chat_id:
        return {}

    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable

        chat_doc = None
        if explicit_chat_id:
            explicit_doc = db.collection("chats").document(explicit_chat_id).get()
            if explicit_doc.exists:
                chat_doc = explicit_doc

        if chat_doc is None and user_id:
            latest_chat_docs = (
                db.collection("chats")
                .where("participants", "array_contains", user_id)
                .order_by("updated_at", direction=gfirestore.Query.DESCENDING)
                .limit(1)
                .get()
            )
            if latest_chat_docs:
                chat_doc = latest_chat_docs[0]

        if chat_doc is None:
            return {}

        chat_data = chat_doc.to_dict() or {}
        chat_data["id"] = chat_doc.id
        for ts_field in ("created_at", "updated_at"):
            if ts_field in chat_data:
                iso = _ts_to_iso(chat_data[ts_field])
                chat_data[ts_field] = iso
                chat_data[f"{ts_field}_readable"] = _iso_to_readable(iso)
        return chat_data
    except Exception as chat_err:
        logging.warning("Could not resolve chat for user %s: %s", user_id, chat_err)
        return {}


def _create_customer_service_chat_message(chat_id: str, message_content: str, image_url: str = "", message_type: str = "custom"):
    db = get_project_b_firestore()
    if db is None:
        return {"success": False, "error": "Firestore not initialized"}, 500

    chat_doc = db.collection("chats").document(chat_id).get()
    if not chat_doc.exists:
        return {"success": False, "error": "Chat not found"}, 404

    chat_location = (chat_doc.to_dict() or {}).get("location")
    message_data = {
        "role": "assistant",
        "content": message_content,
        "image_url": image_url or None,
        "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "location": chat_location,
        "user_id": "CustomerService",
    }
    message_data = {k: v for k, v in message_data.items() if v is not None}

    db.collection("chats").document(chat_id).collection("messages").add(message_data)
    return {
        "success": True,
        "message": "Message sent successfully",
        "messageType": message_type,
        "chatId": chat_id,
        "saved": message_data,
    }, 200


def _normalize_service_json_order(order: dict) -> dict:
    field_values = order.get("field_values") or {}
    payment_details = order.get("payment_details") or {}
    price_summary = order.get("price_summary") or {}

    traveler_name = (
        _service_order_value(field_values.get("full_name"))
        or order.get("traveler_name")
        or order.get("customer_name")
        or ""
    )
    traveler_phone = (
        _service_order_value(field_values.get("phone_number"))
        or _service_order_value(field_values.get("mobile_number"))
        or order.get("traveler_phone_number")
        or ""
    )
    monument_name = (
        _service_order_value(field_values.get("monument_id"))
        or order.get("monument_to_visit")
        or order.get("monument_id")
        or ""
    )
    languages = (
        _service_order_value(field_values.get("language_preference"))
        or order.get("language_preference")
        or ""
    )
    time_slot = (
        _service_order_value(field_values.get("time_slot"))
        or order.get("time_slot")
        or ""
    )
    travel_date = (
        _service_order_value(field_values.get("travel_date"))
        or _service_order_value(field_values.get("start_date"))
        or order.get("date_of_service")
        or ""
    )
    traveler_count = (
        _service_order_value(field_values.get("number_of_travelers"))
        or order.get("number_of_travelers")
        or ""
    )
    service_name = order.get("service_name") or order.get("service_id") or order.get("item_id") or ""

    price = (
        _service_order_number(price_summary.get("total"), default=None)
        or _service_order_number(payment_details.get("amount"), default=None)
        or _service_order_number(order.get("price"), default=None)
    )
    vendor_price = _service_order_number(order.get("vendor_price"), default=None)

    payment_status = (
        payment_details.get("payment_status")
        or payment_details.get("status")
        or order.get("payment_status")
        or ""
    )

    payment_summary = []
    if isinstance(price_summary.get("items"), list):
        for item in price_summary.get("items"):
            if not isinstance(item, dict):
                continue
            label = item.get("label") or "Item"
            amount = item.get("amount")
            payment_summary.append({"label": label, "amount": amount})

    dynamic_fields = []
    used_field_keys = {
        "full_name",
        "phone_number",
        "mobile_number",
        "monument_id",
        "language_preference",
        "time_slot",
        "travel_date",
        "start_date",
        "number_of_travelers",
    }
    if isinstance(field_values, dict):
        for key, raw_value in field_values.items():
            if key in used_field_keys:
                continue
            normalized_value = _service_order_value(raw_value)
            if normalized_value in ("", None):
                continue
            dynamic_fields.append({
                "key": key,
                "label": _humanize_field_key(key),
                "value": normalized_value,
            })

    normalized = dict(order)
    normalized.update({
        "traveler_name": traveler_name,
        "traveler_phone_number": traveler_phone,
        "monument_name": monument_name,
        "language_preference": languages,
        "time_slot_display": str(time_slot or ""),
        "date_of_service": travel_date,
        "number_of_travelers": traveler_count,
        "service_name": service_name,
        "service_type": service_name,
        "price": price,
        "vendor_price": vendor_price,
        "payment_status": payment_status,
        "payment_summary": payment_summary,
        "field_values_display": dynamic_fields,
    })
    return normalized


@app.route("/api/service-orders", methods=["GET"])
@login_required
def api_service_orders():
    """
    Fetch service orders from 'serviceJsonOrder' collection
    where booking_status == 'booked'.
    Returns a list sorted by created_at desc (newest first).
    """
    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable
        from google.cloud.firestore import FieldFilter

        db = get_project_b_firestore()
        if db is None:
            return jsonify({"found": False, "error": "Firestore client not initialized"}), 500

        limit = int(request.args.get("limit", "1000"))

        col = db.collection("serviceJsonOrder")
        q = (
            col.where(filter=FieldFilter("booking_status", "==", "booked"))
            .limit(limit)
            .stream()
        )

        items = []
        for doc in q:
            d = doc.to_dict() or {}
            d["id"] = doc.id

            # Normalize timestamp fields
            for ts_field in ("created_at", "updated_at", "date_of_service"):
                if ts_field in d:
                    iso = _ts_to_iso(d[ts_field])
                    d[ts_field] = iso
                    d[f"{ts_field}_readable"] = _iso_to_readable(iso)

            items.append(_normalize_service_json_order(d))

        # Sort newest first in memory (created_at is the best sort key)
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        items = items[:limit]

        logging.info(f"✅ Fetched {len(items)} service orders with booking_status=booked")
        logging.info("Service orders sample count: %s", len(items))
        if items:
            logging.info("Service orders sample (first 3): %s", json.dumps(items[:3], default=str))
        else:
            logging.info("Service orders response is empty")
        return jsonify({"found": True, "count": len(items), "items": items}), 200

    except Exception as e:
        logging.exception("Error fetching service orders")
        return jsonify({"found": False, "error": str(e)}), 500



@app.route("/api/service-orders/<order_id>", methods=["GET"])
@login_required
def api_service_order_detail(order_id):
    """Fetch a single service order from serviceJsonOrder by document ID."""
    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable

        db = get_project_b_firestore()
        if db is None:
            return jsonify({"found": False, "error": "Firestore not initialized"}), 500

        doc = db.collection("serviceJsonOrder").document(order_id).get()
        if not doc.exists:
            return jsonify({"found": False, "error": "Order not found"}), 404

        d = doc.to_dict() or {}
        d["id"] = doc.id

        for ts_field in ("created_at", "updated_at", "date_of_service"):
            if ts_field in d:
                iso = _ts_to_iso(d[ts_field])
                d[ts_field] = iso
                d[f"{ts_field}_readable"] = _iso_to_readable(iso)

        normalized_order = _normalize_service_json_order(d)

        # Enrich with user details if user_id present
        user_id = normalized_order.get("user_id")
        user_data = {}
        if user_id:
            try:
                user_doc = db.collection("users").document(user_id).get()
                if user_doc.exists:
                    u = user_doc.to_dict() or {}
                    user_data = {
                        "id": user_id,
                        "firstName": u.get("firstName", ""),
                        "lastName": u.get("lastName", ""),
                        "email": u.get("email", ""),
                        "phoneNumber": u.get("phoneNumber", ""),
                        "photoURL": u.get("photoURL", ""),
                    }
            except Exception as ue:
                logging.warning(f"Could not fetch user {user_id}: {ue}")

        # Enrich with vendor details if vendor_id present
        vendor_id = normalized_order.get("vendor_id")
        vendor_data = {}
        if vendor_id:
            try:
                vendor_doc = db.collection("vendor_credential").document(vendor_id).get()
                if vendor_doc.exists:
                    v = vendor_doc.to_dict() or {}
                    vendor_data = {
                        "id": vendor_id,
                        "name": v.get("name") or v.get("userName", ""),
                        "phone": v.get("phone") or v.get("phoneNumber", ""),
                        "email": v.get("email", ""),
                    }
            except Exception as ve:
                logging.warning(f"Could not fetch vendor {vendor_id}: {ve}")

        chat_data = _get_latest_chat_for_user(
            db,
            user_id=user_id,
            explicit_chat_id=normalized_order.get("chat_id") or d.get("chat_id") or "",
        )

        return jsonify({
            "found": True,
            "order": normalized_order,
            "raw_order": d,
            "user": user_data,
            "vendor": vendor_data,
            "chat": chat_data,
        }), 200

    except Exception as e:
        logging.exception("Error fetching service order detail")
        return jsonify({"found": False, "error": str(e)}), 500


@app.route("/api/service-orders/<order_id>/status", methods=["PUT"])
@login_required
def api_update_service_order_status(order_id):
    """Update the booking_status of a serviceJsonOrder document."""
    try:
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        body = request.get_json() or {}
        requested_status = (body.get("status") or "").strip().lower()
        status_aliases = {
            "confirmed": "alloted",
            "in_progress": "ongoing",
        }
        new_status = status_aliases.get(requested_status, requested_status)

        VALID_STATUSES = ["booked", "alloted", "ongoing", "completed", "cancelled"]
        if not new_status or new_status not in VALID_STATUSES:
            return jsonify({"success": False, "error": f"Invalid status. Must be one of: {VALID_STATUSES}"}), 400

        doc_ref = db.collection("serviceJsonOrder").document(order_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"success": False, "error": "Order not found"}), 404

        current_data = doc.to_dict() or {}
        old_status = status_aliases.get(
            (current_data.get("booking_status") or "").strip().lower(),
            (current_data.get("booking_status") or "unknown").strip().lower()
        )
        vendor_id = (current_data.get("vendor_id") or "").strip()

        if new_status == "alloted" and not vendor_id:
            return jsonify({
                "success": False,
                "error": "Vendor must be assigned before changing status to alloted"
            }), 400

        allowed_transitions = {
            "booked": ["booked", "alloted", "cancelled"],
            "alloted": ["alloted", "ongoing", "cancelled"],
            "ongoing": ["ongoing", "completed", "cancelled"],
            "completed": ["completed"],
            "cancelled": ["cancelled"],
        }
        allowed_next_statuses = allowed_transitions.get(old_status, [old_status])
        if new_status not in allowed_next_statuses:
            return jsonify({
                "success": False,
                "error": f"Invalid status transition from {old_status} to {new_status}. Allowed: {allowed_next_statuses}"
            }), 400

        doc_ref.update({
            "booking_status": new_status,
            "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        })

        logging.info(f"✅ serviceJsonOrder {order_id} status: {old_status} → {new_status}")
        return jsonify({"success": True, "order_id": order_id, "old_status": old_status, "new_status": new_status}), 200

    except Exception as e:
        logging.exception("Error updating service order status")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/service-orders/<order_id>/assign-vendor", methods=["PUT"])
@login_required
def api_assign_vendor_to_order(order_id):
    """Assign a vendor to a serviceJsonOrder document."""
    try:
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        body = request.get_json() or {}
        vendor_identifier = (body.get("vendor_id") or "").strip()
        vendor_price = body.get("vendor_price")

        if not vendor_identifier:
            return jsonify({"success": False, "error": "vendor_id is required"}), 400

        doc_ref = db.collection("serviceJsonOrder").document(order_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"success": False, "error": "Order not found"}), 404

        current_data = doc.to_dict() or {}

        vendor_doc_id = ""
        vendor_user_name = vendor_identifier
        vendor_id = vendor_identifier
        vendor_name = vendor_identifier
        try:
            from google.cloud.firestore import FieldFilter

            vendor_doc = db.collection("vendor_credential").document(vendor_identifier).get()
            if vendor_doc.exists:
                vd = vendor_doc.to_dict() or {}
                vendor_doc_id = vendor_doc.id
                vendor_user_name = vd.get("userName") or vendor_identifier
                vendor_name = vd.get("name") or vendor_user_name or vendor_identifier
            else:
                vendor_query = (
                    db.collection("vendor_credential")
                    .where(filter=FieldFilter("userName", "==", vendor_identifier))
                    .limit(1)
                    .stream()
                )
                vendor_doc = next(vendor_query, None)
                if vendor_doc:
                    vd = vendor_doc.to_dict() or {}
                    vendor_doc_id = vendor_doc.id
                    vendor_user_name = vd.get("userName") or vendor_identifier
                    vendor_name = vd.get("name") or vendor_user_name or vendor_identifier
        except Exception:
            pass

        update_data = {
            "vendor_id": vendor_user_name,
            "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        }
        if vendor_doc_id:
            update_data["vendor_doc_id"] = vendor_doc_id
        old_status = (current_data.get("booking_status") or "").strip().lower()
        if old_status == "booked":
            update_data["booking_status"] = "alloted"
        if vendor_price is not None:
            try:
                update_data["vendor_price"] = float(vendor_price)
            except (ValueError, TypeError):
                pass

        doc_ref.update(update_data)

        # Fetch vendor name for response
        vendor_name = vendor_user_name
        try:
            vdoc = db.collection("vendor_credential").document(vendor_doc_id or vendor_identifier).get()
            if vdoc.exists:
                vd = vdoc.to_dict() or {}
                vendor_name = vd.get("name") or vd.get("userName") or vendor_user_name
        except Exception:
            pass

        logging.info(f"✅ serviceJsonOrder {order_id} assigned to vendor {vendor_id}")
        return jsonify({
            "success": True,
            "order_id": order_id,
            "vendor_id": vendor_user_name,
            "vendor_doc_id": vendor_doc_id,
            "vendor_name": vendor_name,
            "new_status": update_data.get("booking_status", old_status or current_data.get("booking_status") or ""),
        }), 200

    except Exception as e:
        logging.exception("Error assigning vendor to order")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/vendors", methods=["GET"])
@login_required
def api_vendors():
    """Fetch all active vendors from vendor_credential collection."""
    try:
        db = get_project_b_firestore()
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500

        docs = db.collection("vendor_credential").stream()
        vendors = []
        for doc in docs:
            d = doc.to_dict() or {}
            # Only return active vendors
            if d.get("isActive") is False:
                continue
            vendors.append({
                "id": doc.id,
                "name": d.get("name") or d.get("userName") or doc.id,
                "phone": d.get("phone") or d.get("phoneNumber") or "",
                "email": d.get("email") or "",
                "userName": d.get("userName") or "",
            })

        vendors.sort(key=lambda x: x.get("name") or "")
        return jsonify({"success": True, "count": len(vendors), "vendors": vendors}), 200

    except Exception as e:
        logging.exception("Error fetching vendors")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------
# ✅ UPLOAD IMAGE (NO login_required)
# ---------------------------
@app.route("/api/upload-customer-service-image", methods=["POST"])
@login_required
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
