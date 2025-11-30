import uvicorn
import aiofiles
import datetime
import cv2
import numpy as np
import os
import json 
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import (
    FastAPI,
    File,
    Form,
    UploadFile,
    Depends,
    Header,
    HTTPException,
    Body
)
from fastapi.responses import FileResponse
from pydantic import BaseModel

# --- Custom Module Imports ---
from report_generator import generate_incident_report, REPORT_FILENAME
from database import (
    insert_validated_incident, 
    log_verification_metric, 
    log_heartbeat
)

# --- Configuration ---
EXPECTED_API_KEY = "key"

# Directories
STORAGE_DIR = Path("incident_reports")
DNN_CHECK_DIR = Path("dnn_check") 
STORAGE_DIR.mkdir(exist_ok=True)
DNN_CHECK_DIR.mkdir(exist_ok=True) 

MODEL_DIR = Path("dnn_models")

# --- Model Initialization ---
MODEL_PROTO = str(MODEL_DIR / "deploy.prototxt")
MODEL_WEIGHTS = str(MODEL_DIR / "res10_300x300_ssd_iter_140000.caffemodel")
CONFIDENCE_THRESHOLD = 0.5 

try:
    net = cv2.dnn.readNetFromCaffe(MODEL_PROTO, MODEL_WEIGHTS)
    print("LOG: DNN Face Detector (Caffe) loaded successfully.")
except Exception as e:
    print(f"FATAL ERROR: Could not load DNN model files: {e}")
    net = None

# --- Verification Logic ---
def verify_incident(image_path: Path, alert_type: str) -> dict:
    """
    Runs the heavy DNN FACE verification on the saved image.
    """
    if net is None:
        return {"verification_status": "FAILED", "reason": "DNN model failed to load."}
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return {"verification_status": "FAILED", "reason": "Could not read image file."}

        (h, w) = img.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 1.0,
            (300, 300), (104.0, 177.0, 123.0))

        net.setInput(blob)
        detections = net.forward()

        face_count = 0
        for i in range(0, detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > CONFIDENCE_THRESHOLD:
                face_count += 1
        
        # Verify based on Alert Type logic
        if alert_type == "MULTIPLE_PEOPLE":
            verification_status = "VALIDATED" if face_count > 1 else "FALSE_POSITIVE"
        elif alert_type == "STUDENT_MISSING":
            verification_status = "VALIDATED" if face_count == 0 else "FALSE_POSITIVE"
        else:
            verification_status = "UNKNOWN"

        return {
            "verification_status": verification_status,
            "face_count_dnn": face_count, 
        }

    except Exception as e:
        print(f"!!! DNN VERIFICATION CRASHED: {e} !!!")
        return {"verification_status": "FAILED", "reason": str(e)}

# --- Background Task Wrapper ---
def run_verification_and_cleanup(image_path: Path, alert_type: str):
    """
    Runs verification, logs metrics to Postgres, handles file movement, and persists incidents.
    """
    # 1. Run the heavy verification
    results = verify_incident(image_path, alert_type)
    image_name = image_path.name
    status = results.get("verification_status", "FAILED")
    
    print(f"VERIFICATION COMPLETE: {image_name} -> {status}")

    # 2. Log the metric to Postgres (For your Frontend Graphs - Validated vs False Positive)
    log_verification_metric(alert_type, status)

    # 3. Handle file logic and incident persistence
    try:
        if status == "VALIDATED":
            # Persist Incident Details to Postgres
            insert_validated_incident(
                image_name=image_name,
                alert_type=alert_type,
                face_count=results.get("face_count_dnn", 0)
            )

            # Move file to 'dnn_check'
            dnn_check_path = DNN_CHECK_DIR / image_name
            os.rename(image_path, dnn_check_path)
            print(f"RESULT: VALIDATED. Moved to {dnn_check_path}")
            
        else:
            # Delete False Positives or Failed checks
            if image_path.exists():
                os.remove(image_path)
            print(f"RESULT: {status}. Deleted {image_name}")
            
    except Exception as e:
        print(f"ERROR during cleanup/DB operation: {e}")

# --- Pydantic Models ---
class Heartbeat(BaseModel):
    device_id: str
    duration: float
    frames_processed: int
    frames_discarded: int
    local_incidents: int

# --- API Configuration ---
executor = ThreadPoolExecutor(max_workers=4) 

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True

app = FastAPI(
    title="Edge Proctor Hybrid API",
    dependencies=[Depends(verify_api_key)]
)

@app.on_event("shutdown")
def shutdown_event():
    executor.shutdown(wait=False)

@app.get("/")
def read_root():
    return {"status": "online", "system": "Cloud Verification Node"}

# --- Endpoints ---

# 1. Ingest Heartbeat (Efficiency Metrics)
@app.post("/ingest-heartbeat/")
async def ingest_heartbeat(hb: Heartbeat):
    """
    Receives periodic stats from the Edge device to calculate efficiency.
    """
    log_heartbeat(
        device_id=hb.device_id,
        duration=hb.duration,
        processed=hb.frames_processed,
        discarded=hb.frames_discarded,
        incidents=hb.local_incidents
    )
    return {"status": "ok"}

# 2. Ingest Alert (Verification Pipeline)
@app.post("/ingest-alert/")
async def ingest_alert(
    alert_type: str = Form(...),
    timestamp: float = Form(...),
    image: UploadFile = File(...)
):
    now = datetime.datetime.now()
    file_timestamp = now.strftime('%Y%m%d_%H%M%S')
    safe_alert_type = "".join(c for c in alert_type if c.isalnum() or c in ('_')).rstrip()
    filename = f"{file_timestamp}_{safe_alert_type}_{image.filename}"
    file_path = STORAGE_DIR / filename

    # Save file asynchronously
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await image.read()
            await out_file.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving file: {e}")

    # Offload verification to background thread
    executor.submit(run_verification_and_cleanup, file_path, alert_type)

    return {
        "status": "ACCEPTED",
        "message": "Alert received. Verification running.",
        "server_filename": filename
    }

# 3. Generate Report & Return Stats
@app.post("/generate-report-and-stats/")
async def generate_report_api():
    """
    Generates PDF, clears DB, and returns aggregating statistics for the frontend graphs.
    """
    print("LOG: Request received to generate report and stats.")
    try:
        # report_generator returns tuple: (path_to_pdf, dictionary_of_stats)
        report_path, stats_data = generate_incident_report()
        
        return {
            "status": "success",
            "message": "Report generated and database cleared.",
            "download_link": f"/download-report/{REPORT_FILENAME}",
            "statistics": stats_data  # Feed this to your graphs
        }
    except Exception as e:
        print(f"ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 4. Download Report File
@app.get("/download-report/{filename}")
async def download_report(filename: str):
    file_path = Path(filename)
    if file_path.exists():
         return FileResponse(
             path=file_path, 
             filename=filename, 
             media_type="application/pdf"
         )
    raise HTTPException(status_code=404, detail="Report not found")

if __name__ == "__main__":
    print("--- Starting Cloud Node ---")
    uvicorn.run("main:app", host="127.0.0.1", port="8000", reload=True)