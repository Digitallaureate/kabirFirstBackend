
import firebase_admin
from firebase_admin import firestore
from firebase_setup import get_project_b_firestore
import os

# Build paths to service account
# The user's env uses functions/ecostory-service-account.json based on logs
# But `firebase_setup` handles it.

try:
    db = get_project_b_firestore()
    print("✅ Connected to Firestore")
except Exception as e:
    print(f"❌ Failed to connect: {e}")
    exit(1)

# 1. List Monuments
print("\n--- Listing Monuments (serviceMonument) ---")
mon_ref = db.collection("serviceMonument")
mon_docs = list(mon_ref.limit(5).stream())

if not mon_docs:
    print("❌ No monuments found in 'serviceMonument'")
else:
    for doc in mon_docs:
        print(f"Monument ID: {doc.id}")
        data = doc.to_dict()
        print(f"  Data keys: {list(data.keys())}")
        print(f"  serviceAvilable: {data.get('serviceAvilable')}")
        
        # 2. Check for 'services' subcollection
        services_ref = doc.reference.collection("services")
        services_docs = list(services_ref.limit(5).stream())
        
        if services_docs:
            print(f"  ✅ Found 'services' subcollection with {len(services_docs)} docs")
            for s_doc in services_docs:
                print(f"    - Service ID: {s_doc.id}, Data: {s_doc.to_dict()}")
        else:
            print("  ⚠️ No docs in 'services' subcollection. Checking other potential subcollections...")
            # List collections is not always straightforward in client SDKs without recursive list, 
            # but we can try common names
            for name in ["service", "servicePackage", "packages", "items"]:
                ref = doc.reference.collection(name)
                if list(ref.limit(1).stream()):
                    print(f"    ✅ Found alternative subcollection: '{name}'")
                    
print("\n--- Listing Service Languages (serviceLanguage) ---")
lang_ref = db.collection("serviceLanguage")
lang_docs = list(lang_ref.limit(5).stream())
if not lang_docs:
    print("❌ No languages found in 'serviceLanguage'")
else:
    for doc in lang_docs:
        print(f"Language ID: {doc.id}, Data: {doc.to_dict()}")

