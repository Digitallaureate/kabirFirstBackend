from firebase_functions import firestore_fn
from firebase_admin import firestore
import logging
from datetime import datetime
import requests
import math

# If you want, you can move this to env later
PROCESS_TEXT_URL = "https://ecostory-backend-36036911566.us-central1.run.app/process-text/"
# ⬆️ change to /process_text or /process if that’s what you use in FastAPI


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two coordinates using Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371.0  # Radius of Earth in kilometers

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


@firestore_fn.on_document_created(document="chats/{chatId}/messages/{messageId}")
def on_message_created(event: firestore_fn.Event[firestore_fn.DocumentSnapshot]):
    """
    Triggered when a new message is added to any chat's messages subcollection.
    Path: chats/{chatId}/messages/{messageId}
    """
    try:
        message_data = event.data.to_dict()
        chat_id = event.params["chatId"]
        message_id = event.params["messageId"]

        logging.info(f"🔔 New message created in chat {chat_id}: {message_id}")
        logging.info(f"📝 Message data: {message_data}")

        role = message_data.get("role", "")
        content = message_data.get("content", "")
        location = message_data.get("location", "")
        created_at = message_data.get("created_at", datetime.utcnow())
        sender_user_id = str(message_data.get("user_id", "")).strip()  # ✅ Clean whitespace

        logging.info(f"🔎 RAW user_id from DB: '{message_data.get('user_id')}' -> Cleaned: '{sender_user_id}'")

        # 1️⃣ Skip user messages
        if role == "user":
            logging.info(f"👤 User message: {content[:100] if content else 'empty'}")
            logging.info(f"⏭️ Skipping - only processing assistant messages")
            return

        # 2️⃣ Avoid infinite loop: skip media/system assistant messages
        logging.warning(f"🔎 Checking sender: '{sender_user_id}' (Role: {role})")

        # ✅ FIXED: Simplified check - skip immediately if sender is CustomerService or error/system
        if sender_user_id in ("ImageG", "AudioG", "VideoG", "ErrorG", "CustomerService"):
            logging.warning(f"⏭️ Skipping message from ignored sender: '{sender_user_id}'")
            return

        if role == "assistant":
            logging.info(f"🤖 Assistant message: {content[:100] if content else 'empty'}")

            db = firestore.client()

            # --- Fetch chat meta ---
            chat_ref = db.collection("chats").document(chat_id)
            chat_doc = chat_ref.get()
            if not chat_doc.exists:
                logging.warning(f"⚠️ Chat document not found: {chat_id}")
                return

            chat_data = chat_doc.to_dict()
            chat_type = chat_data.get("chat_type", "")
            participants = chat_data.get("participants", [])

            logging.info(f"📋 Chat type: {chat_type}, Location: {location}")
            logging.info(f"👥 Participants: {participants}")

            # --- Find user + last known location ---
            user_id = None
            user_latitude = None
            user_longitude = None
            user_location_name = None

            if participants:
                user_id = participants[0]
                logging.info(f"👤 First participant user_id: {user_id}")

                try:
                    user_location_query = (
                        db.collection("user_locations")
                        .where("user_id", "==", user_id)
                        .order_by("created_at", direction=firestore.Query.DESCENDING)
                        .limit(1)
                    )
                    user_location_docs = user_location_query.get()

                    if user_location_docs:
                        user_location_data = user_location_docs[0].to_dict()
                        user_latitude = user_location_data.get("latitude")
                        user_longitude = user_location_data.get("longitude")
                        user_location_name = user_location_data.get("location")
                        logging.info(
                            f"📍 User location found: {user_location_name} "
                            f"({user_latitude}, {user_longitude})"
                        )
                    else:
                        logging.warning(f"⚠️ No location found for user_id: {user_id}")
                except Exception as loc_error:
                    logging.error(f"❌ Error fetching user location: {loc_error}")
            else:
                logging.warning("⚠️ No participants found in chat")

            # --- Build location_context skeleton ---
            location_context = {
                "chatId": chat_id,
                "messageId": message_id,
                "chat_type": chat_type,
                "location": location,
                "user_id": user_id,
                "user_latitude": user_latitude,
                "user_longitude": user_longitude,
                "user_location": user_location_name,
                "target_site": None,
                "nearby_sites": [],
                "nearby_trivia": [],
                "within_1km": False,
                "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            }

            # --- Global / non-journey: 3 nearest sites ---
            if chat_type != "journey" and user_latitude and user_longitude:
                try:
                    logging.info(f"🔍 Searching for nearby historical sites (chat_type: {chat_type})...")
                    historical_sites = (
                        db.collection("historical_sites")
                        .where("is_active", "==", True)
                        .stream()
                    )

                    sites_with_distance = []
                    for site_doc in historical_sites:
                        site_data = site_doc.to_dict()
                        site_id = site_doc.id
                        site_lat = site_data.get("latitude")
                        site_lon = site_data.get("longitude")
                        if site_lat and site_lon:
                            try:
                                site_lat = float(site_lat)
                                site_lon = float(site_lon)
                                distance = calculate_distance(
                                    user_latitude, user_longitude, site_lat, site_lon
                                )
                                sites_with_distance.append(
                                    {
                                        "site_id": site_id,
                                        "site_name": site_data.get("site_name"),
                                        "location": site_data.get("location"),
                                        "distance_km": round(distance, 2),
                                        "latitude": site_lat,
                                        "longitude": site_lon,
                                        "prompt": site_data.get("prompt"),
                                        "site_description": site_data.get("site_description"),
                                        "services": site_data.get("services", []),
                                    }
                                )
                            except (ValueError, TypeError) as e:
                                logging.warning(f"⚠️ Invalid coordinates for site {site_id}: {e}")
                                continue

                    sites_with_distance.sort(key=lambda x: x["distance_km"])
                    location_context["nearby_sites"] = sites_with_distance[:3]

                    logging.info(f"✅ Found {len(location_context['nearby_sites'])} nearby sites")
                except Exception as sites_error:
                    logging.error(f"❌ Error finding nearby sites: {sites_error}")

            # --- Journey: distance to target site + trivia ---
            elif chat_type == "journey" and user_latitude and user_longitude and location:
                logging.info(f"🚶 Journey mode: Checking distance to {location}")
                try:
                    site_query = (
                        db.collection("historical_sites")
                        .where("site_name", "==", location)
                        .where("is_active", "==", True)
                        .limit(1)
                    )
                    site_docs = site_query.get()

                    if site_docs:
                        site_data = site_docs[0].to_dict()
                        site_id = site_docs[0].id
                        site_lat = float(site_data.get("latitude"))
                        site_lon = float(site_data.get("longitude"))

                        distance_to_site = calculate_distance(
                            user_latitude, user_longitude, site_lat, site_lon
                        )
                        logging.info(f"📏 Distance to {location}: {distance_to_site:.2f} km")

                        location_context["target_site"] = {
                            "site_id": site_id,
                            "site_name": location,
                            "distance_km": round(distance_to_site, 2),
                            "latitude": site_lat,
                            "longitude": site_lon,
                        }
                        location_context["within_1km"] = distance_to_site < 1.0

                        # Fetch trivia if within 1km
                        if distance_to_site < 1.0:
                            logging.info("✅ Within 1km, fetching nearby trivia...")
                            try:
                                trivia_query = (
                                    db.collection("trivia")
                                    .where("location", "==", location)
                                    .where("is_active", "==", True)
                                    .stream()
                                )
                                trivia_with_distance = []

                                for trivia_doc in trivia_query:
                                    trivia_data = trivia_doc.to_dict()
                                    trivia_id = trivia_doc.id
                                    trivia_lat = trivia_data.get("latitude")
                                    trivia_lon = trivia_data.get("longitude")
                                    if trivia_lat and trivia_lon:
                                        try:
                                            trivia_lat = float(trivia_lat)
                                            trivia_lon = float(trivia_lon)
                                            trivia_distance = calculate_distance(
                                                user_latitude, user_longitude,
                                                trivia_lat, trivia_lon
                                            )
                                            trivia_with_distance.append(
                                                {
                                                    "id": trivia_id,
                                                    "assistant_id": trivia_data.get("assistant_id"),
                                                    "title": trivia_data.get("title"),
                                                    "content": trivia_data.get("content"),
                                                    "location": trivia_data.get("location"),
                                                    "latitude": trivia_lat,
                                                    "longitude": trivia_lon,
                                                    "distance": round(trivia_distance, 2),
                                                    "tags": trivia_data.get("tags", []),
                                                    "category": trivia_data.get("category"),
                                                    "created_at": trivia_data.get("created_at"),
                                                    "is_active": trivia_data.get("is_active"),
                                                }
                                            )
                                        except (ValueError, TypeError) as e:
                                            logging.warning(
                                                f"⚠️ Invalid coordinates for trivia {trivia_id}: {e}"
                                            )
                                            continue

                                trivia_with_distance.sort(key=lambda x: x["distance"])
                                location_context["nearby_trivia"] = trivia_with_distance[:3]
                                logging.info(
                                    f"✅ Found {len(location_context['nearby_trivia'])} nearby trivia"
                                )
                            except Exception as trivia_error:
                                logging.error(f"❌ Error fetching trivia: {trivia_error}")
                        else:
                            logging.info(
                                f"⏭️ Distance {distance_to_site:.2f}km (>= 1km), skipping trivia fetch"
                            )
                    else:
                        logging.warning(f"⚠️ Historical site not found for location: {location}")
                except Exception as journey_error:
                    logging.error(f"❌ Error processing journey logic: {journey_error}")

            # --- Save locationContext ---
            db.collection("locationContext").document(message_id).set(location_context)
            logging.info(f"✅ Location context stored for message {message_id}")

            # --- Get chapter_id from knowldge_base ---
            chapter_id = None
            if chat_type and location:
                knowledge_query = (
                    db.collection("knowldge_base")
                    .where("chat_type", "==", chat_type)
                    .where("param", "==", location)
                    .limit(1)
                )
                knowledge_docs = knowledge_query.get()
                if knowledge_docs:
                    knowledge_data = knowledge_docs[0].to_dict()
                    chapter_id = knowledge_data.get("chapterId")
                    logging.info(f"✅ Found chapter_id: {chapter_id}")
                else:
                    logging.warning(
                        f"⚠️ No knowledge base found for chat_type={chat_type}, param={location}"
                    )
            else:
                logging.warning("⚠️ Missing chat_type or location")

            # --- Log assistant message ---
            message_log = {
                "chat_id": chat_id,
                "message_id": message_id,
                "role": role,
                "content": content,
                "location": location,
                "chat_type": chat_type,
                "chapter_id": chapter_id,
                "user_id": user_id,
                "user_latitude": user_latitude,
                "user_longitude": user_longitude,
                "user_location": user_location_name,
                "nearby_sites": location_context["nearby_sites"],
                "nearby_trivia": location_context["nearby_trivia"],
                "created_at": created_at,
                "logged_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "original_path": f"chats/{chat_id}/messages/{message_id}",
            }
            db.collection("message_logs").document(message_id).set(message_log)
            logging.info(f"✅ Assistant message logged: {message_id}")

            # --- Find latest USER message to use for process-text ---
            last_user_message_id = None
            last_user_content = None
            last_user_location = None
            try:
                last_user_query = (
                    db.collection("chats")
                    .document(chat_id)
                    .collection("messages")
                    .where("role", "==", "user")
                    .order_by("created_at", direction=firestore.Query.DESCENDING)
                    .limit(1)
                )
                last_user_docs = last_user_query.get()

                if last_user_docs:
                    last_user_message_id = last_user_docs[0].id  # ✅ add this
                    last_user_data = last_user_docs[0].to_dict()
                    last_user_content = last_user_data.get("content")
                    last_user_location = last_user_data.get("location")
                    logging.info(
                        f"🧑‍💬 Last user message for process-text: "
                        f"{last_user_content[:100] if last_user_content else 'empty'}"
                    )
                else:
                    logging.warning(
                        f"⚠️ No previous user message found for chat {chat_id}; "
                        f"falling back to assistant content"
                    )
            except Exception as e:
                logging.error(f"❌ Error fetching last user message: {e}")

            # --- NEW: Check for magic words in last user message ---
            if last_user_content:
                try:
                    # IMPORTANT: you must have last_user_message_id captured in your last_user_query block
                    if not last_user_message_id:
                        logging.warning("⚠️ last_user_message_id missing; cannot create magicWordUser safely")
                    else:
                        logging.info("🔮 Checking for magic words in last user message...")

                        # Fetch active magic words
                        magic_words_query = db.collection("magicWord").where("isActive", "==", True).stream()
                        magic_words_list = []
                        for magic_doc in magic_words_query:
                            magic_data = magic_doc.to_dict()
                            magic_word = magic_data.get("title")
                            if magic_word:
                                magic_words_list.append({
                                    "id": magic_doc.id,
                                    "word": magic_word.lower()
                                })

                        user_content_lower = last_user_content.lower()
                        matched_magic_words = [m for m in magic_words_list if m["word"] in user_content_lower]

                        if matched_magic_words:
                            for matched in matched_magic_words:
                                # ✅ Use USER message id, not assistant message id
                                magic_user_doc_id = f"{last_user_message_id}_{matched['id']}"
                                doc_ref = db.collection("magicWordUser").document(magic_user_doc_id)

                                # ✅ Create only once
                                logging.warning(f"🔍 Checking if request exists: {magic_user_doc_id}")
                                if doc_ref.get().exists:
                                    logging.warning(f"⚠️ magicWordUser already exists: {magic_user_doc_id} (skip)")
                                    continue

                                magic_user_data = {
                                    "chatId": chat_id,
                                    "messageId": last_user_message_id,     # ✅ user message id
                                    "userId": user_id,
                                    "magicWordId": matched["id"],
                                    "magicWord": matched["word"],
                                    "userMessage": last_user_content,
                                    "assistantMessage": content,              # ✅ don't set from CS/assistant
                                    "location": (last_user_location or location or user_location_name or ""),
                                    "matchedAt": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                                    "isActive": True,
                                    "status": "requested",
                                }

                                doc_ref.set(magic_user_data)
                                logging.info(f"✅ Magic word user record CREATED: {magic_user_doc_id}")
                        else:
                            logging.info("ℹ️ No magic words found in last user message")

                except Exception as magic_error:
                    logging.error(f"❌ Error checking magic words: {magic_error}")
            else:
                logging.warning("⚠️ No user content available to check for magic words")

            # if last_user_content:
            #     try:
            #         logging.info("🔮 Checking for magic words in user message...")
                    
            #         db = firestore.client()
                    
            #         # Fetch all active magic words from magicWord collection
            #         magic_words_query = db.collection("magicWord").where("isActive", "==", True).stream()
            #         magic_words_list = []
                    
            #         for magic_doc in magic_words_query:
            #             magic_data = magic_doc.to_dict()
            #             # your schema uses 'title' for the magic word text
            #             magic_word = magic_data.get("title")
            #             if magic_word:
            #                 magic_words_list.append({
            #                     "id": magic_doc.id,
            #                     "word": magic_word.lower(),
            #                     "data": magic_data
            #                 })
                    
            #         logging.info(f"📋 Found {len(magic_words_list)} magic words to check")
                    
            #         # Check if any magic word is in user message (case-insensitive)
            #         user_content_lower = last_user_content.lower()
            #         matched_magic_words = []
                    
            #         for magic in magic_words_list:
            #             if magic["word"] in user_content_lower:
            #                 matched_magic_words.append(magic)
            #                 logging.info(f"✨ Magic word matched: '{magic['word']}'")
                    
            #         # If magic words found, update magicWordUser collection
            #         if matched_magic_words:
            #             for matched in matched_magic_words:
            #                 magic_user_doc_id = f"{message_id}_{matched['id']}"
            #                 magic_user_data = {
            #                     "chatId": chat_id,
            #                     "messageId": message_id,
            #                     "userId": user_id,
            #                     "magicWordId": matched["id"],
            #                     "magicWord": matched["word"],
            #                     "userMessage": last_user_content,
            #                     "assistantMessage": content,
            #                     "location": location or user_location_name,
            #                     "matchedAt": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            #                     "isActive": True,
            #                     "status": "requested",
            #                 }
                            
            #                 db.collection("magicWordUser").document(magic_user_doc_id).set(magic_user_data)
            #                 logging.info(f"✅ Magic word user record created/updated: {magic_user_doc_id}")
            #         else:
            #             logging.info("ℹ️ No magic words found in user message")
                        
            #     except Exception as magic_error:
            #         logging.error(f"❌ Error checking magic words: {magic_error}")
            # else:
            #     logging.warning("⚠️ No user content available to check for magic words")

            # --- Call chatSuggestionData (existing) ---
            if chapter_id:
                try:
                    logging.info(
                        f"📞 Calling chatSuggestionData API with chapter_id={chapter_id}, chat_id={chat_id}"
                    )
                    api_payload = {
                        "chapterId": chapter_id,
                        "content": content,
                        "location": location,
                        "chatId": chat_id,
                    }
                    api_url = "https://us-central1-ecostory-b31b6.cloudfunctions.net/chatSuggestionData"
                    response = requests.post(
                        api_url,
                        json=api_payload,
                        headers={"Content-Type": "application/json"},
                        timeout=30,
                    )
                    if response.status_code == 200:
                        suggestion_data = response.json()
                        db.collection("message_logs").document(message_id).update(
                            {
                                "suggestions": suggestion_data,
                                "suggestions_fetched_at": datetime.utcnow().isoformat(
                                    timespec="milliseconds"
                                )
                                + "Z",
                            }
                        )
                        logging.info(f"✅ Suggestions stored for message {message_id}")
                    else:
                        logging.warning(
                            f"⚠️ chatSuggestionData API returned {response.status_code}: {response.text}"
                        )
                except requests.exceptions.Timeout:
                    logging.error("❌ chatSuggestionData API timeout")
                except requests.exceptions.RequestException as api_error:
                    logging.error(f"❌ Error calling chatSuggestionData API: {api_error}")
                except Exception as api_exception:
                    logging.exception(
                        f"❌ Unexpected error calling chatSuggestionData API: {api_exception}"
                    )
            else:
                logging.warning("⚠️ No chapter_id, skipping chatSuggestionData API call")

                        # ✅ Call process-text API on Cloud Run
            if chapter_id and user_latitude is not None and user_longitude is not None:
                try:
                    content_for_process = last_user_content or content
                    logging.info(
                        f"📞 Calling process-text API with chapter_id={chapter_id}, "
                        f"chat_id={chat_id}, location={location}, "
                        f"lat={user_latitude}, long={user_longitude}"
                    )

                    process_payload = {
                        "content": content_for_process,
                        "chapterId": chapter_id,
                        "chatId": chat_id,
                        "lat": float(user_latitude),
                        "long": float(user_longitude),
                        "location": location or (user_location_name or "")
                    }

                    logging.info(f"📤 process-text payload: {process_payload}")

                    response = requests.post(
                        PROCESS_TEXT_URL,
                        json=process_payload,
                        headers={"Content-Type": "application/json"},
                        timeout=30
                    )

                    if response.status_code == 200:
                        process_data = response.json()
                        logging.info(f"✅ process-text API response: {process_data}")

                        # Optional: store response for debugging / analytics
                        db.collection("message_logs").document(message_id).update({
                            "process": process_data,
                            "process_fetched_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
                        })

                        logging.info(f"✅ process-text result stored for message {message_id}")

                    else:
                        logging.warning(
                            f"⚠️ process-text API returned {response.status_code}: {response.text}"
                        )

                except requests.exceptions.Timeout:
                    logging.error("❌ process-text API timeout")
                except requests.exceptions.RequestException as api_error:
                    logging.error(f"❌ Error calling process-text API: {api_error}")
                except Exception as api_exception:
                    logging.exception(f"❌ Unexpected error calling process-text API: {api_exception}")
            else:
                logging.warning(
                    f"⚠️ Skipping process-text call (chapter_id={chapter_id}, "
                    f"user_latitude={user_latitude}, user_longitude={user_longitude})"
                )


        else:
            # Some other role (very unlikely)
            logging.info(f"💬 Message from {role}: {content[:100] if content else 'empty'}")
            logging.info("⏭️ Skipping - only processing assistant messages")

    except Exception as e:
        logging.exception(f"❌ Error processing message: {e}")
