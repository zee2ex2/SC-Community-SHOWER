FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9200

ENV PORT=9200
ENV HOST=0.0.0.0
ENV SHOWER_DB=/data/shower.db

VOLUME /data

CMD ["python", "server.py"]
