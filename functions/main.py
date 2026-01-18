# Cloud Functions for Firebase SDK
from firebase_functions import firestore_fn, https_fn

# Firebase Admin SDK to access Firestore
from firebase_admin import initialize_app  # ✅ Added credentials import
import google.cloud.firestore

# ✅ Initialize default app (Project A: kabir-assistant-api)
app = initialize_app()


# Import HTTP trigger functions
from imageSearch import searchImageFromDatabase
from videoSearch import searchVideoFromDatabase
from audioSearch import searchAudioFromDatabase
from deviceRedirect import device_redirect
from chatSuggestionData import chatSuggestionData
from process_text import process_text
from messageListener import on_message_created







# HTTP Function: addmessage
@https_fn.on_request()
def addmessage(req: https_fn.Request) -> https_fn.Response:
    """
    Receives a 'text' parameter via HTTP request,
    saves it in Firestore as 'original' field.
    """
    # Grab 'text' from query parameters
    original = req.args.get("text")
    if original is None:
        return https_fn.Response("No text parameter provided", status=400)

    firestore_client: google.cloud.firestore.Client = firestore.client()
    _, doc_ref = firestore_client.collection("messages").add({"original": original})

    return https_fn.Response(f"Message with ID {doc_ref.id} added.")


# Firestore Trigger: makeuppercase
@firestore_fn.on_document_created(document="messages/{pushId}")
def makeuppercase(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """
    When a new document is created in 'messages', 
    this function adds an 'uppercase' field by converting 'original' to uppercase.
    """
    if event.data is None:
        return

    try:
        original = event.data.get("original")
    except KeyError:
        return

    upper = original.upper()
    event.data.reference.update({"uppercase": upper})
