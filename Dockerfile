FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY config ./config
ENV CONFIG_PATH=/app/config/settings.yaml MIGRATIONS_DIR=/app/backend/migrations
EXPOSE 8000
CMD ["uvicorn", "app.asgi:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
