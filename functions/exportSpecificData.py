"""
extract_eateries.py
--------------------
Reads YouTube video transcripts from 'all_transcripts.csv',
uses OpenAI GPT to extract all mentioned eateries/restaurants,
and saves the results to 'eateries_result.xlsx'.

Setup: make sure OPENAI_API_KEY is set in your .env.dev file.
"""

import os
import json
import time
import re
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi

# This file lives in functions/ — parent folder has the CSV and .env.dev
_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # → project root
load_dotenv(os.path.join(_base, ".env.dev"))            # try root/.env.dev
load_dotenv(os.path.join(_base, "functions", ".env.dev"))  # try functions/.env.dev

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
INPUT_CSV    = os.path.join(_base, "all_transcripts.csv")  # → project root
OUTPUT_EXCEL = os.path.join(_base, "eateries_result.xlsx") # → project root
MODEL        = "gpt-4.1-mini"      # same model used across the project
# ─────────────────────────────────────────────

# OpenAI setup — key is read from .env.dev (OPENAI_API_KEY=sk-...)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


SYSTEM_PROMPT = """
You are a food and travel expert who understands ALL languages including Hindi,
Hinglish, Indonesian, Tamil, English, and any other language.

Your job is to extract every eatery, restaurant, dhaba, food stall, cafe, sweet shop,
or any food place mentioned in a YouTube video transcript, regardless of what
language the transcript is in.

IMPORTANT RULES:
- The transcript may be in Hindi, Hinglish, Indonesian, English, or any other language.
- Carefully read the ENTIRE transcript before deciding no eateries exist.
- Eatery names may be in any language/script. Transliterate them to English.
- Food item names should be translated to English where possible.
- Even indirect mentions like "we ate here" near a named place count as an eatery.
- If a place is mentioned multiple times, merge the details into one entry.
- ALWAYS write your output fields in English.

For each eatery found, return:
- name: name of the place in English (transliterate if needed)
- type: one of [Restaurant, Dhaba, Street Food, Cafe, Stall, Hotel, Bakery, Sweet Shop, Other]
- location: city or area if mentioned, else "Not specified"
- food_items: comma-separated list of food/dishes mentioned (translate to English)
- sentiment: overall tone — Positive / Negative / Neutral
- notable_quote: a short English summary of what was said about this place (max 20 words)

Respond ONLY with a valid JSON object with key "eateries" containing an array.
If truly no eatery is mentioned, return {"eateries": []}.
Example:
{
  "eateries": [
    {
      "name": "Sharma Ji Dhaba",
      "type": "Dhaba",
      "location": "Agra",
      "food_items": "chole bhature, lassi",
      "sentiment": "Positive",
      "notable_quote": "Best chole bhature in the whole of Agra"
    }
  ]
}
"""

def get_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    if not url or pd.isna(url):
        return None
    
    # Common patterns: v=ID, /v/ID, /shorts/ID, youtu.be/ID
    patterns = [
        r"(?:v=|\/v\/|shorts\/|youtu\.be\/|embed\/)([a-zA-Z0-9_-]{11})",
        r"^(?:[a-zA-Z0-9_-]{11})$" # already just an ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, str(url))
        if match:
            return match.group(1)
            
    return None

def fetch_youtube_transcript(video_id: str) -> str:
    """Fetch transcript from YouTube using youtube-transcript-api with robust fallback."""
    if not video_id:
        return ""
    
    try:
        # Get all available transcripts
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to find a transcript in prioritized languages
        # .find_transcript() handles both manual and auto-generated
        try:
            transcript = transcript_list.find_transcript(['hi', 'en', 'id'])
        except:
            # If not found, just take the first one available
            transcript = next(iter(transcript_list))
            
        data = transcript.fetch()
        return " ".join([entry['text'] for entry in data])
    except Exception as e:
        print(f"  ⚠ Could not fetch transcript for {video_id}: {e}")
        return ""

def extract_eateries_from_transcript(title: str, transcript: str) -> list[dict]:
    """Call OpenAI and return a list of eatery dicts for a single transcript."""
    transcript_str = str(transcript).strip()
    if not transcript_str or transcript_str.lower() == "nan":
        print(f"  ⚠ Skipping '{title}' — empty transcript")
        return []

    # Trim transcript to avoid token overload (keep first ~6000 chars ≈ ~1500 tokens)
    trimmed = transcript_str[:8000]  # Hindi text is denser, allow more chars

    user_message = f"""
Video Title: {title}

Transcript:
{trimmed}

Extract all eateries mentioned above and return them as a JSON array.
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.2,   # low temp = more consistent/factual output
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()

        # GPT returns a JSON object; we want the array inside it
        parsed = json.loads(raw)

        # Handle both {"eateries": [...]} and direct array responses
        if isinstance(parsed, list):
            eateries = parsed
        elif isinstance(parsed, dict):
            # find the first list value
            eateries = next((v for v in parsed.values() if isinstance(v, list)), [])
        else:
            eateries = []

        return eateries

    except json.JSONDecodeError as e:
        print(f"  ✗ JSON parse error for '{title}': {e}")
        return []
    except Exception as e:
        print(f"  ✗ API error for '{title}': {e}")
        return []


def main():
    # ── 1. Load CSV ──────────────────────────────────────────────────────────
    print(f"📂 Loading {INPUT_CSV} ...")
    df = pd.read_csv(INPUT_CSV, encoding='utf-8-sig')  # utf-8-sig handles BOM + Hindi/multilingual text
    print(f"   Found {len(df)} videos\n")

    all_rows = []

    # ── 2. Process each video ────────────────────────────────────────────────
    for idx, row in df.iterrows():
        title       = str(row.get("Title", f"Video {idx}"))
        video_url   = str(row.get("Video URL", ""))
        views       = row.get("Views", "")
        csv_transcript = str(row.get("Transcript", "")).strip()
        
        print(f"[{idx+1}/{len(df)}] Processing: {title[:60]}...")
        
        # Determine transcript source
        if csv_transcript and len(csv_transcript) > 100 and csv_transcript.lower() != "nan":
            print(f"   📄 Using existing transcript from CSV ({len(csv_transcript)} chars)...")
            transcript = csv_transcript
        else:
            # Fallback: Fresh fetch from YouTube
            video_id = get_video_id(video_url)
            if video_id:
                print(f"   🎥 Fetching fresh transcript for {video_id}...")
                transcript = fetch_youtube_transcript(video_id)
            else:
                print("   ⚠ No transcript in CSV and could not extract Video ID from URL.")
                continue

        if not transcript or len(transcript.strip()) < 50:
            print(f"   ⚠ Transcript too short or missing ({len(transcript)} chars)")
            continue

        eateries = extract_eateries_from_transcript(title, transcript)

        if eateries:
            print(f"   ✓ Found {len(eateries)} eaterie(s)")
            for e in eateries:
                all_rows.append({
                    "Video Title"   : title,
                    "Video URL"     : video_url,
                    "Views"         : views,
                    "Eatery Name"   : e.get("name", ""),
                    "Type"          : e.get("type", ""),
                    "Location"      : e.get("location", ""),
                    "Food Items"    : e.get("food_items", ""),
                    "Sentiment"     : e.get("sentiment", ""),
                    "Notable Quote" : e.get("notable_quote", ""),
                })
        else:
            print(f"   — No eateries found")

        # Small delay to avoid hitting rate limits
        time.sleep(0.5)

    # ── 3. Save results ──────────────────────────────────────────────────────
    if all_rows:
        result_df = pd.DataFrame(all_rows)
        
        save_path = OUTPUT_EXCEL
        attempt = 1
        while attempt < 10:
            try:
                with pd.ExcelWriter(save_path, engine="openpyxl") as writer:
                    # Sheet 1 — All eateries
                    result_df.to_excel(writer, sheet_name="All Eateries", index=False)

                    # Sheet 2 — Summary
                    summary = (
                        result_df.groupby("Eatery Name")
                        .agg(
                            Mentioned_In_Videos=("Video Title", "nunique"),
                            Types=("Type", lambda x: ", ".join(x.unique())),
                            Locations=("Location", lambda x: ", ".join(x.unique())),
                            Avg_Sentiment=("Sentiment", lambda x: x.mode()[0] if len(x) > 0 else ""),
                        )
                        .sort_values("Mentioned_In_Videos", ascending=False)
                        .reset_index()
                    )
                    summary.to_excel(writer, sheet_name="Summary", index=False)
                
                print(f"\n✅ Done! Results saved to '{save_path}'")
                break
            except PermissionError:
                save_path = OUTPUT_EXCEL.replace(".xlsx", f"_v{attempt+1}.xlsx")
                print(f"   ⚠ Permission denied for result file. Trying {save_path}...")
                attempt += 1
        
        print(f"   Total eateries extracted : {len(result_df)}")
        print(f"   Unique eateries          : {result_df['Eatery Name'].nunique()}")
        print(f"   Videos with eateries     : {result_df['Video Title'].nunique()}")
    else:
        print("\n⚠ No eateries found across all transcripts.")


if __name__ == "__main__":
    main()
