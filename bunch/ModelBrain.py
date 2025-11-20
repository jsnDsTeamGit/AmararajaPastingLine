import os
import cv2
import sys
import uuid
import time
import json
import threading
import numpy as np
from queue import Queue
from pathlib import Path
from datetime import datetime,timezone
from typing import List, Tuple
from ModelClass import YoloDetection

# -------------------- Existing config & folders --------------------
model = YoloDetection("model.pt", "yolo")

correctedAnnotations = { 
    'ROI':'ROI',
    'Plate Edge Damage':'Plate edge damage',
    'Wire Bend':'Wire Bend',
    'Excess Backing Paper':'Excess backing paper',
    'Flashes on Lug': 'Flashes on Lug',
    'Plate Bend':'Plate bend'
}
ResultFolder = r"ModelResults"
os.makedirs(ResultFolder, exist_ok=True)

SOURCE_DIR = r"LineData"
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

# Scan & stability settings
SCAN_INTERVAL_SEC = 0.20           # batch scans (slightly higher than 0.05 reduces overhead)
FILE_STABILITY_WAIT = 0.12
FILE_STABILITY_RETRIES = 8

# Concurrency / queue
QUEUE_MAXSIZE = 1024               # backpressure to avoid memory blowups
WORKERS = 2                        # IO+inference workers; keep small unless model is thread-safe

# -------------------- Your existing helpers (unchanged) --------------------
LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "MultiplatePlateModel.log")

def DamagedPlateCoords(detectedROIbbox, filteredDamages):
    results = []
    roiYmin = int(detectedROIbbox.get('y1'))
    roiYmax = int(detectedROIbbox.get('y2'))
    roiH = roiYmax - roiYmin
    if roiH <= 0:
        return results

    pxPerPlate = roiH / 50.0
    identifiedPlatesData = []
    for dmg in filteredDamages:
        dmgBox = dmg.get('box', {})
        dmgYmin = int(dmgBox.get('y1'))
        dmgYmax = int(dmgBox.get('y2'))

        dmgStartPlate = int((dmgYmin - roiYmin) / pxPerPlate)
        dmgEndPlate = int((dmgYmax - roiYmin) / pxPerPlate)
        dmg["startPlate"] = dmgStartPlate
        dmg["endPlate"] = dmgEndPlate
        identifiedPlatesData.append(dmg)
    return identifiedPlatesData

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def modelPredictor(model, image):
    try:
        prediction_dect = model.detectLabel(image)
        return True, prediction_dect
    except Exception as e:
        return False, str(e)

def BBoxCheck(outerBox, innerBox):
    outer = outerBox["box"]
    inner = innerBox["box"]

    # Midpoint of inner box
    midX = (inner["x1"] + inner["x2"]) / 2
    midY = (inner["y1"] + inner["y2"]) / 2

    # Define corners of inner box
    corners = [
        (inner["x1"], inner["y1"]),  # top-left
        (inner["x1"], inner["y2"]),  # bottom-left
        (inner["x2"], inner["y1"]),  # top-right
        (inner["x2"], inner["y2"]),  # bottom-right
    ]

    # Helper function to check point inside outer box
    def point_in_outer(x, y):
        return outer["x1"] <= x <= outer["x2"] and outer["y1"] <= y <= outer["y2"]

    # Check midpoint
    if point_in_outer(midX, midY):
        return True

    # Check corners
    for x, y in corners:
        if point_in_outer(x, y):
            return True

    return False

def MaxRoi(detectedRois):
    areaData = []
    for i in detectedRois:
        x1, y1, x2, y2 = i["box"].values()
        w, h = x2-x1, y2-y1
        areaData.append(w*h)
    return [detectedRois[np.argmax(areaData)]]

def AnalyseImage(image, processId):
    h, w = image.shape[:2]
    predictionStatus, predictionDect = modelPredictor(model, image)
    imgId = f"{uuid.uuid4()}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    if not predictionStatus:
        log(f"❌ Prediction failed for {processId}: {predictionDect}")
        return "Success"

    for detection in predictionDect:
        if detection['name'] in correctedAnnotations:
            detection['name'] = correctedAnnotations[detection['name']]

    detectedRois = [i for i in predictionDect if i['name'] == 'ROI']
    if not detectedRois:
        return "Success"

    detectedRois = MaxRoi(detectedRois)
    filteredDamages = [i for i in predictionDect if i['name'] not in ['ROI'] and BBoxCheck(detectedRois[0], i)]
    status = "Fail" if filteredDamages else "Pass"
    damagePlateCoords = []
    if filteredDamages:
        damagePlateCoords = DamagedPlateCoords(detectedRois[0]["box"], filteredDamages)
    damagePlateCoords.append(detectedRois[0])
    data = {
        "status": status,
        "height": h,
        "width": w,
        "processId": processId,
        "predictionData": damagePlateCoords,
    }
    filteredDamages.append(detectedRois[0])
    data = {"status": status, "height": h, "width": w, "processId": processId, "predictionData": filteredDamages}
    with open(os.path.join(ResultFolder, f"{imgId}.json"), "w") as f:
        json.dump(data, f, indent=4)
    imgSavePath = os.path.join(ResultFolder, f"{imgId}.jpg")
    cv2.imwrite(imgSavePath, image)
    return "Success"

def is_file_ready(path: Path,
                  wait: float = FILE_STABILITY_WAIT,
                  retries: int = FILE_STABILITY_RETRIES) -> bool:
    try:
        old_size = path.stat().st_size
    except FileNotFoundError:
        return False
    for _ in range(retries):
        time.sleep(wait)
        try:
            new_size = path.stat().st_size
        except FileNotFoundError:
            return False
        if new_size == old_size and new_size > 0:
            return True
        old_size = new_size
    return False

def delete_with_retries(path: Path, attempts: int = 5, wait: float = 0.05):
    for _ in range(attempts):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            time.sleep(wait)
        except OSError:
            time.sleep(wait)
    # last resort: mark as done to avoid reprocessing
    try:
        path.rename(path.with_suffix(path.suffix + ".done"))
    except Exception:
        pass
    return False

# -------------------- Faster pipeline --------------------
Task = Tuple[float, Path]          # (ctime, path)
scan_seen = set()                  # already enqueued paths (strings)
q_files: "Queue[Path]" = Queue(maxsize=QUEUE_MAXSIZE)

def imread_fast(path: Path):
    """Robust Windows-friendly read using fromfile + imdecode."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None

def watcher():
    src = Path(SOURCE_DIR)
    src.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            entries: List[Task] = []
            with os.scandir(src) as it:
                for e in it:
                    if not e.is_file():
                        continue
                    p = Path(e.path)
                    # skip marked-done or non-image
                    if p.suffix.lower() == ".done":
                        continue
                    if p.suffix.lower() not in EXTS:
                        continue
                    spath = str(p)
                    if spath in scan_seen:
                        continue
                    if not is_file_ready(p):
                        continue
                    try:
                        ctime = e.stat().st_ctime
                    except FileNotFoundError:
                        continue
                    entries.append((ctime, p))

            if entries:
                # oldest-first to honor "creation order" requirement
                entries.sort(key=lambda t: t[0])
                for _, p in entries:
                    scan_seen.add(str(p))
                    q_files.put(p)  # blocks if full (backpressure)

            time.sleep(SCAN_INTERVAL_SEC)
        except Exception as ex:
            log(f"❌ Watcher error: {ex}")
            time.sleep(0.5)

def worker(idx: int):
    while True:
        path = q_files.get()
        try:
            img = imread_fast(path)
            if img is None:
                delete_with_retries(path)
                continue
            imName = os.path.splitext(os.path.basename(path))[0]
            proc_id = imName.split("__")[-1]
            ok = False
            try:
                ok = bool(AnalyseImage(img, proc_id))
            except Exception as e:
                log(f"❌ Worker-{idx} processing error for {path.name}: {e}")
                ok = False
            if ok:
                if not delete_with_retries(path):
                    log(f"⚠️ Worker-{idx} could not delete {path}")
        finally:
            q_files.task_done()

def start_pipeline():
    for i in range(WORKERS):
        threading.Thread(target=worker, args=(i,), name=f"Worker-{i+1}", daemon=False).start()
    threading.Thread(target=watcher, name="Watcher", daemon=False).start()

# -------------------- Boot --------------------
# start_pipeline()