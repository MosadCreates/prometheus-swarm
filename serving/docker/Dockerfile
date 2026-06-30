# Serving container — hosts the FastAPI model endpoint
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    uvicorn>=0.30.0 \
    onnxruntime>=1.18.0 \
    numpy>=1.26.4 \
    pandas>=2.2.2 \
    prometheus-client>=0.20.0 \
    scikit-learn>=1.4.2 \
    joblib>=1.3.2

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
