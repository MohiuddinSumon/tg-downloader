# Telegram Downloader

## Overview

This project provides a Docker container for downloading files from Telegram using the `app.py` Python script.

## Docker Commands

### Building the Image

To build the Docker image, run the following command:
```bash
docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t telegram-downloader . --no-cache
```
### Running the Container

To run the Docker container, use the following command:
```bash
docker run -d \
--name telegram-downloader \
--env-file .env \
--mount type=bind,source="$(pwd)/downloader_session.session",target=/app/downloader_session.session \
--mount type=bind,source="${DOWNLOAD_BASE_PATH}",target="${DOWNLOAD_BASE_PATH}" \
--restart unless-stopped \
telegram-downloader
```
### Other Docker Commands

* `docker start`: Starts the container.
* `docker save telegram-downloader:latest`: Saves the image to a file.
* `docker ps -a`: Lists all containers.
* `docker rm`: Removes a container.
* `docker rmi`: Removes an image.
* `docker stats`: Displays container statistics.

## Scripts

### entrypoint.sh

This script is used as the entrypoint for the Docker container. It starts the `app.py` Python script when the container is run.

### windows_runner.bat

This script is used to run the `app.py` Python script on Windows.

## Usage

To use this project, follow these steps:

1. Build the Docker image using the `docker build` command.
2. Run the Docker container using the `docker run` command.
3. Use the `docker start` and `docker stop` commands to control the container.

Note: This is a basic readme file, and you may need to add more information depending on your specific use case.
