FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

FROM base AS builder
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

FROM base AS production
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .
EXPOSE 8001

CMD ["gunicorn", "main:app",
 "--workers", "4",
 "--worker-class", "uvicorn.workers.UvicornWorker",
 "--bind", "0.0.0.0:8001",
 "--timeout", "60",
 "--access-logfile", "-"]