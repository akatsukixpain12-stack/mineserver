FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/agent ./agent
COPY index.html ./web/index.html
CMD exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers
