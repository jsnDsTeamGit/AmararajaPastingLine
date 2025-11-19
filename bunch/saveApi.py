import os
import sys
import uuid
import json
import time
import socket
from pathlib import Path
from datetime import datetime,timezone
from typing import Dict, List, Tuple
from headerCreation import CreateHeader
from utils import createSaveJson, PostApiCall
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========= CONFIG =========
WATCH_FOLDER = r"ApiData"   # single folder
saveUrl = "http://10.215.10.125:1001/ProcessRegistryEdgeSave"

POLL_INTERVAL_SEC = 0.5
API_WORKERS = 8
DELETE_WORKERS = 8
DEBUG_SAVE_JSON = True

IMAGE_EXT = ".jpg"
JSON_EXT = ".json"


_prev_sizes: Dict[str, Tuple[int, int]] = {}
LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "MultiplatePlateModel.log")

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

# ========= NET HELPERS =========
def is_online(timeout: float = 3.0) -> bool:
    targets = [("1.1.1.1", 53), ("8.8.8.8", 53), ("www.msftconnecttest.com", 80)]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False

def wait_for_network(initial_delay: float = 2.0, max_delay: float = 60.0) -> None:
    delay = initial_delay
    if is_online():
        return
    print("🌐 No internet connection detected. Waiting for network...")
    log("⚠️ No internet connection detected. Waiting for network...")
    while True:
        if is_online():
            print("✅ Network is back. Continuing...")
            log("✅ Network is back. Continuing...")
            return
        print(f"⚠️ Still offline. Retrying in {int(delay)}s...")
        log(f"⚠️ Still offline. Retrying in {int(delay)}s...")
        time.sleep(delay)
        delay = min(delay * 1.5, max_delay)

# ========= HELPERS =========
def _base_key(p: Path) -> str:
    return os.path.splitext(str(p))[0]

def scan_ready_pairs(folder: str, cache: Dict[str, Tuple[int, int]]) -> List[Tuple[Path, Path]]:
    ready = []
    now_seen: Dict[str, Tuple[int, int]] = {}
    try:
        with os.scandir(folder) as it:
            for e in it:
                if not e.is_file() or not e.name.lower().endswith(IMAGE_EXT):
                    continue

                img_path = Path(e.path)
                json_path = Path(os.path.splitext(e.path)[0] + JSON_EXT)
                if not json_path.exists():
                    continue

                try:
                    st_img = e.stat(follow_symlinks=False)
                    st_json = os.stat(json_path)
                except FileNotFoundError:
                    continue

                key = _base_key(img_path)
                pair_size = (st_img.st_size, st_json.st_size)

                prev = cache.get(key)
                if prev is not None and prev == pair_size and pair_size[0] > 0 and pair_size[1] > 0:
                    ready.append((img_path, json_path))
                now_seen[key] = pair_size
    except FileNotFoundError:
        os.makedirs(folder, exist_ok=True)

    cache.clear()
    cache.update(now_seen)
    return ready

def delete_pair(img: Path, js: Path, cache: Dict[str, Tuple[int, int]]) -> None:
    for p in (img, js):
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            log(f"⚠️ Could not delete {p}: {e}")
    cache.pop(_base_key(img), None)

def process_image(img_path: Path) -> bool:
    SaveJson = createSaveJson(str(img_path))
    header = CreateHeader(str(uuid.uuid4()))
    header["Site-Id"] = SaveJson["serviceDetails"]["configDetails"]["siteId"]

    if DEBUG_SAVE_JSON:
        try:
            with open("save.json", "w") as f:
                json.dump(SaveJson, f, indent=2)
        except Exception as e:
            log(f"⚠️ Could not write debug save.json: {e}")

    try:
        saveStatus, errorValue = PostApiCall(saveUrl, header=header, data=SaveJson)
    except Exception as e:
        log(f"❌ Error in PostApiCall: {e}")
        return False
    return bool(saveStatus)

# ========= MAIN LOOP =========
def run_once(api_pool, del_pool):
    pairs = scan_ready_pairs(WATCH_FOLDER, _prev_sizes)
    if not pairs:
        return

    if not is_online():
        wait_for_network()

    futures = {api_pool.submit(process_image, img): (img, js) for img, js in pairs}
    for fut in as_completed(futures):
        img, js = futures[fut]
        ok = False
        try:
            ok = fut.result()
        except Exception as e:
            log(f"❌ API worker error for {img}: {e}")
        if ok:
            del_pool.submit(delete_pair, img, js, _prev_sizes)

def SaveMain():
    os.makedirs(WATCH_FOLDER, exist_ok=True)

    import pyfiglet
    print(pyfiglet.figlet_format("BUNCH START RUNNING"))
    print("DO NOT CLOSE THIS WINDOW!...")
    print("===================================")

    with ThreadPoolExecutor(max_workers=API_WORKERS) as api_pool, \
         ThreadPoolExecutor(max_workers=DELETE_WORKERS) as del_pool:
        while True:
            try:
                run_once(api_pool, del_pool)
            except Exception as e:
                log(f"❌ Main loop error: {e}")
            time.sleep(POLL_INTERVAL_SEC)

