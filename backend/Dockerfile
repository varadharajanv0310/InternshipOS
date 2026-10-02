FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/internshipos /app/backend/internshipos
ENV PYTHONPATH=/app/backend APP_DATA_DIR=/app/data PDF_ENGINE=reportlab
EXPOSE 8000
CMD ["uvicorn", "internshipos.main:app", "--host", "0.0.0.0", "--port", "8000"]
