FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN chmod +x start.sh

EXPOSE 7860

CMD ["bash", "/app/start.sh"]
