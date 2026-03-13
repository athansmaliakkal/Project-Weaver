# Base image: Ubuntu 24.04 is required for modern Playwright/Camoufox dependencies
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

# Increase timeouts for slow networks (3 hours = 10800 seconds)
ENV PIP_DEFAULT_TIMEOUT=10800
ENV HTTPX_TIMEOUT=10800.0

# Install Python 3.12 and required system libraries
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3-pip \
    curl \
    libdbus-glib-1-2 \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python3 -m venv /opt/venv
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Camoufox (Stealth Playwright fork) and its GeoIP database
RUN pip install --no-cache-dir "camoufox[geoip]"

# Install Playwright OS-level browser dependencies
RUN playwright install-deps

# Fetch the stealth browser binaries with a retry mechanism for slow connections
# This will try the download up to 5 times if it fails
RUN for i in {1..5}; do camoufox fetch && break || sleep 15; done

# Copy the application code
COPY . .

# Create necessary directories for local SQLite and CSV storage
RUN mkdir -p db output

# Expose the API port
EXPOSE 8000

# Start the FastAPI server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]