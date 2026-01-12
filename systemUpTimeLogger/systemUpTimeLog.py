import json
import time
import os
from datetime import datetime

# ---------------- CONFIG ----------------
LOG_FILE = "system_uptime.json"
HEARTBEAT_INTERVAL = 10  # 5 minutes
RETRY_DELAY = 2  # seconds
MAX_RETRIES = 5
# ----------------------------------------

def now():
    return datetime.now().isoformat(timespec="seconds")

def load_json():
    if not os.path.exists(LOG_FILE):
        return {}

    for _ in range(MAX_RETRIES):
        try:
            with open(LOG_FILE, "r") as f:
                return json.load(f)

        except json.JSONDecodeError:
            # Try recovering from backup
            bak_file = LOG_FILE + ".bak"
            if os.path.exists(bak_file):
                try:
                    with open(bak_file, "r") as bf:
                        data = json.load(bf)
                    # Restore backup → main
                    save_json(data)
                    return data
                except Exception:
                    pass
            return {}

        except (PermissionError, OSError):
            time.sleep(RETRY_DELAY)

    return {}


    return {}

def save_json(data):
    temp_file = LOG_FILE + ".tmp"
    bak_file = LOG_FILE + ".bak"

    for _ in range(MAX_RETRIES):
        try:
            # Write temp
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=4)

            # Backup current file
            if os.path.exists(LOG_FILE):
                os.replace(LOG_FILE, bak_file)

            # Replace main atomically
            os.replace(temp_file, LOG_FILE)
            return

        except (PermissionError, OSError):
            time.sleep(RETRY_DELAY)

    print("Warning: Failed to persist uptime log safely.")


def main():
    system_start_time = now()

    data = load_json()
    data[system_start_time] = system_start_time
    save_json(data)

    try:
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            data = load_json()
            data[system_start_time] = now()
            save_json(data)

    except KeyboardInterrupt:
        data = load_json()
        data[system_start_time] = now()
        save_json(data)

if __name__ == "__main__":
    main()
