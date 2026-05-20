FROM python:3.12-slim

WORKDIR /app

# Install ODBC Driver 18 for SQL Server (direct .deb download, OS-agnostic)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg unixodbc unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/* \
    && odbcinst -q -d 2>&1 | head -5

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9200

ENV PORT=9200
ENV HOST=0.0.0.0
ENV SHOWER_DB=/data/shower.db

VOLUME /data

CMD ["python", "server.py"]
