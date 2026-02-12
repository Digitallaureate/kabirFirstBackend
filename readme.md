# EcoStory Firebase Project (Initial Project)

This repository contains the Firebase Cloud Functions and associated scripts for the EcoStory backend.

## 🚀 **Quick Reference: Deployment**

**BEFORE DEPLOYING:**
1.  Check which project you are using: `firebase projects:list`
2.  Switch to the correct project: `firebase use ecostory-b31b6` (or `ecostory-site`)

### **Deploy Specific Functions**
Use these commands to deploy only the function you changed (safer & faster).

```powershell
# Deploy the Magic Word / Message Listener (Main Logic)
firebase deploy --only functions:on_message_created

# Deploy the Admin Panel / Customer Service App
firebase deploy --only functions:customerService_app

# Deploy Chat Suggestion Data
firebase deploy --only functions:chatSuggestionData

# Deploy Process Text (Cloud Run / Function)
firebase deploy --only functions:process_text
```

### **Deploy ALL Functions**
⚠️ **Warning:** This deploys everything. Only use if initial setup.
```powershell
firebase deploy --only functions
```

---

## 🛠️ **Project Setup**

### 1. Python Environment (Windows)
```powershell
# Create virtual environment (if not exists)
python -m venv venv

# Activate virtual environment
.\venv\Scripts\activate

# Install dependencies
pip install -r functions/requirements.txt
```

### 2. Firebase Login
```powershell
# Login to your Google account
firebase login

# List your projects
firebase projects:list

# Select active project
firebase use ecostory-b31b6
```

---

## 📊 **Data Management Scripts**
Commands for managing `historical_sites` / `knowledge_base` data using `exportChapterData.py`.

**Note:** Run these from the project root (`c:\python_project\initial_project`).

### **Import / Export**
```powershell
# Import from Excel
python functions\exportChapterData.py import --file "import_test5.xlsx" --chapter-id "taj-mahal1"

# Export to Excel/CSV
python functions\exportChapterData.py export --chapter-id "taj-mahal1"
```

### **Search & Vector DB**
```powershell
# Test Semantic Search
python functions\exportChapterData.py search --query "Taj Mahal architecture" --chapter-id "taj-mahal1"
```

### **Manage Records**
```powershell
# List all records for a chapter
python functions\exportChapterData.py list --chapter-id "taj-mahal1"

# Delete ALL records for a chapter (DANGER!)
python functions\exportChapterData.py delete-all --chapter-id "taj-mahal1"

# Delete single record by ID
python functions\exportChapterData.py delete --record-id "taj-mahal1::0"

# Get a specific record details
python functions\exportChapterData.py get --record-id "taj-mahal1::0"
```

---

## 🔍 **Monitoring & Debugging**

### **View Logs**
```powershell
# View logs for a specific function
firebase functions:log --only on_message_created
```

### **Verify Code Version**
Look for `[INITIAL_PROJECT]` in the logs to confirm the correct code is running.

```powershell
# Example log output:
# W 2024-02-09T12:00:00.000Z on_message_created 🚀 [INITIAL_PROJECT] 🔔 New message created...
```
