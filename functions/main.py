# Cloud Functions for Firebase SDK
from firebase_functions import firestore_fn, https_fn

# Firebase Admin SDK to access Firestore
from firebase_admin import initialize_app, firestore  # ✅ import firestore properly
import google.cloud.firestore

# ✅ Initialize default app (Project A: kabir-assistant-api)
initialize_app()

# Import HTTP trigger functions (UNCHANGED)
from imageSearch import searchImageFromDatabase
from videoSearch import searchVideoFromDatabase
from audioSearch import searchAudioFromDatabase
from deviceRedirect import device_redirect
from chatSuggestionData import chatSuggestionData
from process_text import process_text
from messageListener import on_message_created

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
    # Create Flask request context from the WSGI environ
    with flask_app.request_context(req.environ):
        resp = flask_app.full_dispatch_request()

    # Convert Flask Response -> Firebase Response
    return https_fn.Response(
        resp.get_data(),
        status=resp.status_code,
        headers=dict(resp.headers),
        content_type=resp.content_type,
    )
