FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && \
    apt-get install -y python3 python3-pip
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY tests /app/tests/

CMD ["pytest -qq"]