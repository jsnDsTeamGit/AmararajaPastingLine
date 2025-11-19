import os
import sys
import json
import torch
from datetime import datetime,timezone
from ultralytics import YOLO,RTDETR

LOG_FILE = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__),
                        "SinglePlateModel.log")

def log(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}]{msg}\n")
    except Exception:
        pass

class YoloDetection:
    def __init__(self,model_file,modelType):
        self.device = torch.device(0 if torch.cuda.is_available() else "cpu").type
        if self.device == "cpu":
            log("inferencing with cpu capabilities")
        else:
            log("inferencing with gpu capabilities")
        if modelType == "yolo":
            self.model = YOLO(model_file)
        else:
            self.model = RTDETR(model_file)
    def detectLabel(self,image,th=0.5):
        results=self.model.predict(source=image,show=False,save=False,verbose=False,conf=th,device=self.device,show_conf = False)
        if self.device != "cpu":
            torch.cuda.empty_cache()
        try:
            prediction_dect=results[0].to_json()
            prediction_dect = json.loads(prediction_dect)
            return prediction_dect
        except:
            return []
       