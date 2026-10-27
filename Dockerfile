FROM python:3.13-slim

RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || sed -i 's/main/main contrib non-free non-free-firmware/g' /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends rsync default-mysql-client rar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["python", "-m", "app.main", "scheduler"]
