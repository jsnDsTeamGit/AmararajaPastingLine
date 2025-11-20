import os
import sys
import json
import time
import requests
import pyodbc
from crytoGraphy import decrypt
from blobConnect import upload_blob
from datetime import datetime, timezone,timedelta

with open("configData.json","r") as f:
    localConfig = json.load(f)

commonDetails = {
        "lat": "",
        "long": "",
        "sourceId": "1",
        "sourceDetails": "Web",
        "languageToken": "en",
        "tenantId": localConfig.get("responseResult","").get("configDetails","").get("tenantId",""),
        "siteId": localConfig.get("responseResult","").get("configDetails","").get("tenantId",""),
        "siteUserId": localConfig.get("responseResult","").get("configDetails","").get("tenantId",""),
        "Master-Access-Id": "",
        "roleId": "2"
    }
resultInValue = {
    "Pass": 1,
    "Fail": 2,
    "Negative": 3
}

jsonConfigDetails = localConfig.get("responseResult", {}).get("configDetails", {})
encryptedContainerName = jsonConfigDetails.get("containerName", "")
encryptedConnectString = jsonConfigDetails.get("connectionString", "")

decrytedStatus, containerName = decrypt(encryptedContainerName)
decrytedStatus, connectString = decrypt(encryptedConnectString)

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "MultiplatePlateModel.log")

Api_LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "ApiCalledBunchLog.log")
def apilog(msg: str):
    try:
        with open(Api_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def PostApiCall(url,header, data=None, timeout=50):
    try:
        apilog(url)
        response = requests.post(
            url,
            headers=header,
            json=data,
            timeout=timeout
        )
        response = response.json()
        if int(response.get("responseCode", 500)) != 200:
            return False, response
        return True, response
    except requests.exceptions.RequestException as e:
        return False, str(e)

def get_latest_plate_type(timestamp_str):
    try:
        # Parse the input UTC timestamp
        ts_utc = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.000Z")
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)

        # Convert UTC to local time (e.g., IST = UTC +5:30)
        ts_local = ts_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))

        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=10.120.0.129;"
            "DATABASE=AREML;"
            "UID=jsn;"
            "PWD=Test@123"
        )
        cursor = conn.cursor()

        query = """
            SELECT TOP 1 [Recipe]
            FROM [AREML].[dbo].[ABD2_BW2]
            WHERE [Datetime] <= ?
            ORDER BY [Datetime] DESC
        """

        # Use the converted local time
        cursor.execute(query, ts_local)
        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
            return row[0]
        else:
            return None

    except Exception as e:
        print(f"Database error: {e}")
        return None
      
def restart_program():
    try:
        python = sys.executable
        os.execl(python, python, *sys.argv)
        print("🔄 Restarting program...")
    except Exception as e:
        print(f"⚠️ Restart failed: {e}")
        sys.exit(1)

def get_iso_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def get_file_created_iso(path: str) -> str:
    # Get file creation time (in seconds since epoch)
    ts = os.path.getctime(path)
    # Convert to local datetime (no UTC)
    dt = datetime.fromtimestamp(ts,tz=timezone.utc)
    # Format as required
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def GetAnnotatedDetails(predictions):
    annotatedDetails = []
    for pred in predictions:
        name = pred.get("name", "")
        bbox = pred.get("box", {})
        x1,y1,x2,y2 = int(bbox.get("x1",0)),int(bbox.get("y1",0)),int(bbox.get("x2",0)),int(bbox.get("y2",0))
        coords = [{"x": x1, "y": y1}, {"x": x2, "y": y2}]
        annotatedDetails.append({
            "name": name,
            "type":1,
            "coordinates": coords,
            "startArea":pred.get("startPlate", 0),
            "endArea":pred.get("endPlate", 0)
        })
    return annotatedDetails

def createSaveJson(filepath):
    resultDetails = {}
    for i in range(3):
        blobStatus, blobUrl = upload_blob(connectString,containerName,filepath,filepath)
        blobUrl = blobUrl.replace("\\","/")
        if blobStatus:
            break
        if i == 2:
            print("Error in uploading result after 3 attempts")
            time.sleep(5)
            sys.exit(1)
    imgId = os.path.basename(filepath).split(".")[0]
    jsonPath = os.path.join(os.path.dirname(filepath),f"{imgId}.json")
    with open(jsonPath,"r") as f:
        imgData = json.load(f)
    with open("lastPlateType.json", "r") as f:
        plateTypeData = json.load(f)
    resultDetails["processId"] = imgData.get("processId","")
    resultDetails["id"] = imgId
    resultDetails["url"] = blobUrl
    resultDetails["resultId"] = resultInValue.get(imgData.get("status","Negative"),3)
    resultDetails["height"] = imgData.get("height",0)
    resultDetails["width"] = imgData.get("width",0)
    resultDetails["batchId"] = imgData["batchId"]
    resultDetails["batchCount"] = imgData["batchSize"]
    resultDetails["batchPassCount"] = imgData.get("batchPassCount",0)
    resultDetails["batchFailCount"] = imgData.get("batchFailCount",0)
    resultDetails["dateTime"] = get_file_created_iso(jsonPath)
    resultDetails["plateType"] = plateTypeData.get("plate_type", "Unknown")
    resultDetails["labelValue"] = {"annotatedDetails": GetAnnotatedDetails(imgData.get("predictionData",[]))}
    ApiJson = {
        "commonDetails":commonDetails,
        "serviceDetails":{"configDetails":jsonConfigDetails,"resultDetails":resultDetails}

    }
    return ApiJson



        

