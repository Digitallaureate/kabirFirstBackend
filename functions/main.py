# Cloud Functions for Firebase SDK
from firebase_functions import firestore_fn, https_fn
from io import BytesIO

# Firebase Admin SDK to access Firestore
from firebase_admin import initialize_app, firestore  # ✅ import firestore properly
import google.cloud.firestore

# ✅ Initialize default app. Resolves at runtime to the deployed project,
# which is ecostory-b31b6 (see .firebaserc default + readme deploy steps).
initialize_app()

# Import HTTP trigger functions (UNCHANGED)
from imageSearch import searchImageFromDatabase
from videoSearch import searchVideoFromDatabase
from audioSearch import searchAudioFromDatabase
from deviceRedirect import device_redirect
from chatSuggestionData import chatSuggestionData
from process_text import process_text
from messageListener import on_message_created
from serviceOrderListener import notify_vendors_on_open_order

# -------------------------
# HTTP Function: addmessage (same behavior)
# -------------------------
@https_fn.on_request()
def addmessage(req: https_fn.Request) -> https_fn.Response:
    """
    Receives a 'text' parameter via HTTP request,
    saves it in Firestore as 'original' field.
    """
    original = req.args.get("text")
    if original is None:
        return https_fn.Response("No text parameter provided", status=400)

    firestore_client: google.cloud.firestore.Client = firestore.client()
    _, doc_ref = firestore_client.collection("messages").add({"original": original})

    return https_fn.Response(f"Message with ID {doc_ref.id} added.")


# -------------------------
# Firestore Trigger: makeuppercase (same behavior)
# -------------------------
@firestore_fn.on_document_created(document="messages/{pushId}")
def makeuppercase(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """
    When a new document is created in 'messages',
    this function adds an 'uppercase' field by converting 'original' to uppercase.
    """
    if event.data is None:
        return

    original = event.data.get("original")
    if not original:
        return

    event.data.reference.update({"uppercase": original.upper()})


# -------------------------
# ✅ Customer Service Admin Panel (Flask) - NEW
# -------------------------
from app import app as flask_app  # your app.py (has SubPathMiddleware + templates)

@https_fn.on_request()
def customerService_app(req: https_fn.Request) -> https_fn.Response:
    """
    Exposes the Flask admin panel at /support/** via Firebase Hosting rewrite.
    """
    environ = dict(req.environ)

    # Ensure Flask reads a stable in-memory request body inside the emulator.
    raw_body = req.get_data(cache=True)
    environ["wsgi.input"] = BytesIO(raw_body)
    environ["CONTENT_LENGTH"] = str(len(raw_body))

    status_holder = {}

    def start_response(status, headers, exc_info=None):
        status_holder["status"] = status
        status_holder["headers"] = headers
        return None

    response_iter = flask_app.wsgi_app(environ, start_response)
    try:
        response_body = b"".join(response_iter)
    finally:
        close_fn = getattr(response_iter, "close", None)
        if close_fn:
            close_fn()

    status_code = int(status_holder.get("status", "500").split()[0])
    headers = dict(status_holder.get("headers", []))
    content_type = headers.pop("Content-Type", None)

    return https_fn.Response(
        response_body,
        status=status_code,
        headers=headers,
        content_type=content_type,
    )
