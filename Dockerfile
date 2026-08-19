FROM python:3.13-slim

WORKDIR /app

# Prevent Python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install Python dependencies (psycopg2-binary contains precompiled wheels)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port
EXPOSE 8000

# Command to run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
