FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    VISUAL_ASSET_ENHANCEMENT_ENABLED=0 \
    PDF_VISUAL_ASSET_ENHANCEMENT_ENABLED=0

WORKDIR /app

# Runtime libraries required by OpenCV/Paddle. OCRmyPDF, Ghostscript, qpdf,
# and Tesseract are intentionally absent from the stable-v4 pipeline.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads

EXPOSE 7860

CMD ["python", "app.py"]
