# export_chapter_to_excel.py
import os
import json
import argparse
import pandas as pd
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI

# Load .env.dev from the same directory as this script
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, ".env.dev")
load_dotenv(env_path)

def zero_vector(dim: int):
    return [0.0] * dim

def flatten_match(m: dict) -> dict:
    md = m.get("metadata") or {}
    return {
        "id": m.get("id", ""),
        "score": m.get("score", ""),
        "chapterId": md.get("chapterId", ""),
        "text": md.get("text", ""),
        "imageDesc": md.get("imageDesc", ""),
        "imageURL": md.get("imageURL", ""),
        "metadata_json": json.dumps(md, ensure_ascii=False),
    }

def export_chapter_data(args):
    """Export chapter data to Excel/CSV"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("KABIR_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("Missing Pinecone environment variables.")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"🔍 Fetching records for chapterId='{args.chapter_id}'...")

    resp = index.query(
        vector=zero_vector(args.dim),
        top_k=args.top_k,
        include_metadata=True,
        filter={"chapterId": args.chapter_id},
    )

    matches = resp.get("matches", [])
    rows = [flatten_match(m) for m in matches]
    df = pd.DataFrame(rows)

    csv_name = f"export_{args.chapter_id}.csv"
    xlsx_name = f"export_{args.chapter_id}.xlsx"
    df.to_csv(csv_name, index=False, encoding="utf-8")
    df.to_excel(xlsx_name, index=False)

    print(f"✅ Export complete! Wrote {len(df)} rows:")
    print(f"   - {csv_name}")
    print(f"   - {xlsx_name}")

def generate_embedding(text: str) -> list:
    """Generate embedding using OpenAI"""
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        print("⚠️ Warning: Missing OPENAI_API_KEY, using zero vector")
        return [0.0] * 1536
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.embeddings.create(
            input=text,
            model="text-embedding-ada-002"
        )
        embedding = response.data[0].embedding
        print(f"   ✅ Generated embedding with {len(embedding)} dimensions")
        return embedding
    except Exception as e:
        print(f"⚠️ Error generating embedding: {e}")
        print(f"   Using zero vector instead")
        return [0.0] * 1536

def import_from_excel(args):
    """Import data from Excel file to Pinecone"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("KABIR_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("❌ Missing Pinecone environment variables.")
    
    if not OPENAI_API_KEY:
        print("⚠️ WARNING: OPENAI_API_KEY not found! Will use zero vectors (no semantic search)")
        use_embeddings = False
    else:
        print(f"✅ OpenAI API Key found: {OPENAI_API_KEY[:8]}...")
        use_embeddings = True

    # Read Excel file
    if not os.path.exists(args.file):
        raise SystemExit(f"❌ File not found: {args.file}")
    
    print(f"📖 Reading Excel file: {args.file}")
    df = pd.read_excel(args.file)
    
    # Check required column (case-insensitive)
    text_column = None
    for col in df.columns:
        if col.lower() == 'text':
            text_column = col
            break
    
    if text_column is None:
        raise SystemExit(f"❌ Excel file must have a 'text' or 'Text' column. Found columns: {list(df.columns)}")
    
    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)
    
    print(f"📊 Found {len(df)} rows to import")
    print(f"🎯 Target Chapter ID: {args.chapter_id}")
    
    vectors_to_upsert = []
    success_count = 0
    error_count = 0
    
    for idx, row in df.iterrows():
        text = str(row[text_column]).strip()
        
        if not text or text == 'nan':
            print(f"⚠️ Skipping row {idx + 1}: Empty text")
            error_count += 1
            continue
        
        # Generate unique ID (like test4::0, test4::1, etc.)
        record_id = f"{args.chapter_id}::{idx}"
        
        # Generate embedding using OpenAI
        print(f"🔄 Processing {idx + 1}/{len(df)}: {text[:50]}...")
        
        if use_embeddings:
            embedding = generate_embedding(text)
            if embedding is None:
                error_count += 1
                continue
        else:
            embedding = [0.0] * 1536
        
        # Get current timestamp
        from datetime import datetime
        created_at = datetime.utcnow().isoformat() + "Z"
        
        # Prepare metadata
        metadata = {
            "chapterId": args.chapter_id,
            "text": text,
            "imageDesc": "",
            "imageURL": "",
            "createdAt": created_at,
        }
        
        vectors_to_upsert.append({
            "id": record_id,
            "values": embedding,
            "metadata": metadata
        })
        
        success_count += 1
        
        # Batch upsert every 100 records
        if len(vectors_to_upsert) >= 100:
            index.upsert(vectors=vectors_to_upsert)
            print(f"✅ Uploaded batch of {len(vectors_to_upsert)} records")
            vectors_to_upsert = []
    
    # Upload remaining records
    if vectors_to_upsert:
        index.upsert(vectors=vectors_to_upsert)
        print(f"✅ Uploaded final batch of {len(vectors_to_upsert)} records")
    
    print(f"\n🎉 Import complete!")
    print(f"   ✅ Success: {success_count} records")
    print(f"   ❌ Errors: {error_count} records")
    if not use_embeddings:
        print(f"   ⚠️ WARNING: Used zero vectors - semantic search won't work!")

def delete_record(args):
    """Delete a specific record by ID"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("PINECONE_INDEX_HOST")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("Missing Pinecone environment variables.")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"🗑️ Deleting record with ID='{args.record_id}'...")
    
    try:
        # Delete the record
        index.delete(ids=[args.record_id])
        print(f"✅ Successfully deleted record: {args.record_id}")
    except Exception as e:
        print(f"❌ Error deleting record: {e}")

def delete_all_records(args):
    """Delete all records for a chapter"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("KABIR_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("Missing Pinecone environment variables.")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"🔍 Finding all records for chapterId='{args.chapter_id}'...")
    
    # Query to get all record IDs
    resp = index.query(
        vector=zero_vector(1536),
        top_k=10000,
        include_metadata=True,
        filter={"chapterId": args.chapter_id},
    )
    
    matches = resp.get("matches", [])
    record_ids = [m["id"] for m in matches]
    
    if not record_ids:
        print(f"❌ No records found for chapterId='{args.chapter_id}'")
        return
    
    print(f"🗑️ Found {len(record_ids)} records to delete")
    print(f"   Record IDs: {record_ids[:5]}{'...' if len(record_ids) > 5 else ''}")
    
    # Confirm deletion
    confirm = input(f"\n⚠️ Delete all {len(record_ids)} records? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Deletion cancelled")
        return
    
    # Delete in batches of 1000 (Pinecone's limit)
    batch_size = 1000
    total_deleted = 0
    
    try:
        for i in range(0, len(record_ids), batch_size):
            batch = record_ids[i:i + batch_size]
            index.delete(ids=batch)
            total_deleted += len(batch)
            print(f"✅ Deleted batch {i//batch_size + 1}: {len(batch)} records (Total: {total_deleted}/{len(record_ids)})")
        
        print(f"\n🎉 Successfully deleted all {total_deleted} records!")
    except Exception as e:
        print(f"❌ Error deleting records: {e}")
        print(f"   Deleted {total_deleted} out of {len(record_ids)} records before error")

def list_records(args):
    """List all records for a chapter with their IDs"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("Missing Pinecone environment variables.")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"📋 Listing records for chapterId='{args.chapter_id}'...")

    resp = index.query(
        vector=zero_vector(args.dim),
        top_k=args.top_k,
        include_metadata=True,
        filter={"chapterId": args.chapter_id},
    )

    matches = resp.get("matches", [])
    
    if not matches:
        print(f"No records found for chapterId='{args.chapter_id}'")
        return
    
    print(f"\nFound {len(matches)} records:")
    print("-" * 80)
    for i, match in enumerate(matches, 1):
        md = match.get("metadata", {})
        print(f"{i}. ID: {match['id']}")
        print(f"   Score: {match.get('score', 'N/A')}")
        print(f"   Description: {md.get('imageDesc', md.get('text', 'No description'))[:60]}...")
        print("-" * 80)

def search_records(args):
    """Search records using semantic search"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("KABIR_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("Missing Pinecone environment variables.")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"🔍 Searching for: '{args.query}'")
    
    # Generate embedding for the search query
    query_embedding = generate_embedding(args.query)
    
    if query_embedding is None:
        raise SystemExit("❌ Failed to generate embedding for query")
    
    # Perform semantic search
    resp = index.query(
        vector=query_embedding,
        top_k=args.top_k,
        include_metadata=True,
        filter={"chapterId": args.chapter_id} if args.chapter_id else None,
    )
    
    matches = resp.get("matches", [])
    
    if not matches:
        print("No results found")
        return
    
    print(f"\n✅ Found {len(matches)} results:")
    print("=" * 80)
    for i, match in enumerate(matches, 1):
        md = match.get("metadata", {})
        score = match.get("score", 0)
        print(f"{i}. Score: {score:.4f} | ID: {match['id']}")
        print(f"   Text: {md.get('text', '')[:150]}...")
        print("-" * 80)

def add_single_record(args):
    """Add a single record to Pinecone"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("KABIR_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("❌ Missing Pinecone environment variables.")

    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"➕ Adding new record to chapter: {args.chapter_id}")
    
    # Generate embedding
    if OPENAI_API_KEY:
        print(f"🔄 Generating embedding for text: {args.text[:50]}...")
        embedding = generate_embedding(args.text)
        if embedding is None:
            raise SystemExit("❌ Failed to generate embedding")
    else:
        print("⚠️ WARNING: Using zero vector (no OpenAI API key)")
        embedding = [0.0] * 1536
    
    # Generate unique ID
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    record_id = args.record_id if args.record_id else f"{args.chapter_id}::{timestamp}"
    
    # Get current timestamp
    created_at = datetime.utcnow().isoformat() + "Z"
    
    # Prepare metadata
    metadata = {
        "chapterId": args.chapter_id,
        "text": args.text,
        "imageDesc": args.image_desc or "",
        "imageURL": args.image_url or "",
        "createdAt": created_at,
    }
    
    # Upsert the record
    try:
        index.upsert(
            vectors=[{
                "id": record_id,
                "values": embedding,
                "metadata": metadata
            }]
        )
        print(f"\n✅ Successfully added record!")
        print(f"   ID: {record_id}")
        print(f"   Chapter: {args.chapter_id}")
        print(f"   Text: {args.text[:100]}...")
        print(f"   Created At: {created_at}")
    except Exception as e:
        print(f"❌ Error adding record: {e}")

def get_record(args):
    """Get a specific record by ID"""
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("KABIR_INDEX_NAME")
    PINECONE_INDEX_HOST = os.getenv("KABIR_INDEX_HOST")

    if not all([PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_INDEX_HOST]):
        raise SystemExit("❌ Missing Pinecone environment variables.")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(name=PINECONE_INDEX_NAME, host=PINECONE_INDEX_HOST)

    print(f"🔍 Fetching record with ID: '{args.record_id}'...")
    
    try:
        # Fetch the record
        result = index.fetch(ids=[args.record_id])
        
        if not result or 'vectors' not in result or not result['vectors']:
            print(f"❌ Record not found: {args.record_id}")
            return
        
        vector_data = result['vectors'].get(args.record_id)
        if not vector_data:
            print(f"❌ Record not found: {args.record_id}")
            return
        
        metadata = vector_data.get('metadata', {})
        
        print(f"\n✅ Record found!")
        print("=" * 80)
        print(f"ID: {args.record_id}")
        print(f"Chapter ID: {metadata.get('chapterId', 'N/A')}")
        print(f"Created At: {metadata.get('createdAt', 'N/A')}")
        print(f"\nText:\n{metadata.get('text', 'N/A')}")
        print(f"\nImage Description: {metadata.get('imageDesc', 'N/A')}")
        print(f"Image URL: {metadata.get('imageURL', 'N/A')}")
        print("=" * 80)
        
        # Optionally save to file
        if args.output:
            output_data = {
                "id": args.record_id,
                "metadata": metadata
            }
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Saved to: {args.output}")
            
    except Exception as e:
        print(f"❌ Error fetching record: {e}")

def main():
    parser = argparse.ArgumentParser(description="Pinecone Chapter Data Management")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Export command
    export_parser = subparsers.add_parser('export', help='Export chapter data to Excel/CSV')
    export_parser.add_argument("--chapter-id", required=True, help="Chapter ID to export")
    export_parser.add_argument("--dim", type=int, default=1536, help="Vector dimension")
    export_parser.add_argument("--top-k", type=int, default=5000, help="Max records to fetch")

    # Import command
    import_parser = subparsers.add_parser('import', help='Import data from Excel file')
    import_parser.add_argument("--file", required=True, help="Path to Excel file")
    import_parser.add_argument("--chapter-id", required=True, help="Chapter ID for all records")

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a single record')
    add_parser.add_argument("--chapter-id", required=True, help="Chapter ID")
    add_parser.add_argument("--text", required=True, help="Text content")
    add_parser.add_argument("--record-id", help="Custom record ID (optional, auto-generated if not provided)")
    add_parser.add_argument("--image-desc", help="Image description (optional)")
    add_parser.add_argument("--image-url", help="Image URL (optional)")

    # Get command (NEW)
    get_parser = subparsers.add_parser('get', help='Get a specific record by ID')
    get_parser.add_argument("--record-id", required=True, help="Record ID to fetch")
    get_parser.add_argument("--output", help="Save to JSON file (optional)")

    # Search command
    search_parser = subparsers.add_parser('search', help='Semantic search in records')
    search_parser.add_argument("--query", required=True, help="Search query text")
    search_parser.add_argument("--chapter-id", help="Filter by chapter ID (optional)")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of results")

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a specific record')
    delete_parser.add_argument("--record-id", required=True, help="Record ID to delete")

    # Delete all command
    delete_all_parser = subparsers.add_parser('delete-all', help='Delete all records for a chapter')
    delete_all_parser.add_argument("--chapter-id", required=True, help="Chapter ID to delete all records")

    # List command
    list_parser = subparsers.add_parser('list', help='List all records for a chapter')
    list_parser.add_argument("--chapter-id", required=True, help="Chapter ID to list")
    list_parser.add_argument("--dim", type=int, default=1536, help="Vector dimension")
    list_parser.add_argument("--top-k", type=int, default=5000, help="Max records to fetch")

    args = parser.parse_args()

    if args.command == 'export':
        export_chapter_data(args)
    elif args.command == 'import':
        import_from_excel(args)
    elif args.command == 'add':
        add_single_record(args)
    elif args.command == 'get':
        get_record(args)
    elif args.command == 'search':
        search_records(args)
    elif args.command == 'delete':
        delete_record(args)
    elif args.command == 'delete-all':
        delete_all_records(args)
    elif args.command == 'list':
        list_records(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
