FROM python:3.11-slim

WORKDIR /app

# Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY app.py .
COPY templates/ templates/
COPY static/ static/

EXPOSE 8080

CMD ["python", "app.py"]
