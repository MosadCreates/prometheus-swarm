# Base training image
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    lightgbm==4.3.0 \
    xgboost==2.0.3 \
    scikit-learn==1.4.2 \
    pandas==2.2.2 \
    numpy==1.26.4 \
    imbalanced-learn==0.12.3 \
    optuna==3.6.1 \
    torch==2.3.0 \
    transformers==4.41.0

WORKDIR /app
COPY scripts/ /app/scripts/
COPY data/ /app/data/
COPY outputs/ /app/outputs/

ENTRYPOINT ["python"]
