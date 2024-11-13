FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    cifs-utils \
    && rm -rf /var/lib/apt/lists/*


# Get the user and group ID of the host system (assuming you're using environment variables)
ARG UID=1000
ARG GID=1000

# Create a user with the same UID and GID as the host system user
RUN addgroup --gid ${GID} appgroup && \
    adduser --uid ${UID} --gid ${GID} --disabled-password --gecos "" appuser



# Set working directory
WORKDIR /app

RUN chown -R appuser:appgroup /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make entrypoint script executable
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh


# Set the user to run the application as the created user
USER appuser
# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]