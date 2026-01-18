from firebase_functions import https_fn
from firebase_functions.https_fn import Request
from datetime import datetime
import logging
import os
from openai import OpenAI
from pinecone import Pinecone
from dotenv import load_dotenv
import json

from firebase_setup import get_project_b_firestore

# Load environment variables
load_dotenv(".env.dev")

project_b_db = get_project_b_firestore()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
PINECONE_INDEX_HOST = os.getenv("PINECONE_INDEX_HOST")

if not PINECONE_INDEX_HOST:
    raise EnvironmentError("Missing PINECONE_INDEX_HOST for serverless Pinecone setup")

@https_fn.on_request()
def searchImageFromDatabase(req: Request) -> https_fn.Response:
    try:
        data = req.get_json(silent=True)
        if not data:
            return https_fn.Response("Invalid JSON payload", status=400)

        chapterId = data.get("chapterId")
        chatId = data.get("chatId")
        content = data.get("content")
        lat = data.get("lat")
        long = data.get("long")
        location = data.get("location")

        if not chapterId or not chatId or not content or not lat or not long or not location:
            return https_fn.Response("Missing required parameters", status=400)

        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

        chapter_check_response = index.query(
            vector=[0.0] * 1536,
            top_k=1,
            filter={"chapterId": chapterId},
            include_metadata=True
        )

        matches = chapter_check_response.get("matches", [])

        chat_doc_ref = project_b_db.collection("chats").document(chatId)
        chat_doc = chat_doc_ref.get()
        if not chat_doc.exists:
            return https_fn.Response(
                json.dumps({"error": f"Chat ID '{chatId}' not found in Project B."}),
                status=404,
                content_type="application/json"
            )

        if not matches:
            # No match found
            description = "Sorry, I don't have an image for this place. Kindly upload or generate a relevant one."
            image_url = None
            score = 0.0

            message_data = {
                "content": description,
                "image_url": image_url,
                "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "location": location,
                "role": "assistant",
                "user_id": "ImageG",
            }

            doc_ref = chat_doc_ref.collection("messages").document()
            message_id = doc_ref.id
            message_data["id"] = message_id
            doc_ref.set(message_data)

            return https_fn.Response(
                json.dumps({
                    "message": "Message written to Firestore",
                    "id": message_id,
                    "score": score,
                    "content": description,
                    "created_at": message_data["created_at"],
                    "image_url": image_url,
                    "location": location,
                    "role": "assistant",
                    "userId": "ImageG",
                }),
                status=200,
                content_type="application/json"
            )

        # Semantic search
        embedding_response = client.embeddings.create(
            model="text-embedding-ada-002",
            input=content
        )
        query_vector = embedding_response.data[0].embedding

        search_response = index.query(
            vector=query_vector,
            top_k=1,
            filter={"chapterId": chapterId},
            include_metadata=True
        )

        matches = search_response.get("matches", [])

        if not matches:
            return https_fn.Response("No semantic matches found", status=404)

        top_match = matches[0]
        score = top_match["score"]
        original_description = top_match["metadata"].get("imageDesc", "No description found.")
        image_url = top_match["metadata"].get("imageURL", "No image URL found.")

        description = original_description
        if score <= 0.757:
            description += "\n\nThis is the closest image I could find—feel free to upload a more relevant one!"

        message_data = {
            "content": description,
            "image_url": image_url,
            "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "location": location,
            "role": "assistant",
            "user_id": "ImageG",
        }

        doc_ref = chat_doc_ref.collection("messages").document()
        message_id = doc_ref.id
        message_data["id"] = message_id
        doc_ref.set(message_data)

        return https_fn.Response(
            json.dumps({
                "message": "Message written to Firestore",
                "id": message_id,
                "score": score,
                "content": description,
                "created_at": message_data["created_at"],
                "image_url": image_url,
                "location": location,
                "role": "assistant",
                "userId": "ImageG",
            }),
            status=200,
            content_type="application/json"
        )

    except Exception as e:
        logging.exception("Error during imageSearch")
        return https_fn.Response(f"Error: {str(e)}", status=500)
