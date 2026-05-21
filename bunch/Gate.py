import os
import sys
import uuid
import time
import json
import ChangeDir
import threading
from datetime import datetime,timezone
from crytoGraphy import decrypt
from CaptureCam1 import startCam
from saveApi import SaveMain
from WatcherFile import watch_folder
from ModelBrain import start_pipeline
from blobConnect import download_blob
from headerCreation import CreateHeader
from utils import PostApiCall, restart_program

def delete_json_and_images(base_folder):
    # Define common image extensions
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp"}

    for root, _, files in os.walk(base_folder):
        for file in files:
            file_path = os.path.join(root, file)
            _, ext = os.path.splitext(file)

            # Check for JSON or image files
            if ext.lower() == ".json" or ext.lower() in image_extensions:
                try:
                    os.remove(file_path)
                except Exception as e:
                    pass

delete_json_and_images("LineData")
# delete_json_and_images(r"ModelResults")
fetchUrl = "https://api.web.inspectionone.ai/ProcessRegistryEdgeFetch"
fetchApiData = {
    "commonDetails": {
    "lat": "",
    "long": "",
    "sourceId": "1",
    "sourceDetails": "Web",
    "languageToken": "en",
    "tenantId": "4c0161b2-26d5-4ec4-a84b-4a357aa01c3f",
    "siteId": "577836e8-50ab-4356-a1ba-2e2f115b5e7c",
    "siteUserId": "eb98d343-ff39-457c-bf78-ba0f361aacd5",
    "Master-Access-Id": "",
    "roleId": "3"
},
    "serviceDetails": {
        "deviceId": "xoa9mot9md",
        "cameraId": "xoa9mot9md"
    }
}

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "MultiplatePlateModel.log")

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

with open("configData.json", "r") as f:
    localConfig = json.load(f)
localConfigDetails = localConfig.get("responseResult", {}).get("configDetails", {})
localVersion = localConfigDetails.get("version", "")

header = CreateHeader(str(uuid.uuid4()))
header["Site-Id"] = ""
configJsonStatus, configJsonData = PostApiCall(fetchUrl, header=header, data=fetchApiData)
if not configJsonStatus:
    log(f"❌ Failed to fetch config: {configJsonData}")
    time.sleep(5)
    sys.exit(1)
if configJsonData.get("responseCode", "400") != "200":
    log(f"❌ Invalid response code: {configJsonData.get('responseCode', 'N/A')}")
    time.sleep(5)
    sys.exit(1)
with open("configData.json", "w") as f:
    json.dump(configJsonData, f, indent=4)
jsonConfigDetails = configJsonData.get("responseResult", {}).get("configDetails", {})
jsonVersion = jsonConfigDetails.get("version", "")

encryptedContainerName = jsonConfigDetails.get("containerName", "")
encryptedConnectString = jsonConfigDetails.get("connectionString", "")

decrytedStatus, containerName = decrypt(encryptedContainerName)
decrytedStatus, connectString = decrypt(encryptedConnectString)

if not decrytedStatus:
    log(f"❌ Decryption failed for container or connection string")
    time.sleep(5)
    sys.exit(1)

if localVersion != jsonVersion:
    print(f"🔄 New version detected: {localVersion} → {jsonVersion}")
    magicId = jsonConfigDetails.get("magicId", "")
    iterationId = jsonConfigDetails.get("currentIteration", 1)
    blobPath = f"{magicId}/Iteration{iterationId}/model.pt"
    localPath = "model.pt"
    modelStatus = download_blob(connectString, containerName, blobPath, localPath)
    if not modelStatus:
        log("❌ Model download failed")
        time.sleep(5)
        sys.exit(1)
    restart_program()

if __name__ == "__main__":
    threads = [
        threading.Thread(target=SaveMain, name="SaveApi", daemon=False),
        threading.Thread(target=watch_folder, name="Watcher", daemon=False),
        threading.Thread(target=startCam, name="Cam1", daemon=False),
        threading.Thread(target=start_pipeline, name="ModelProcess", daemon=False),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
