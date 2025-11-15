import uvicorn
import aiofiles
import datetime
import cv2
import numpy as np
import os
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
STORAGE_DIR.mkdir(exist_ok=True)
MODEL_DIR = Path("dnn_models")

# Model files (relative to the FastAPI root directory)
MODEL_CFG = str(MODEL_DIR / "yolov3-tiny.cfg")
MODEL_WEIGHTS = str(MODEL_DIR / "yolov3-tiny.weights")
MODEL_NAMES = str(MODEL_DIR / "coco.names")

CONFIDENCE_THRESHOLD = 0.5
PROCTORING_OBJECTS = ["laptop", "keyboard", "mouse", "chair", "dining table", "cell phone"]


# --- Global Model Initialization ---
# The model loads ONCE when the server starts.
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


# --- Verification Function (The heavy, blocking task) ---
def verify_incident(image_path: Path, alert_type: str) -> dict:
    """Runs the heavy DNN verification on the saved image."""
    
    # 1. Check if model is available
    if net is None:
        return {"verification_status": "FAILED", "reason": "DNN model failed to load on startup."}

    # 2. Load the image from disk
    img = cv2.imread(str(image_path))
    if img is None:
        return {"verification_status": "FAILED", "reason": "Could not read image file."}

    # 3. Prepare the image for the network (create blob)
    blob = cv2.dnn.blobFromImage(img, 1/255.0, (416, 416), swapRB=True, crop=False)
    net.setInput(blob)
    
    # 4. Forward pass through the network (The computationally intensive part)
    outs = net.forward(output_layers)

    # 5. Process results
    class_ids = []
    
    for out in outs:
        for detection in out:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]
            if confidence > CONFIDENCE_THRESHOLD:
                class_ids.append(class_id)
    
    detected_classes = [classes[id] for id in class_ids]
    
    # 6. Determine Verification Status based on alert_type
    
    if alert_type == "MULTIPLE_PEOPLE":
        person_count = detected_classes.count("person")
        if person_count > 1:
            verification_status = "VALIDATED"
        else:
            verification_status = "FALSE_POSITIVE"
            
        return {
            "verification_status": verification_status,
            "person_count_dnn": person_count,
            "detected_objects": list(set(detected_classes))
        }

    elif alert_type == "STUDENT_MISSING":
        person_count = detected_classes.count("person")
        proctor_objects_present = any(obj in detected_classes for obj in PROCTORING_OBJECTS)
        
        if person_count == 0 and proctor_objects_present:
            verification_status = "VALIDATED"
        else:
            verification_status = "FALSE_POSITIVE"
            
        return {
            "verification_status": verification_status,
            "person_count_dnn": person_count,
            "proctor_objects_present": proctor_objects_present,
            "detected_objects": list(set(detected_classes))
        }
        
    return {"verification_status": "UNKNOWN", "reason": "Invalid alert type."}


# --- Security Dependency ---
async def verify_api_key(x_api_key: str = Header(None)):
    """A dependency to verify the X-API-Key header."""
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if x_api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True

# --- API Application ---
# NOTE: We create a custom ThreadPoolExecutor to prevent blocking the main Uvicorn worker thread
executor = ThreadPoolExecutor(max_workers=4) 

app = FastAPI(
    title="Edge Proctor Ingestion & Verification API",
    description="Receives alerts, saves images, and verifies them using a YOLO DNN model.",
    dependencies=[Depends(verify_api_key)]
)


@app.on_event("shutdown")
def shutdown_event():
    executor.shutdown(wait=False) # Ensure background threads are cleaned up


@app.get("/")
async def get_root():
    """Root endpoint to check if the API is alive."""
    return {"status": "ok", "message": "Proctor API is running."}


@app.post("/ingest-alert/")
async def ingest_alert(
    alert_type: str = Form(...),
    timestamp: float = Form(...),
    image: UploadFile = File(...)
):
    """
    Main endpoint for receiving alerts, saving the image, and triggering DNN verification.
    """
    
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
    print(f"LOG: Image saved to {file_path}. Starting DNN verification...")
    
    # We submit the blocking verify_incident function to the executor.
    # We do NOT await it here. The result will be processed later.
    executor.submit(verify_incident, file_path, alert_type)

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