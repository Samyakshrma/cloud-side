import uvicorn
import aiofiles
import datetime
import cv2
import numpy as np
import os
import json 
import sqlite3 
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
from fastapi.responses import FileResponse # NEW: For serving the PDF

# Import the new report generation function and constants
from report_generator import generate_incident_report, REPORT_FILENAME

# --- Configuration ---

EXPECTED_API_KEY = "key"

# Directories on the VM
STORAGE_DIR = Path("incident_reports")
DNN_CHECK_DIR = Path("dnn_check") 
STORAGE_DIR.mkdir(exist_ok=True)
DNN_CHECK_DIR.mkdir(exist_ok=True) 

MODEL_DIR = Path("dnn_models")

# SQLite Database Configuration
DB_NAME = "incident_data.db"
TABLE_NAME = "validated_incidents"

# --- Database Initialization (Unchanged) ---

def initialize_database():
    """Initializes the SQLite database and creates the table if it doesn't exist."""
    print(f"LOG: Initializing database: {DB_NAME}")
    try:
        # Connect to the database (creates it if it doesn't exist)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Create table for validated incidents
        # The image_name will serve as the unique identifier
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                image_name TEXT PRIMARY KEY,
                alert_type TEXT NOT NULL,
                face_count_dnn INTEGER NOT NULL,
                validation_time TEXT NOT NULL
            );
        """)
        conn.commit()
        print(f"LOG: Database and table '{TABLE_NAME}' ready.")
    except Exception as e:
        print(f"FATAL ERROR: Could not initialize SQLite database: {e}")
    finally:
        if conn:
            conn.close()

# --- Model Initialization (Unchanged) ---
MODEL_PROTO = str(MODEL_DIR / "deploy.prototxt")
MODEL_WEIGHTS = str(MODEL_DIR / "res10_300x300_ssd_iter_140000.caffemodel")
CONFIDENCE_THRESHOLD = 0.5 

try:
    net = cv2.dnn.readNetFromCaffe(MODEL_PROTO, MODEL_WEIGHTS)
    print("LOG: DNN Face Detector (Caffe) loaded successfully.")
except Exception as e:
    print(f"FATAL ERROR: Could not load DNN model files. Verification will fail gracefully: {e}")
    net = None

# Initialize the database right after configuration and before running the app
initialize_database()

# --- Verification Function (Unchanged) ---
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
        blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 1.0,
            (300, 300), (104.0, 177.0, 123.0))

        net.setInput(blob)
        detections = net.forward()

        face_count = 0
        
        for i in range(0, detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > CONFIDENCE_THRESHOLD:
                face_count += 1
        
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


# --- Database Insertion Function (Unchanged) ---
def insert_validated_incident(image_name: str, alert_type: str, face_count: int):
    """Inserts a validated incident record into the SQLite database."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Prepare the data
        validation_time = datetime.datetime.now().isoformat()
        
        # Insert the record
        cursor.execute(f"""
            INSERT INTO {TABLE_NAME} (image_name, alert_type, face_count_dnn, validation_time)
            VALUES (?, ?, ?, ?);
        """, (image_name, alert_type, face_count, validation_time))
        
        conn.commit()
        print(f"LOG: Successfully inserted validated incident into DB: {image_name}")

    except sqlite3.IntegrityError:
        # This handles the unlikely case of a duplicate image name
        print(f"WARNING: Duplicate image name attempted for DB insertion: {image_name}")
    except Exception as e:
        print(f"ERROR: Failed to insert incident into DB: {e}")
    finally:
        if conn:
            conn.close()

# --- Background Task Wrapper (Unchanged) ---
def run_verification_and_cleanup(image_path: Path, alert_type: str):
    """
    Runs verification, handles file movement/deletion, and persists data to SQLite.
    """
    # 1. Run the heavy verification
    results = verify_incident(image_path, alert_type)
    image_name = image_path.name
    
    # 2. PRINT THE RESULTS
    print("---" * 10)
    print(f"VERIFICATION COMPLETE for: {image_name}")
    print(json.dumps(results, indent=2)) 
    print("---" * 10)

    # 3. Implement file logic and database persistence
    try:
        if results.get("verification_status") == "VALIDATED":
            # Persist to Database
            insert_validated_incident(
                image_name=image_name,
                alert_type=alert_type,
                face_count=results.get("face_count_dnn", 0)
            )

            # Move the file to the 'dnn_check' folder
            dnn_check_path = DNN_CHECK_DIR / image_name
            os.rename(image_path, dnn_check_path)
            print(f"RESULT: VALIDATED. Moved to {dnn_check_path}")
            
        else:
            # Delete the file if it's a FALSE_POSITIVE, FAILED, or UNKNOWN
            os.remove(image_path)
            print(f"RESULT: FALSE POSITIVE/FAILED. Deleted {image_name}")
            
    except Exception as e:
        print(f"ERROR during file cleanup/DB operation: {e}")

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

# NEW ENDPOINT: Report Generation
@app.get("/generate-report/")
async def generate_report():
    """
    Triggers the creation of a PDF report containing all validated incidents
    and returns the file for download.
    """
    print("LOG: API endpoint /generate-report/ triggered.")
    try:
        # Generate the report synchronously (it's a one-off operation)
        report_path = generate_incident_report()
        
        # Return the generated PDF file using FileResponse
        return FileResponse(
            path=report_path, 
            filename=REPORT_FILENAME, 
            media_type="application/pdf",
            # This ensures the browser downloads the file with the correct name
            headers={"Content-Disposition": f"attachment; filename={REPORT_FILENAME}"}
        )
    except Exception as e:
        # Catch errors from the report generation function
        print(f"ERROR: Failed to generate report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create report: {e}")


@app.post("/ingest-alert/")
async def ingest_alert(
    alert_type: str = Form(...),
    timestamp: float = Form(...),
    image: UploadFile = File(...)
):
    now = datetime.datetime.now()
    file_timestamp = now.strftime('%Y%m%d_%H%M%S')
    # Use the alert_type from the form for the filename construction
    safe_alert_type = "".join(c for c in alert_type if c.isalnum() or c in ('_')).rstrip()
    
    # The original image filename is now appended after the incident type
    # This automatically includes the image name in the file name saved
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