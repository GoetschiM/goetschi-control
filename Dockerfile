# --- Stage 1: build the React (Vite) frontend ---
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build          # outputs to /app/static/spa (see vite.config.js)

# --- Stage 2: Python runtime ---
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/
# overlay the freshly built SPA
COPY --from=frontend /app/static/spa ./static/spa

EXPOSE 8080
CMD ["python", "app.py"]
