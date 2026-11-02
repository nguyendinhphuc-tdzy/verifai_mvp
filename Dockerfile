# VerifAI demo image for Hugging Face Spaces (Docker SDK, free CPU Basic:
# 2 vCPU / 16 GB RAM, no GPU, no persistent disk). Also runs anywhere Docker runs.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Spaces run containers as uid 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=2 \
    VERIFAI_DATA=/home/user/data \
    VERIFAI_SEED_DB=/home/user/app/deploy/seed.sql \
    VERIFAI_PUBLIC_MODE=1 \
    OCR_ENABLED=1 OCR_LANG=vi OCR_SCAN_MODE=adaptive \
    ASR_ENABLED=1 WHISPER_MODEL=small WHISPER_LANGUAGE=vi WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 \
    VLM_ENABLED=1 VLM_INPUT_MODE=video MAX_CONCURRENT_JOBS=1 MAX_VIDEO_MB=100
WORKDIR /home/user/app

COPY --chown=user requirements.txt requirements-lock.txt requirements-ai.txt ./
RUN pip install --no-cache-dir --user -r requirements-lock.txt \
    && pip install --no-cache-dir --user paddlepaddle==3.2.0 paddleocr==3.7.0 faster-whisper==1.2.1

COPY --chown=user . .

# Download OCR/ASR weights at build time so the first job does not wait for them.
RUN python scripts/warm_models.py

EXPOSE 7860
# --proxy-headers: Spaces terminate TLS in front of the app; the CSRF origin
# check needs the real https scheme and host.
CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "7860", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
