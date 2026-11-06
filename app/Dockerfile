FROM python:3.15.2-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Prague

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Installers are build-time tools, not part of the serving runtime.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --upgrade --only-binary=:all: -r requirements.txt \
    && pip check \
    && pip uninstall -y pip \
    && python -c "import ensurepip, shutil; shutil.rmtree(ensurepip.__path__[0])"

COPY . .
RUN mkdir -p images thumbnails data

USER 1001:1001

EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003", "--log-level", "info"]
