import logging
import os
from supabase import create_client, Client
from dotenv import load_dotenv
from google.cloud import storage
from google.oauth2 import service_account

# Load environment variables
load_dotenv()

# --- Logging ---
logger = logging.getLogger("dashboard")
logger.setLevel(logging.INFO)

# --- Supabase setup ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# --- Google Cloud Storage setup ---
credentials = service_account.Credentials.from_service_account_file(
    "./credentials.json"
)
client = storage.Client(credentials=credentials, project=credentials.project_id)
bucket = client.bucket("secret-api")


# --- GCS Helper Functions ---

def upload_to_gcs(file_stream, folder: str, filename: str):
    """
    Upload a file stream to Google Cloud Storage.
    """
    try:
        blob_path = f"{folder}/{filename}".strip("/")
        blob = bucket.blob(blob_path)
        blob.upload_from_file(file_stream, content_type="image/jpeg")
        blob.make_public()  # Optional — make files publicly accessible
        logger.info(f"✅ Uploaded {filename} to GCS at {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"❌ Failed to upload to GCS: {e}")
        raise


def delete_from_gcs(filepath: str):
    """
    Delete a file from Google Cloud Storage.
    """
    try:
        blob_path = filepath.strip("/")
        blob = bucket.blob(blob_path)
        blob.delete()
        logger.info(f"🗑️ Deleted {blob_path} from GCS")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete from GCS: {e}")
        return False


def create_gcs_folder(folder_path: str):
    """
    Create a logical folder in GCS (optional, just creates a placeholder).
    """
    try:
        blob = bucket.blob(f"{folder_path.strip('/')}/.placeholder")
        blob.upload_from_string("")
        logger.info(f"📁 Created folder placeholder at {folder_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create folder: {e}")
        return False
