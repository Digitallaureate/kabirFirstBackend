# test_trigger.py
from firebase_admin import credentials, firestore, initialize_app
import os
from dotenv import load_dotenv

load_dotenv("functions/.env.dev")

# Connect to emulator
os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8080"

# Initialize with Project B credentials
cred_path = os.getenv("FIREBASE_PROJECT_B_SERVICE_ACCOUNT_KEY")
cred = credentials.Certificate(cred_path)
app = initialize_app(cred)

db = firestore.client()

# Add test message
chat_id = "07d279b9-ad50-4458-9708-408f8e547b0d"
db.collection("chats").document(chat_id).collection("messages").add({
    "content": "Test from Python script",
    "role": "user",
    "location": "Delhi",
    "created_at": firestore.SERVER_TIMESTAMP
})

print("✅ Test message added! Check your emulator logs.")