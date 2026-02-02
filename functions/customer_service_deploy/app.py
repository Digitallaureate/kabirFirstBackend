from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import logging
import os
from functools import wraps
from datetime import datetime
from uuid import uuid4
from urllib.parse import quote

# ✅ Import from your package modules
from customerService.user_summary import get_user_summary_by_phone
from customerService.magic_word_summary import get_magicword_requests, get_magicword_detail, get_user_magicword_requests, get_user_completed_orders, get_user_payment_history
from google.cloud import firestore as gfirestore

from firebase_setup import get_project_b_firestore, get_project_b_storage_bucket


app = Flask(
    __name__,
    template_folder="customerService/templates"
)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-to-a-long-random-secret")

# ✅ Handle /support sub-path
# This ensures that when hosted at /support, Flask sees correct paths (e.g. /login instead of /support/login)
# and generates correct URLs (e.g. /support/login).
class SubPathMiddleware:
    def __init__(self, app, prefix='/support'):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path_info = environ.get('PATH_INFO', '')
        if path_info.startswith(self.prefix):
            environ['PATH_INFO'] = path_info[len(self.prefix):] or '/'
            environ['SCRIPT_NAME'] = self.prefix
        return self.app(environ, start_response)

app.wsgi_app = SubPathMiddleware(app.wsgi_app)


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

    username = ""
    password = ""

    if request.is_json:
        body = request.get_json() or {}
        username = (body.get("username") or "").strip()
        password = (body.get("password") or "").strip()
    else:
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

    if not username or not password:
        if request.is_json:
            return jsonify({"success": False, "error": "Username and password are required"}), 400
        return render_template("index.html", error="Username and password are required")

    result = verify_admin_from_firestore(username, password)

    if not result.get("ok"):
        err = result.get("error", "Login failed")
        if request.is_json:
            return jsonify({"success": False, "error": err}), 401
        return render_template("index.html", error=err)

    session["admin_logged_in"] = True
    session["admin_user"] = result.get("user")

    if request.is_json:
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
        limit = int(request.args.get("limit", "100"))
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
            "image_url": image_url or None,  # ✅ image only (key)
            "user_id": "SystemG",
            "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "location": chat_location,
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

        # Update the field
        doc_ref.update({"isHumanInteraction": is_human})

        return jsonify({"success": True, "chatId": chat_id, "isHumanInteraction": is_human}), 200

    except Exception as e:
        logging.exception("Error toggling interaction mode")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------
# ✅ UPLOAD IMAGE (NO login_required as you asked)
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
