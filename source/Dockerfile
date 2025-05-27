FROM python:3.9-slim-bullseye

ARG UID=10001

# Create app directory and essential subdirectories
RUN mkdir -p /app /app/deleted /app/added /app/modified

# Set working directory
WORKDIR /app

# Create a non-root user 'appuser' with a specific UID
# No home directory is created with --no-create-home, shell is /sbin/nologin
RUN adduser \
    --disabled-password \
    --gecos "" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Install jq and clean up apt cache
RUN apt-get update && \
    apt-get install -y --no-install-recommends jq procps && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy application files
COPY ./watchanyresource.py .
COPY ./requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Set home directory for appuser (though it primarily uses WORKDIR /app)
ENV HOME=/app

# Switch to non-root user
USER appuser

# Define the command to run the application
CMD ["python3","./watchanyresource.py"]
