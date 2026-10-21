FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd --create-home bot && mkdir -p /app/data && chown bot /app/data
USER bot

VOLUME ["/app/data"]
EXPOSE 8000

# Mặc định chạy webhook. Muốn chạy polling: docker run ... python -m app.polling
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
