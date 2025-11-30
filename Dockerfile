# Use a lightweight Python base image
FROM python:3.11-slim

# 1. Install system dependencies required for OpenCV and wget
# libgl1 is the modern replacement for the obsolete libgl1-mesa-glx
RUN apt-get update && apt-get install -y \
    wget \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# 2. Copy dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Setup Directories
RUN mkdir -p dnn_models incident_reports dnn_check

# 4. Download the DNN Models directly into the image
RUN wget -O dnn_models/res10_300x300_ssd_iter_140000.caffemodel https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel

RUN wget -O dnn_models/deploy.prototxt https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt

# 5. Copy the rest of your application code
COPY . .

# 6. Expose the port FastAPI runs on
EXPOSE 8000

# 7. Command to run the application
# We use 0.0.0.0 to ensure it listens to requests from outside the container
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]