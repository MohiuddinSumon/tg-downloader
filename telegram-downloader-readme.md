# Telegram Zip Document Downloader from Channel

A Python script for downloading files from Telegram channels with support for concurrent downloads, preview image fetching, and flexible filtering options.

## Prerequisites

- Python 3.12 or higher
- Telegram API credentials (API ID and Hash) from https://my.telegram.org/apps

## Installation

1. Install Python:

   - **Windows**: Download and install from [python.org](https://python.org)
   - **macOS**:
     ```bash
     brew install python
     ```
   - **Linux**:
     ```bash
     sudo apt update
     sudo apt install python3 python3-pip
     ```

2. Clone the repository:

   ```bash
   git clone <repository-url>
   cd telegram-downloader
   ```

3. Create and activate virtual environment:

   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # macOS/Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Create a `.env` file in the project root with the following variables:

   ```env
   # Required
   API_ID=your_api_id
   API_HASH=your_api_hash
   CHANNEL_URL=https://t.me/your_channel
   BOT_TOKEN=your_bot_token  # if using bot instead of user account
   TELEGRAM_USER_PHONE=your_phone  # format: +1234567890

   # Optional
   DOWNLOAD_BASE_PATH=./downloads
   MAX_CONCURRENT_DOWNLOADS=3
   MIN_DELAY=3.0
   MAX_DELAY=10.0
   (if you need to filter from specific file)
   FILE_NAME_FILTER=specific_file_name
   (otherwise keep it's value blank to start from last download automatically)
   FILE_NAME_FILTER=
   BEFORE_AFTER='before'  # or 'after'

   ```

### Environment Variables Explanation

- `API_ID` & `API_HASH`: Get from https://my.telegram.org/apps
- `CHANNEL_URL`: Target Telegram channel URL
- `BOT_TOKEN`: Optional bot token for authentication
- `TELEGRAM_USER_PHONE`: Your phone number for user authentication
- `DOWNLOAD_BASE_PATH`: Directory for downloaded files (default: ./downloads)
- `MAX_CONCURRENT_DOWNLOADS`: Number of simultaneous downloads (default: 3)
- `MIN_DELAY` & `MAX_DELAY`: Random delay range between downloads in seconds
- `FILE_NAME_FILTER`: Search for specific file and download befor or after from it
- `BEFORE_AFTER`: Download files before or after a reference point

## Usage

1. Run the script:

   ```bash
   # Make sure virtual environment is activated
   python app.py
   ```

2. First-time setup:

   - If not using a bot token, you'll be prompted for:
     1. Phone number (if not in .env)
     2. Verification code (sent to your Telegram)
     3. Two-factor authentication password (if enabled)
   - Subsequent runs will use the saved session

3. Monitoring:
   - Progress is shown in console
   - Logs are saved in `downloads/downloader.log`
   - Download history is tracked in `downloads/<channel_name>/last_download.json`

## Features

- Concurrent file downloads
- Preview image fetching from Telegram and 3dsky.org
- File filtering by name and date
- Download resumption from last point
- Random delays to avoid rate limiting
- Comprehensive logging

## Troubleshooting

1. If session expires:

   ```bash
   # Delete session file and run again
   rm downloader_session.session
   python app.py
   ```

2. To reset download history:
   ```bash
   # Delete last_download.json from channel directory
   # this will start downloading from latest
   rm downloads/<channel_name>/last_download.json
   ```

## Notes

- Only .zip files are downloaded by default
- Preview images are saved alongside downloaded files
- The script maintains a session file for authentication
- Downloads are tracked per channel
