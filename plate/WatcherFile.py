import os
import sys
import time
import json
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from utils import get_latest_plate_type_with_timeout,get_file_created_iso
import random
import traceback

WATCH_FOLDER = r"ModelResults"
OUTPUT_FOLDER = r"ApiData"
BATCH_SIZE = 500

batch_no = 0  # global batch counter

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "SinglePlateModel.log")

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}]{msg}\n")
    except Exception:
        pass

def compute_scaled_sampling(
    N_base=441000, T_base=9350,
    N_new=None, pass_frac=0.60, k=4, round_counts=True
):
    if N_new is None:
        N_new = N_base

    r = T_base / N_base
    T_new = r * N_new

    a = pass_frac
    b = 1.0 - a

    denom = N_new * (a + b * k)
    if denom == 0:
        raise ValueError("Denominator zero: check pass_frac and k")

    p = T_new / denom
    f = k * p

    pass_count = N_new * a * p
    fail_count = N_new * b * f
    total_count = pass_count + fail_count

    if round_counts:
        pass_count = int(round(pass_count))
        fail_count = int(round(fail_count))
        total_count = pass_count + fail_count

    return {
        "baseline_fraction_r": r,
        "new_target_T_new": T_new,
        "p_decimal": p,
        "f_decimal": f,
        "p_percent": p * 100,
        "f_percent": f * 100,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "total_count": total_count,
        "feasible": (p <= 1.0 and f <= 1.0)
    }

def get_pass_fail_counts(folder):
    pass_count, fail_count = 0, 0
    continuous_fail_active = False
    json_files = [f for f in os.listdir(folder) if f.endswith(".json")]
    for jf in json_files:
        try:
            with open(os.path.join(folder, jf), "r") as f:
                data = json.load(f)
                if data.get("status", "").lower() == "pass":
                    pass_count += 1
                else:
                    fail_count += 1
                if data.get("continuousFailFlag", False):
                    continuous_fail_active = True
        except:
            print(f)
            continue
    total = pass_count + fail_count
    pass_frac = pass_count / total if total > 0 else 0
    fail_frac = fail_count / total if total > 0 else 0
    return pass_count, fail_count, pass_frac, fail_frac, continuous_fail_active

def move_selected_files(files, dest_folder):
    os.makedirs(dest_folder, exist_ok=True)
    for f in files:
        shutil.move(f, os.path.join(dest_folder, os.path.basename(f)))

def process_batch(batch_folder, output_folder, batch_no):
   
    pass_count, fail_count, pass_frac, fail_frac, continuous_fail_active = get_pass_fail_counts(batch_folder)
    total = pass_count + fail_count
    batchId = f"{uuid.uuid4()}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    # 🔥 Scaled sampling
    sampling = compute_scaled_sampling(N_new=total, pass_frac=pass_frac, k=4)
    move_pass = sampling["pass_count"]
    move_fail = sampling["fail_count"]
    need_to_move = move_pass + move_fail
    if continuous_fail_active:
        if need_to_move >= fail_count:
            fail_quota = fail_count
            pass_quota = need_to_move - fail_quota
        else:
            fail_quota = need_to_move
            pass_quota = 0
    moved = 0
    deleted = 0
    allJsonFiles = [f for f in os.listdir(batch_folder) if f.endswith(".json")]
    random.shuffle(allJsonFiles)  # Shuffle to ensure randomness in selection

    for idx,jf in enumerate(allJsonFiles):
        try:
            with open(os.path.join(batch_folder, jf), "r") as f:
                data = json.load(f)
            status = data.get("status", "").lower()
            newData = data.copy()
            img_file = os.path.splitext(jf)[0] + ".jpg"
            json_path = os.path.join(batch_folder, jf)
            if idx == 0:
                plate_type = get_latest_plate_type_with_timeout(get_file_created_iso(json_path), timeout=8)
                # plate_type = "Unknown"
                if plate_type is None:
                    with open("lastPlateType.json", "w") as f:
                        json.dump({"plate_type": "Unknown"}, f)
                    log("⚠️ Could not retrieve latest plate type, defaulting to 'Unknown'")
                else:
                    with open("lastPlateType.json", "w") as f:
                        json.dump({"plate_type": plate_type}, f)
            img_path = os.path.join(batch_folder, img_file)
            newData["batchId"] = batchId
            newData["batchSize"] = BATCH_SIZE
            newData["batchPassCount"] = pass_count
            newData["batchFailCount"] = fail_count
            newData["isBatchFailed"] = 1 if continuous_fail_active else 0

            if continuous_fail_active == True:
                if status == "fail" and fail_quota > 0:
                    with open(os.path.join(batch_folder, jf), "w") as k:
                        json.dump(newData,k,indent=4)
                    move_selected_files([json_path, img_path], output_folder)
                    fail_quota -= 1
                    moved += 1 
                elif status == "pass" and pass_quota > 0:
                    with open(os.path.join(batch_folder, jf), "w") as k:
                        json.dump(newData,k,indent=4)
                    move_selected_files([json_path, img_path], output_folder)
                    pass_quota -= 1
                    moved += 1
                else:
                    for p in [json_path, img_path]:
                        if os.path.exists(p):
                            os.remove(p)
                            deleted += 1

            else:
                if status == "pass" and move_pass > 0:
                    with open(os.path.join(batch_folder, jf), "w") as k:
                        json.dump(newData,k,indent=4)
                    move_selected_files([json_path, img_path], output_folder)
                    move_pass -= 1
                    moved += 1
                elif status == "fail" and move_fail > 0:
                    with open(os.path.join(batch_folder, jf), "w") as k:
                        json.dump(newData,k,indent=4)
                    move_selected_files([json_path, img_path], output_folder)
                    move_fail -= 1
                    moved += 1
                else:
                    for p in [json_path, img_path]:
                        if os.path.exists(p):
                            os.remove(p)
                            deleted += 1
        except:
            continue

    # ✅ One single summary print line
    if not continuous_fail_active:
        log(
        f"Batch {batch_no} | "
        f"Pass%: {pass_frac*100:.2f} | Fail%: {fail_frac*100:.2f} | "
        f"Moved: {sampling['total_count']} (Pass: {sampling['pass_count']}, Fail: {sampling['fail_count']}) | "
        f"ClusterPass%: {round(sampling['p_percent'],2)}, ClusterFail%: {round(sampling['f_percent'],2)} | "
        f"Deleted: {total - sampling['total_count']} | "
        f"ContinuousFailActive: {continuous_fail_active}"  
    )
    else:
        log(
        f"Batch {batch_no} | "
        f"Pass%: 0 | Fail%: 100 | "
        f"Moved: {sampling['total_count']} (Pass: 0, Fail: {need_to_move}) | "
        f"ClusterPass%: 0, ClusterFail%: 100 | "
        f"Deleted: {total - need_to_move} | "
        f"ContinuousFailActive: {continuous_fail_active}"
        )

def watch_folder():
    global batch_no
    while True:
        files = [f for f in os.listdir(WATCH_FOLDER) if f.endswith(".json")]
        if len(files) >= BATCH_SIZE:
            batch_no += 1
            batch_files = files[:BATCH_SIZE]
            batch_folder = os.path.join(WATCH_FOLDER, f"batch_tmp_{batch_no}")
            os.makedirs(batch_folder, exist_ok=True)

            for jf in batch_files:
                img_file = os.path.splitext(jf)[0] + ".jpg"
                shutil.move(os.path.join(WATCH_FOLDER, jf), batch_folder)
                if os.path.exists(os.path.join(WATCH_FOLDER, img_file)):
                    shutil.move(os.path.join(WATCH_FOLDER, img_file), batch_folder)

            process_batch(batch_folder, OUTPUT_FOLDER, batch_no)
            shutil.rmtree(batch_folder)

        time.sleep(1)

# -------------------- Boot --------------------
# watch_folder()