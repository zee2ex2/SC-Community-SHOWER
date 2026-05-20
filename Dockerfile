FROM python:3.12-slim

WORKDIR /app

# Install ODBC Driver 18 for SQL Server
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list | sed 's|signed-by=/etc/apt/trusted.gpg.d/microsoft.asc|signed-by=/usr/share/keyrings/microsoft-prod.gpg|g' > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9200

ENV PORT=9200
ENV HOST=0.0.0.0
ENV SHOWER_DB=/data/shower.db

VOLUME /data

CMD ["python", "server.py"]
