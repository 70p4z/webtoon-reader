FROM python:3.11-slim

# Prevent .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Flask config
ENV FLASK_ENV=production
ENV WEBTOON_LIBRARY=/library

# Create instance folder
RUN mkdir -p instance

EXPOSE 5000

CMD ["python", "run.py"]
