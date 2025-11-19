import os
import sys
from datetime import datetime, timezone
from azure.storage.blob import BlobServiceClient

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "SinglePlateModel.log")

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass
def download_blob(connect_string: str, container_name: str, blob_path: str, local_path: str):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connect_string)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
        with open(local_path, "wb") as f:
            f.write(blob_client.download_blob().readall())
        return True
    except Exception as e:
        log(f"❌ Error: {e}")
        return False

def upload_blob(connect_string: str, container_name: str, blob_path: str, local_path: str, overwrite: bool = True):
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connect_string)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
        with open(local_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=overwrite)
        account_url = blob_service_client.url  # e.g. https://<account>.blob.core.windows.net
        blob_url = f"{account_url}{container_name}/{blob_path}"
        return True, blob_url
    except Exception as e:
        log(f"❌ Error: {e}")
        return False, None
    
