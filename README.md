


# ☁️ ViEdge: Cloud Verification Node Documentation

## 1\. Overview

The **ViEdge Cloud Node** serves as the centralized "Forensic Validator" in the hybrid architecture. Unlike traditional systems that process every frame, this node remains idle until triggered by the Edge device. Upon receiving a filtered alert, it spins up a heavy **Deep Neural Network (ResNet-10 SSD)** to perform a high-precision analysis, determining if the alert is a true incident or a false positive.

### Key Responsibilities

  * **Ingestion:** Receives high-priority images and efficiency heartbeats from Edge devices.
  * **Verification:** Runs a ResNet-10 Single Shot Detector (SSD) to validate face counts.
  * **Persistence:** Stores validated metadata in PostgreSQL and archives forensic images.
  * **Analytics:** Calculates bandwidth savings and generates PDF incident reports.

-----

## 2\. Technology Stack

  * **Framework:** FastAPI (Python 3.11+)
  * **Server:** Uvicorn (ASGI) / Gunicorn (Process Manager)
  * **AI Engine:** OpenCV DNN Module (Caffe Framework)
  * **Database:** PostgreSQL (Hosted on NeonDB)
  * **Deployment:** Docker Container on Azure VM (Ubuntu LTS)

-----

## 3\. Directory Structure

The application requires a specific directory layout to function correctly.

```text
cloud-side/
├── dnn_models/                 # Stores the heavy AI models
│   ├── deploy.prototxt         # Model architecture
│   └── res10_300x300...model   # Pre-trained weights
├── incident_reports/           # Temp storage for incoming alerts
├── dnn_check/                  # Permanent storage for validated images
├── Dockerfile                  # Container instructions
├── requirements.txt            # Python dependencies
├── main.py                     # API Entry point & Verification Logic
├── database.py                 # PostgreSQL connection & Schema management
├── report_generator.py         # PDF generation logic
└── .env                        # Secrets (DB Connection String)
```

-----

## 4\. AI Model Setup (Critical)

The Cloud Node relies on a **ResNet-10 Single Shot Detector (SSD)**. This model is too large to store in source control and must be downloaded during setup or Docker build.

**Model Source:** OpenCV 3rd Party Repository.

### Download Commands

Run these commands inside the `cloud-side` directory to create the folder and fetch the models:

```bash
# 1. Create the directory
mkdir -p dnn_models

# 2. Download Pre-trained Weights (The "Brain")
wget -O dnn_models/res10_300x300_ssd_iter_140000.caffemodel https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel

# 3. Download Architecture Config (The "Structure")
wget -O dnn_models/deploy.prototxt https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt
```

-----

## 5\. Configuration

Create a `.env` file in the root directory to store sensitive credentials.

```ini
# .env
NEON_CONN_STRING="postgresql://<user>:<password>@<endpoint>.neon.tech/<dbname>"
```

*Note: The API Key logic is handled in code (`EXPECTED_API_KEY = "key"`), but can be moved here for higher security.*

-----

## 6\. Deployment (Docker)

We use Docker to ensure the OpenCV dependencies and system libraries (`libgl1`, etc.) are identical in development and production.

### Dockerfile Breakdown

Our `Dockerfile` automatically handles the model download so you don't need to do it manually on the server.

```dockerfile
FROM python:3.11-slim

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y \
    wget libgl1 libglib2.0-0 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create directories
RUN mkdir -p dnn_models incident_reports dnn_check

# AUTOMATIC MODEL DOWNLOAD during build
RUN wget -O dnn_models/res10_300x300_ssd_iter_140000.caffemodel https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel
RUN wget -O dnn_models/deploy.prototxt https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt

COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Run Commands

```bash
# 1. Build the image (Downloads models & installs dependencies)
docker build -t viedge-cloud .

# 2. Run the container (Maps port 8000 & injects DB connection)
docker run -d -p 8000:8000 --env-file .env --name viedge_container --restart always viedge-cloud
```

-----

## 7\. API Reference

The Cloud Node exposes RESTful endpoints for the Edge and Dashboard.

| Endpoint | Method | Purpose | Payload |
| :--- | :--- | :--- | :--- |
| `/ingest-heartbeat/` | POST | **Efficiency Tracking.** Receives stats on processed/discarded frames from Edge. | JSON `{ "frames_processed": 500... }` |
| `/ingest-alert/` | POST | **Verification Pipeline.** Receives potential violation images. Triggers background DNN check. | Multipart Form (Image + Metadata) |
| `/generate-report-and-stats/` | POST | **Sync.** Calculates final stats, generates PDF, and **clears the database** for the next session. | Empty JSON |
| `/download-report/{filename}` | GET | **Download.** Serves the generated PDF report. | None |

-----

## 8\. Database Schema

The system uses three tables in PostgreSQL to separate operational data from analytical metrics.

1.  **`validated_incidents`**: Stores verified alerts (Image Name, Type, Timestamp). Used for PDF generation.
2.  **`heartbeat_stats`**: Stores raw counters (Processed vs. Discarded). Used to calculate "Bandwidth Saved."
3.  **`verification_stats`**: Stores the outcome of every DNN check (True Positive vs. False Positive). Used to visualize AI accuracy.

-----

## 9\. Troubleshooting

  * **Error:** `ImportError: libGL.so.1`
      * **Fix:** Ensure `libgl1` is installed in the Dockerfile (already included in the provided config).
  * **Error:** `DNN model failed to load`
      * **Fix:** Check `dnn_models/` directory. Ensure the file sizes are correct (`.caffemodel` should be approx 10MB).
  * **Error:** `Failed to fetch` (Frontend)
      * **Fix:** Ensure `CORSMiddleware` is active in `main.py` and allowing `*` origins.