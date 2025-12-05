FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY structural_scaffolding ./structural_scaffolding
COPY build_structural_scaffolding.py ./build_structural_scaffolding.py

# Default: keep container running for interactive use
CMD ["tail", "-f", "/dev/null"]
