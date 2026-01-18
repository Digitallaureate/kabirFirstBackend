from firebase_functions import https_fn
from firebase_functions.https_fn import Request
from datetime import datetime
import logging
import os
import json
from openai import OpenAI
from pinecone import Pinecone
from dotenv import load_dotenv
from firebase_setup import get_project_b_firestore

# Load environment variables
load_dotenv(".env.dev")

# Firestore (Project B)
project_b_db = get_project_b_firestore()

# OpenAI & Pinecone
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# List all your index names and hosts
INDEXES = [
    {"name": os.getenv("KABIR_INDEX_NAME"),       "host": os.getenv("KABIR_INDEX_HOST")},
    {"name": os.getenv("PINECONE_INDEX_NAME"),    "host": os.getenv("PINECONE_INDEX_HOST")},
    {"name": os.getenv("PINECONE_INDEX_NAME2"),   "host": os.getenv("PINECONE_INDEX_HOST2")},
    {"name": os.getenv("PINECONE_INDEX_NAME3"),   "host": os.getenv("PINECONE_INDEX_HOST3")},
]

# Selection settings
SCORE_THRESHOLD = 0.75
MAX_RESULTS = 5
TYPE_QUOTAS = {"text": 2, "image": 1, "video": 1, "audio": 1}
FALLBACK_FILL = True
TOP_K_PER_INDEX = 10  # pull more so quotas can be satisfied

@https_fn.on_request()
def chatSuggestionData(req: Request) -> https_fn.Response:
    try:
        data = req.get_json(silent=True) or {}
        chapterId = data.get("chapterId")
        chatId    = data.get("chatId")
        content   = data.get("content")
        location  = data.get("location")

        # Validate inputs
        if not all([chapterId, chatId, content, location]):
            return https_fn.Response("Missing required parameters", status=400)

        # Get embedding for the query
        embedding_response = client.embeddings.create(
            model="text-embedding-ada-002",  # match your upsert model
            input=content
        )
        query_vector = embedding_response.data[0].embedding

        print(f"Searching for chapterId: {chapterId} with content: {content}")
        print(f"Using indexes: {INDEXES}")

        # Collect by type and dedupe
        buckets = {"text": [], "image": [], "video": [], "audio": []}
        all_items = []
        seen = set()

        pc = Pinecone(api_key=PINECONE_API_KEY)

        # Query each index
        for idx in INDEXES:
            if not idx["name"] or not idx["host"]:
                continue

            index = pc.Index(name=idx["name"], host=idx["host"])
            search_response = index.query(
                vector=query_vector,
                top_k=TOP_K_PER_INDEX,
                filter={"chapterId": {"$eq": chapterId}},
                include_metadata=True
            )

            matches = search_response.get("matches", [])
            for match in matches:
                if match.get("score", 0) < SCORE_THRESHOLD:
                    continue

                md = match.get("metadata", {}) or {}

                # normalize/try common key variants for URL fields
                video_url = md.get("videoURL") or md.get("videoUrl") or md.get("video_url")
                image_url = md.get("imageURL") or md.get("imageUrl") or md.get("image_url")
                audio_url = md.get("audioURL") or md.get("audioUrl") or md.get("audio_url")

                if has_value(video_url):
                    item_type = "video"
                    url = video_url
                    desc = md.get("videoDesc", "") or md.get("video_desc", "") or ""
                    text = md.get("text", "") or ""
                elif has_value(image_url):
                    item_type = "image"
                    url = image_url
                    desc = md.get("imageDesc", "") or md.get("image_desc", "") or ""
                    text = md.get("text", "") or ""
                elif has_value(audio_url):
                    item_type = "audio"
                    url = audio_url
                    desc = md.get("audioDesc", "") or md.get("audio_desc", "") or ""
                    text = md.get("text", "") or ""
                else:
                    item_type = "text"
                    url = None
                    desc = ""
                    text = md.get("text", "") or ""

                item = {
                    "score": match.get("score", 0),
                    "id": match.get("id"),
                    "chatId": chatId,
                    "type": item_type,
                    "description": desc,
                    "text": text,
                    "url": url,
                    "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                    "location": location,
                    "role": "assistant",
                    "read": False
                }

                key = f"{item_type}:{match['id']}"
                if key in seen:
                    continue
                seen.add(key)

                buckets[item_type].append(item)
                all_items.append(item)

        # Sort each bucket by score desc
        for t in buckets:
            buckets[t].sort(key=lambda x: x.get("score", 0), reverse=True)

        # Pick items according to quotas
        selected = []
        for t, q in TYPE_QUOTAS.items():
            selected.extend(buckets[t][:q])

        # Backfill if enabled
        if FALLBACK_FILL and len(selected) < MAX_RESULTS:
            selected_keys = {f"{i['type']}:{i['id']}" for i in selected}
            leftovers = [i for i in all_items if f"{i['type']}:{i['id']}" not in selected_keys]
            leftovers.sort(key=lambda x: x.get("score", 0), reverse=True)
            need = MAX_RESULTS - len(selected)
            selected.extend(leftovers[:need])

        # Cap to MAX_RESULTS
        results = selected[:MAX_RESULTS]

        print(
            f"Selected {len(results)} (text={len([i for i in results if i['type']=='text'])}, "
            f"image={len([i for i in results if i['type']=='image'])}, "
            f"video={len([i for i in results if i['type']=='video'])}, "
            f"audio={len([i for i in results if i['type']=='audio'])})"
        )

        # Write each to Firestore
        col_ref = project_b_db.collection("chatRecomendation")
        batch = project_b_db.batch()
        written_refs = []
        for item in results:
            doc_ref = col_ref.document()
            item["docId"] = doc_ref.id 
            batch.set(doc_ref, item)
            written_refs.append(doc_ref)
        batch.commit()

        return https_fn.Response(
            json.dumps({
                "message": "Chat recommendations inserted",
                "count": len(written_refs),
                "data": results
            }),
            status=200,
            content_type="application/json"
        )

    except Exception as e:
        logging.exception("Error during multi-index search")
        return https_fn.Response(f"Error: {str(e)}", status=500)

# helper to test presence of meaningful values (handles None, empty, "nan", etc.)
def has_value(v):
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    if s.lower() in {"nan", "none", "null"}:
        return False
    return True
