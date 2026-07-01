# Base training image for Prometheus Swarm.
# Scripts, data, and outputs are mounted as Docker volumes at runtime — not COPYed.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p scripts data outputs && \
    pip install --no-cache-dir \
    lightgbm==4.3.0 \
    xgboost==2.0.3 \
    scikit-learn==1.4.2 \
    pandas==2.2.2 \
    numpy==1.26.4 \
    imbalanced-learn==0.12.3 \
    optuna==3.6.1 \
    torch==2.3.0 \
    transformers==4.41.0

ENTRYPOINT ["python"]
