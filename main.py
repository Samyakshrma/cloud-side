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
DNN_CHECK_DIR = Path("dnn_check") # <-- YOUR NEW FOLDER
STORAGE_DIR.mkdir(exist_ok=True)
DNN_CHECK_DIR.mkdir(exist_ok=True) # <-- CREATE IT

MODEL_DIR = Path("dnn_models")

# Model files (Using yolov3-tiny, as it's lighter)
MODEL_CFG = str(MODEL_DIR / "yolov3-tiny.cfg")
MODEL_WEIGHTS = str(MODEL_DIR / "yolov3-tiny.weights")
MODEL_NAMES = str(MODEL_DIR / "coco.names")

CONFIDENCE_THRESHOLD = 0.5
# --- PROCTORING_OBJECTS list has been REMOVED ---

# --- Global Model Initialization ---
try:
    net = cv2.dnn.readNetFromDarknet(MODEL_CFG, MODEL_WEIGHTS)
    layer_names = net.getLayerNames()
    output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]
    
    with open(MODEL_NAMES, 'r') as f:
        classes = [line.strip() for line in f.readlines()]
    
    print("LOG: DNN Model (YOLOv3-tiny) loaded successfully.")

except Exception as e:
    print(f"FATAL ERROR: Could not load DNN model files. Verification will fail gracefully: {e}")
    net = None

# --- Verification Function (SIMPLIFIED as you requested) ---
def verify_incident(image_path: Path, alert_type: str) -> dict:
    """
    Runs the heavy DNN verification on the saved image.
    This version ONLY checks for person count.
    """
    
    if net is None:
        return {"verification_status": "FAILED", "reason": "DNN model failed to load on startup."}
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return {"verification_status": "FAILED", "reason": "Could not read image file."}

        blob = cv2.dnn.blobFromImage(img, 1/255.0, (416, 416), swapRB=True, crop=False)
        net.setInput(blob)
        outs = net.forward(output_layers) # This is the heavy part

        class_ids = []
        for out in outs:
            for detection in out:
                scores = detection[5:]
                class_id = np.argmax(scores)
                confidence = scores[class_id]
                if confidence > CONFIDENCE_THRESHOLD:
                    class_ids.append(class_id)
        
        detected_classes = [classes[id] for id in class_ids]
        person_count = detected_classes.count("person")
        
        # --- NEW, SIMPLIFIED LOGIC ---
        if alert_type == "MULTIPLE_PEOPLE":
            # Edge said >1. We validate if DNN also says >1.
            verification_status = "VALIDATED" if person_count > 1 else "FALSE_POSITIVE"
            
        elif alert_type == "STUDENT_MISSING":
            # Edge said 0. We validate if DNN also says 0.
            verification_status = "VALIDATED" if person_count == 0 else "FALSE_POSITIVE"
        
        else:
            verification_status = "UNKNOWN"

        return {
            "verification_status": verification_status,
            "person_count_dnn": person_count,
            "detected_objects": list(set(detected_classes)) # We still log everything, just don't use it for logic
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
    
    # --- MODIFIED: Call your new wrapper function ---
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
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)