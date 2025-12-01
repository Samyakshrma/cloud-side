

# ☁️ ViEdge: Cloud Verification Node Documentation

## 1. Overview

The **ViEdge Cloud Node** acts as the centralized *Forensic Validator* in a hybrid AI architecture. It is only triggered when the Edge device detects a potential violation. Upon receiving an alert, the Cloud Node uses a **ResNet-10 Single Shot Detector (SSD)** to verify if the event is a *true incident* or a *false positive*.

### Key Responsibilities

* **Ingestion:** Receives images and heartbeats from Edge nodes.
* **Verification:** Performs DNN-based validation on alerts.
* **Persistence:** Stores validated results in PostgreSQL (NeonDB).
* **Analytics:** Generates PDF incident reports and bandwidth statistics.

---

## 2. Technology Stack

* **Framework:** FastAPI (Python 3.11+)
* **Server:** Uvicorn
* **AI Engine:** OpenCV DNN (Caffe model)
* **Database:** PostgreSQL on **NeonDB**
* **Deployment:** Docker (Ubuntu LTS on Azure VM)

---

## 3. Directory Structure

```text
cloud-side/
├── dnn_models/                # AI models (auto-downloaded during Docker build)
├── incident_reports/          # Temporary uploads from Edge
├── dnn_check/                 # Permanent verified images
├── Dockerfile                 # Container build instructions
├── requirements.txt           # Dependencies
├── main.py                    # FastAPI entrypoint
├── database.py                # Database connection and schema
├── report_generator.py        # PDF and stats generator
└── .env                       # Secrets and environment variables
```

---

## 4. Environment Setup

Before building the image, create a `.env` file in the project root:

```ini
# .env
NEON_CONN_STRING="postgresql://<user>:<password>@<endpoint>.neon.tech/<dbname>"
```

> 🧠 **Tip:** You can also define additional environment variables here (e.g., API keys, debug flags).

---

## 5. Dockerized Deployment

All dependencies, models, and directories are handled automatically in the Docker build process — no manual downloads required.

### 🧱 Dockerfile Summary

```dockerfile
FROM python:3.11-slim

# Install OpenCV dependencies
RUN apt-get update && apt-get install -y \
    wget libgl1 libglib2.0-0 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create required directories
RUN mkdir -p dnn_models incident_reports dnn_check

# Automatically download models
RUN wget -O dnn_models/res10_300x300_ssd_iter_140000.caffemodel https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel
RUN wget -O dnn_models/deploy.prototxt https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt

COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 6. Run Instructions

### 🔨 Build the Docker Image

```bash
docker build -t viedge-cloud .
```

### 🚀 Run the Container

```bash
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name viedge_container \
  --restart always \
  viedge-cloud
```

The application will be available at:
👉 `http://localhost:8000`

---

## 7. API Reference

| Endpoint                      | Method | Description                                | Payload                            |
| ----------------------------- | ------ | ------------------------------------------ | ---------------------------------- |
| `/ingest-heartbeat/`          | POST   | Receives stats from edge nodes             | JSON `{ "frames_processed": 500 }` |
| `/ingest-alert/`              | POST   | Receives alerts and triggers DNN check     | Multipart (Image + Metadata)       |
| `/generate-report-and-stats/` | POST   | Generates PDF report & resets session data | `{}`                               |
| `/download-report/{filename}` | GET    | Download generated PDF reports             | None                               |

---

## 8. Database Schema

| Table                 | Purpose                                   |
| --------------------- | ----------------------------------------- |
| `validated_incidents` | Stores confirmed alerts (used in reports) |
| `heartbeat_stats`     | Tracks Edge device performance metrics    |
| `verification_stats`  | Logs DNN validation outcomes              |

---

## 9. Troubleshooting

| Error                      | Cause                     | Fix                                                     |
| -------------------------- | ------------------------- | ------------------------------------------------------- |
| `ImportError: libGL.so.1`  | Missing OpenCV dependency | Already handled by `libgl1` in Dockerfile               |
| `DNN model failed to load` | Missing model file        | Models auto-download during build — rebuild image       |
| `Failed to fetch (CORS)`   | API request blocked       | Ensure `CORSMiddleware` in `main.py` allows all origins |

---

### ✅ You’re all set!

Once deployed, your ViEdge Cloud Node will automatically:

* Spin up on Docker
* Connect to NeonDB
* Download and initialize AI models
* Listen for verification alerts on port `8000`

---
