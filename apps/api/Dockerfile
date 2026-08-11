# Stage 1: Builder
FROM python:3.13-slim AS builder

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Create a virtual environment and install dependencies
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production
FROM python:3.13-slim

# Create a dedicated, non-privileged user to run the application
RUN useradd --create-home --shell /bin/bash api-user

WORKDIR /app

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the application code and set ownership
COPY --chown=api-user:api-user . .

# Drop root privileges by switching to the non-root user
USER api-user

EXPOSE 8000

CMD ["uvicorn", "jat_api.main:app", "--host", "0.0.0.0", "--port", "8000"]