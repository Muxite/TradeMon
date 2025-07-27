FROM python:3.10-slim
WORKDIR /stocker
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/stocker:/stocker/shared
