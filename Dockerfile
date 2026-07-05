FROM python:3.13-slim

WORKDIR /code

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose port 8000
EXPOSE 8000

# Start the FastAPI application
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
