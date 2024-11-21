# Docker Commands

## Builds an image from Dockerfile

```bash
docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t telegram-downloader . --no-cache
```

## Creates and run a container from an image

```bash
docker run -d \
--name telegram-downloader \
 --env-file .env \
 --mount type=bind,source="$(pwd)/downloader_session.session",target=/app/downloader_session.session \
  --mount type=bind,source="${DOWNLOAD_BASE_PATH}",target="${DOWNLOAD_BASE_PATH}" \
 --restart unless-stopped \
 telegram-downloader
```

```bash

docker start

docker save telegram-downloader:latest

docker ps -a

docker rm

docker rmi

docker stats
```
