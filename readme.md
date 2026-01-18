// 
# Import from Excel
python functions\exportChapterData.py import --file "import_test5.xlsx" --chapter-id "taj-mahal1"

# Export to Excel/CSV
python functions\exportChapterData.py export --chapter-id "taj-mahal1"

# Search with semantic search
python functions\exportChapterData.py search --query "Taj Mahal architecture" --chapter-id "taj-mahal1"

# List all records
python functions\exportChapterData.py list --chapter-id "taj-mahal1"

# Delete all records for a chapter
python functions\exportChapterData.py delete-all --chapter-id "taj-mahal1"

# Delete single record
python functions\exportChapterData.py delete --record-id "taj-mahal1::0"

# Get a specific record by ID
python functions\exportChapterData.py get --record-id "taj-mahal1::0"



