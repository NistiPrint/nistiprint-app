# Use the official Python image from the Docker Hub
FROM python:3.12-slim

EXPOSE 8080

# Set the working directory in the container
WORKDIR /app

# Install curl
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Upgrade pip to latest version
RUN pip install --no-cache-dir --upgrade pip

# Install the dependencies
RUN pip install --no-cache-dir --timeout=120 -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Create necessary directories
RUN mkdir -p /app/temp
RUN mkdir -p /app/static/js/ferramentas

# Specify the command to run the application
CMD ["gunicorn", "--workers=1", "--threads=3", "-b", "0.0.0.0:8080", "passenger_wsgi:app", "--timeout=600"]
