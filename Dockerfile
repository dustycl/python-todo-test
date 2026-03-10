FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN useradd --create-home appuser

# Copy application code
COPY app/ app/
COPY migrations/ migrations/
COPY run.py .

# Create instance directory for logs
RUN mkdir -p instance && chown -R appuser:appuser /app

USER appuser

# Railway sets PORT dynamically; default to 8000 for local Docker
ENV PORT=8000
EXPOSE ${PORT}

CMD gunicorn --bind "0.0.0.0:${PORT}" "app:create_app()"
