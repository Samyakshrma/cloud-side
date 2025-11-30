# ---- Base Image ----
FROM python:3.11-slim

# ---- Install System Dependencies (for OpenCV + wget) ----
RUN apt-get update && apt-get install -y \
    wget \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ---- Set Working Directory ----
WORKDIR /app

# ---- Install Python Dependencies ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Prepare Project Directories ----
RUN mkdir -p dnn_models incident_reports dnn_check

# ---- Download DNN Models ----
RUN wget -O dnn_models/res10_300x300_ssd_iter_140000.caffemodel \
    https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel

RUN wget -O dnn_models/deploy.prototxt \
    https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt

# ---- Copy Application Code ----
COPY . .

# ---- Expose FastAPI Port ----
EXPOSE 8000

# ---- Start Server ----
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
