from firebase_setup import get_project_b_firestore

db = get_project_b_firestore()

print("Listing magicWordUser documents...")
docs = db.collection("magicWordUser").stream()
found = False
target_id = "umzOUYMJt5hyCv4z1DgP_FwD0PzH918ebu9Y5tQty"

for doc in docs:
    if doc.id == target_id:
        found = True
        print("✅ FOUND TARGET ID!")
        print(doc.to_dict())
    elif target_id in doc.id or "umzOUY" in doc.id:
        print(f"⚠️ PARTIAL MATCH: {doc.id}")
        data = doc.to_dict()
        print(f"   chatId: {data.get('chatId')}")
        print(f"   chat_id: {data.get('chat_id')}")

if not found:
    print("❌ Target ID NOT found exactly.")
