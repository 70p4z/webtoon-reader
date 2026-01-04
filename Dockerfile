
FROM python:3.11-slim
WORKDIR /app
RUN apt update -y -qq
RUN apt install -qq -y unrar-free
COPY requirements.txt /app
RUN pip install -r requirements.txt
COPY . /app
EXPOSE 5000
CMD ["python","app/app.py"]
