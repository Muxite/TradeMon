FROM python:3.10-slim
WORKDIR /worker
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.txt
COPY pyproject.toml pyproject.toml
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .
COPY . .
ENV PYTHONPATH=/worker:/worker/shared
