# pinecone_setup.py
import os
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv(".env.dev")

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_HOST = os.getenv("PINECONE_INDEX_HOST")

if not PINECONE_INDEX_HOST:
    raise EnvironmentError("Missing PINECONE_INDEX_HOST for serverless Pinecone setup")

pc = Pinecone(api_key=PINECONE_API_KEY)
