import uvicorn
import aiofiles
import datetime
from pathlib import Path
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

# !! IMPORTANT: Change this to your own secret key
# This is the key your edge script must send in its header
EXPECTED_API_KEY = "your-secret-key-here-12345"

# Create a directory to store the incident images
STORAGE_DIR = Path("incident_reports")
STORAGE_DIR.mkdir(exist_ok=True)


# --- Security Dependency ---

async def verify_api_key(x_api_key: str = Header(None)):
    """A dependency to verify the X-API-Key header."""
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if x_api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return True

# --- API Application ---

app = FastAPI(
    title="Edge Proctor Ingestion API",
    description="Receives incident alerts and images from edge devices.",
    dependencies=[Depends(verify_api_key)] # This applies API key auth to ALL endpoints
)


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
    This is the main endpoint for receiving alerts.
    It expects a multipart/form-data request containing:
    - 'alert_type' (form data)
    - 'timestamp' (form data)
    - 'image' (file data)
    """
    
    # 1. Create a unique, sortable filename
    now = datetime.datetime.now()
    file_timestamp = now.strftime('%Y%m%d_%H%M%S')
    
    # Clean the alert_type for the filename
    safe_alert_type = "".join(c for c in alert_type if c.isalnum() or c in ('_')).rstrip()
    filename = f"{file_timestamp}_{safe_alert_type}_{image.filename}"
    file_path = STORAGE_DIR / filename

    # 2. Save the uploaded image asynchronously
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            content = await image.read()  # Read file content
            await out_file.write(content)  # Write to disk
    except Exception as e:
        print(f"Error saving file: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving file: {e}")

    # 3. Log to console and return success
    print(f"LOG [Alert Received]:")
    print(f"  > Type: {alert_type}")
    print(f"  > Edge Timestamp: {datetime.datetime.fromtimestamp(timestamp)}")
    print(f"  > Image Saved as: {file_path}")
    
    return {
        "status": "success",
        "message": "Alert processed and image saved.",
        "server_filename": filename,
        "alert_type": alert_type
    }

# This allows you to run `python main.py` for local testing
if __name__ == "__main__":
    print("--- Starting local development server ---")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)