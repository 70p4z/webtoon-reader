
FROM python:3.11-slim
WORKDIR /app
RUN sed -i 's/Components: main/Components: main contrib non-free/' \
       /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends unrar \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app
RUN pip install -r requirements.txt
COPY . /app
EXPOSE 5000
CMD ["python","app/app.py"]
