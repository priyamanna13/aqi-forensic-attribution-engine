# Build the AQI Attribution API backend image.
# Usage (from project root):
#   docker build -t backend-image-name .
#   docker run -d --name backend-container --network aq-intelligence-net \
#              --env-file .env -e POSTGRES_HOST=db -p 5000:5000 backend-image-name

FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer-cached until requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

ENV PYTHONUNBUFFERED=1
# Default DB host to the compose service name when running inside Docker
ENV POSTGRES_HOST=db

EXPOSE 5000

# Serve the FastAPI app via uvicorn
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "5000"]
