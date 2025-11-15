import uvicorn
import aiofiles
import datetime
import cv2
import numpy as np
import os
import json # Import json for logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import (
    FastAPI,
    File,
    Form,
    UploadFile,
    Depends,
    Header,
    HTTPException
)

# --- Configuration ---

EXPECTED_API_KEY = "your-secret-key-here-12345"

# Directories on the VM
STORAGE_DIR = Path("incident_reports")
DNN_CHECK_DIR = Path("dnn_check") 
STORAGE_DIR.mkdir(exist_ok=True)
DNN_CHECK_DIR.mkdir(exist_ok=True) 

MODEL_DIR = Path("dnn_models")

# --- THIS IS THE NEW, CORRECT MODEL ---
# We are now using a Caffe DNN Face Detector, not YOLO
MODEL_PROTO = str(MODEL_DIR / "deploy.prototxt")
MODEL_WEIGHTS = str(MODEL_DIR / "res10_300x300_ssd_iter_140000.caffemodel")
# ---------------------------------------

CONFIDENCE_THRESHOLD = 0.5 # We can use the same confidence

# --- Global Model Initialization ---
try:
    # Load the new Caffe model
    net = cv2.dnn.readNetFromCaffe(MODEL_PROTO, MODEL_WEIGHTS)
    print("LOG: DNN Face Detector (Caffe) loaded successfully.")

except Exception as e:
    print(f"FATAL ERROR: Could not load DNN model files. Verification will fail gracefully: {e}")
    net = None

# --- Verification Function (NEW, SIMPLER, MORE ACCURATE) ---
def verify_incident(image_path: Path, alert_type: str) -> dict:
    """
    Runs the heavy DNN FACE verification on the saved image.
    This version ONLY checks for face count.
    """
    
    if net is None:
        return {"verification_status": "FAILED", "reason": "DNN model failed to load on startup."}
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return {"verification_status": "FAILED", "reason": "Could not read image file."}

        (h, w) = img.shape[:2]
        # Create a blob, resizing to a fixed 300x300 pixels
        # and applying the model's required mean subtraction
        blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 1.0,
            (300, 300), (104.0, 177.0, 123.0))

        net.setInput(blob)
        # This is the heavy part
        detections = net.forward()

        face_count = 0
        
        # Loop over the detections
        for i in range(0, detections.shape[2]):
            # Extract the confidence (i.e., probability)
            confidence = detections[0, 0, i, 2]

            # Filter out weak detections
            if confidence > CONFIDENCE_THRESHOLD:
                face_count += 1
        
        # --- SIMPLIFIED LOGIC ---
        if alert_type == "MULTIPLE_PEOPLE":
            # Edge said >1. We validate if DNN also says >1.
            verification_status = "VALIDATED" if face_count > 1 else "FALSE_POSITIVE"
            
        elif alert_type == "STUDENT_MISSING":
            # Edge said 0. We validate if DNN also says 0.
            verification_status = "VALIDATED" if face_count == 0 else "FALSE_POSITIVE"
        
        else:
            verification_status = "UNKNOWN"

        return {
            "verification_status": verification_status,
            "face_count_dnn": face_count, # This count will now be accurate
        }
        # --- END OF SIMPLIFIED LOGIC ---

    except Exception as e:
        print(f"!!! DNN VERIFICATION CRASHED: {e} !!!")
        return {"verification_status": "FAILED", "reason": str(e)}


# --- Background Task Wrapper (Unchanged) ---
def run_verification_and_cleanup(image_path: Path, alert_type: str):
    """
    This is the new function that runs in the background.
    It gets the verification result and performs your requested file operations.
    """
    # 1. Run the heavy verification
    results = verify_incident(image_path, alert_type)
    
    # 2. PRINT THE RESULTS
    print("---" * 10)
    print(f"VERIFICATION COMPLETE for: {image_path.name}")
    print(json.dumps(results, indent=2)) # Pretty-print the results
    print("---" * 10)

    # 3. Implement your file logic
    try:
        if results.get("verification_status") == "VALIDATED":
            # Move the file to the 'dnn_check' folder
            dnn_check_path = DNN_CHECK_DIR / image_path.name
            os.rename(image_path, dnn_check_path)
            print(f"RESULT: VALIDATED. Moved to {dnn_check_path}")
        else:
            # Delete the file if it's a FALSE_POSITIVE or FAILED
            os.remove(image_path)
            print(f"RESULT: FALSE POSITIVE/FAILED. Deleted {image_path.name}")
    except Exception as e:
        print(f"ERROR during file cleanup: {e}")

# --- Security Dependency (Unchanged) ---
async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if x_api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True

# --- API Application ---
executor = ThreadPoolExecutor(max_workers=4) 
app = FastAPI(
    title="Edge Proctor Ingestion & Verification API",
    dependencies=[Depends(verify_api_key)]
)

@app.on_event("shutdown")
def shutdown_event():
    executor.shutdown(wait=False)

@app.get("/")
async def get_root():
    return {"status": "ok", "message": "Proctor API is running."}

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

    # 1. Save the uploaded image asynchronously
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await image.read()
            await out_file.write(content)
    except Exception as e:
        print(f"Error saving file: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving file: {e}")

    # 2. Trigger the Heavy Verification in a background thread
    print(f"LOG: Image saved to {file_path}. Starting DNN verification in background...")
    
    executor.submit(run_verification_and_cleanup, file_path, alert_type)

    # 3. Respond INSTANTLY to the edge device
    return {
        "status": "ACCEPTED",
        "message": "Alert received. Verification is running in the background.",
        "server_filename": filename,
        "verification_status": "PENDING"
    }

if __name__ == "__main__":
    print("--- Starting local development server ---")
    uvicorn.run("main:app", host="127.0.0.1", port="8000", reload=True)