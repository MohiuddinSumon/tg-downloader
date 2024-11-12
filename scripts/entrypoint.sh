#!/bin/bash

# Mount network share
mkdir -p /mnt/telegram-storage
mount -t cifs //${SERVER_IP}/Storage-C/telegram-zips /mnt/telegram-storage -o vers=3.0,username=${SMB_USERNAME},password=${SMB_PASSWORD}

# Start the Python script
exec python /app/telegram_downloader.py