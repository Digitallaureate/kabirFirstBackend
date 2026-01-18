from firebase_functions import https_fn
from firebase_functions.https_fn import Request
import json
import os
from openai import OpenAI
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv(".env.dev")

# OpenAI setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Intent categories
INTENTS = {
    "search_image": "searchImageFromDatabase",
    "search_audio": "searchAudioFromDatabase", 
    "search_video": "searchVideoFromDatabase"
}

@https_fn.on_request()
def process_text(req: Request) -> https_fn.Response:
    try:
        data = req.get_json(silent=True)
        if not data:
            return https_fn.Response("Invalid JSON payload", status=400)

        user_text = data.get("text")
        if not user_text:
            return https_fn.Response("Missing 'text' parameter", status=400)

        # Step 1: Get intent from OpenAI
        intent = classify_intent(user_text)
        
        # Step 2: Call appropriate API based on intent
        response = call_intent_api(intent, data)
        
        return https_fn.Response(
            json.dumps({
                "intent": intent,
                "response": response
            }),
            status=200,
            content_type="application/json"
        )

    except Exception as e:
        return https_fn.Response(f"Error: {str(e)}", status=500)

def classify_intent(user_text: str) -> str:
    """Use OpenAI to classify the user's intent"""
    
    prompt = f"""
    Classify the following user text into one of these 5 categories:
    
    1. search_image - User wants to search for images
    2. search_audio - User wants to search for audio files
    3. search_video - User wants to search for videos
    4. web_search - User wants to search the web for information
    5. generate_image - User wants to generate/create a new image
    
    User text: "{user_text}"
    
    Respond with only the category name (e.g., "search_image").
    
    Examples:
    - "Show me pictures of India Gate" -> search_image
    - "Find audio about Delhi" -> search_audio
    - "Play video of Republic Day" -> search_video
    - "What is the history of India Gate?" -> web_search
    - "Create an image of a sunset" -> generate_image
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are an intent classifier. Respond only with the category name."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        intent = response.choices[0].message.content.strip().lower()
        
        # Validate intent
        if intent in INTENTS:
            return intent
        else:
            return "search_image"  # Default fallback
            
    except Exception as e:
        print(f"Error classifying intent: {e}")
        return "search_image"  # Default fallback

def call_intent_api(intent: str, original_data: dict) -> dict:
    """Call the appropriate API based on the classified intent"""
    
    base_url = "http://127.0.0.1:5001/ecostory-b31b6/us-central1"  # For local emulator
    # base_url = "https://us-central1-ecostory-b31b6.cloudfunctions.net"  # For production
    
    try:
        # Transform data for the specific API
        api_data = {
            "content": original_data.get("text", original_data.get("content", "")),
            "chapterId": original_data.get("chapterId", ""),
            "chatId": original_data.get("chatId", "default_chat_id"),  # Add this
            "location": original_data.get("location", ""),
            "lat": original_data.get("lat", 0),
            "long": original_data.get("long", 0)
        }
        
        if intent == "search_image":
            url = f"{base_url}/searchImageFromDatabase"
            response = requests.post(url, json=api_data)
            
        elif intent == "search_audio":
            url = f"{base_url}/searchAudioFromDatabase"
            response = requests.post(url, json=api_data)
            
        elif intent == "search_video":
            url = f"{base_url}/searchVideoFromDatabase"
            response = requests.post(url, json=api_data)
        
        else:
            return {"error": "Unknown intent"}
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"API call failed with status {response.status_code}",
                "details": response.text,
                "sent_data": api_data
            }
            
    except Exception as e:
        return {"error": f"Error calling API: {str(e)}"}