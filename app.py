import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import pytz
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telethon import TelegramClient, sync
from telethon.tl.types import (
    InputMessagesFilterDocument,
    InputMessagesFilterPhotos,
    Message,
)

# pylint: disable=W1203


class TelegramDownloader:
    """
    TelegramDownloader class for downloading files from Telegram channels."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "downloader_session",
        download_path: Union[str, Path] = os.getenv(
            "DOWNLOAD_BASE_PATH", "./downloads"
        ),
        log_level: int = logging.INFO,
    ):
        """
        Initialize the Telegram downloader.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_name: Name for the Telegram session
            download_path: Path where files will be saved
            log_level: Logging level (default: logging.INFO)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.base_download_path = Path(download_path)
        self.base_download_path.mkdir(parents=True, exist_ok=True)
        self.current_channel_path: Optional[Path] = None
        self.last_download_file: Optional[Path] = None
        self.session_name = session_name
        self.session_file = Path(f"{session_name}.session")

        # Setup logging
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.base_download_path / "downloader.log"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Initialize client with unique session name to avoid conflicts
        # unique_session = f"{session_name}_{os.getpid()}"
        self.client = TelegramClient(session_name, api_id, api_hash)

    def setup_channel_directory(self, channel_name: str):
        """Setup channel-specific directory and last download tracking file."""
        self.current_channel_path = self.base_download_path / channel_name
        self.current_channel_path.mkdir(parents=True, exist_ok=True)
        self.last_download_file = self.current_channel_path / "last_download.json"

    def get_last_download_info(self) -> Dict:
        """Read last download information from tracking file."""
        if self.last_download_file and self.last_download_file.exists():
            try:
                with open(self.last_download_file, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                self.logger.warning("Invalid last download file, starting fresh")
        return {}

    def save_last_download_info(self, message: Message):
        """Save information about the last downloaded file."""
        if not self.last_download_file:
            return

        download_info = {
            "date": message.date.isoformat(),
            "message_id": message.id,
            "file_name": message.file.name if message.file else None,
            "downloaded_at": datetime.now().isoformat(),
        }

        with open(self.last_download_file, "w") as f:
            json.dump(download_info, f, indent=2)

    async def check_session(self) -> bool:
        """Check if a valid session exists and is usable."""
        if not self.session_file.exists():
            self.logger.info("No existing session found")
            return False

        try:
            # Try to connect using existing session
            if not self.client.is_connected():
                await self.client.connect()

            # Check if session is authorized
            if await self.client.is_user_authorized():
                self.logger.info("Found valid existing session")
                return True
            else:
                self.logger.info("Session exists but is not authorized")
                return False
        except Exception as e:
            self.logger.warning(f"Error checking session: {str(e)}")
            return False

    async def connect(self) -> bool:
        """
        Connect to Telegram, using existing session if available.
        Returns True if connection was successful.
        """

        try:
            # Check for existing valid session first
            if await self.check_session():
                return True

            # If no valid session, start new connection
            if not self.client.is_connected():
                await self.client.connect()

            # Try bot token first if available
            bot_token = os.getenv("BOT_TOKEN")
            if bot_token:
                await self.client.start(bot_token=bot_token)  # type: ignore
                self.logger.info("Connected to Telegram as a bot")
                return True

            # Fall back to user authentication
            user_phone = os.getenv("TELEGRAM_USER_PHONE")
            if not user_phone:
                user_phone = input("Enter your phone number: ")

            # Start the client with phone number
            await self.client.start(phone=user_phone)  # type: ignore
            self.logger.info(f"Connected to Telegram as user: {user_phone}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to Telegram: {str(e)}")
            return False

    async def disconnect(self):
        """Properly disconnect from Telegram."""
        try:
            await self.client.disconnect()  # type: ignore
            self.logger.info("Disconnected from Telegram")
        except Exception as e:
            self.logger.error(f"Error during disconnect: {str(e)}")

    async def logout(self):
        """Log out and remove session file."""
        try:
            await self.client.log_out()
            self.logger.info("Logged out from Telegram")

            # Remove session file if it exists
            if self.session_file.exists():
                self.session_file.unlink()
                self.logger.info("Removed session file")
        except Exception as e:
            self.logger.error(f"Error during logout: {str(e)}")

    def random_delay(self, min_seconds: float = 3.0, max_seconds: float = 10.0):
        """Add random delay to avoid detection."""
        delay = random.uniform(min_seconds, max_seconds)
        self.logger.debug(f"Adding delay of {delay:.2f} seconds")
        time.sleep(delay)

    async def download_files(
        self,
        channel_url: str,
        file_name_filter: Optional[str] = None,
        date_filter: Optional[datetime] = None,
        before_after: str = "after",
        limit: Optional[int] = None,
    ) -> List[Path]:
        """
        Download ZIP files from the specified channel with filtering options.

        Args:
            channel_url: URL or username of the Telegram channel
            file_name_filter: Optional filter for file names
            date_filter: Optional datetime to filter messages
            before_after: "before" or "after" for date filtering
            limit: Maximum number of files to download

        Returns:
            List of paths to downloaded files
        """
        downloaded_files = []
        try:
            channel = await self.client.get_entity(channel_url)
            channel_name = channel.username or channel.title
            self.setup_channel_directory(channel_name)

            self.logger.info(f"Accessing channel: {channel.title}")

            # Get last download info
            last_download = self.get_last_download_info()
            last_message_id = last_download.get("message_id", 0)
            print(last_message_id)

            # Ensure date_filter is timezone-aware if provided
            if date_filter and date_filter.tzinfo is None:
                date_filter = pytz.UTC.localize(date_filter)

            async for message in self.client.iter_messages(
                channel,
                limit=limit,
                filter=InputMessagesFilterDocument,
                max_id=last_message_id,
            ):
                try:

                    if message.file and message.file.name.endswith(".zip"):
                        print(
                            f"Got A File to download: {message.date}, {message.file.name}, {message.id}"
                        )
                        # Apply filters
                        if date_filter:
                            print(
                                f"Applying Date Filter: Message Date: {message.date}, Filter Date:{date_filter}, Before/After: {before_after}"
                            )

                            message_date = message.date.replace(
                                tzinfo=pytz.UTC
                            )  # Ensure message date is UTC
                            if (
                                before_after == "after" and message_date < date_filter
                            ) or (
                                before_after == "before" and message_date > date_filter
                            ):
                                print(
                                    f"IN FILTER {message_date}, {date_filter}, {message.file.name}"
                                )
                                continue

                        if (
                            file_name_filter
                            and file_name_filter.lower()
                            not in message.file.name.lower()
                        ):
                            continue

                        # Use channel-specific directory for downloads
                        file_path = self.current_channel_path / message.file.name

                        try:
                            # Skip if file already exists
                            if file_path.exists():
                                self.logger.info(
                                    f"File already exists, skipping: {message.file.name}"
                                )
                                downloaded_files.append(file_path)
                                continue

                            self.logger.info(f"Downloading: {message.file.name}")
                            await message.download_media(file_path)
                            downloaded_files.append(file_path)

                            # Save last download info after successful download
                            self.save_last_download_info(message)

                            self.logger.info(
                                f"Successfully downloaded: {message.file.name}"
                            )

                            # Then try to find and download the preview image
                            base_filename = (
                                file_path.stem
                            )  # Get filename without extension
                            async for media_message in self.client.iter_messages(
                                message.chat_id,
                                search=base_filename,  # Search for messages containing the filename
                                filter=InputMessagesFilterPhotos,  # Filter for photos only
                                limit=5,  # Look at a few messages around to find the preview
                            ):
                                if (
                                    media_message.photo
                                    and base_filename in media_message.text
                                ):
                                    image_path = (
                                        file_path.parent / f"{base_filename}.jpg"
                                    )
                                    await media_message.download_media(image_path)
                                    self.logger.info(
                                        f"Successfully downloaded preview image: {image_path}"
                                    )
                                    break
                                else:
                                    # Get preview image
                                    await self.get_preview_image(message.file.name)

                            self.random_delay()
                        except Exception as e:
                            self.logger.error(
                                f"Failed to download {message.file.name}: {str(e)}"
                            )
                            continue
                except Exception as e:
                    self.logger.error(f"Error processing message: {str(e)}")
                    continue

        except Exception as e:
            self.logger.error(f"Error during download process: {str(e)}")
            raise

        return downloaded_files

    async def get_preview_image(self, zip_filename: str) -> Optional[Path]:
        """
        Fetch preview image from 3dsky.org for a given filename.

        Args:
            zip_filename: Name of the ZIP file

        Returns:
            Path to saved preview image if successful, None otherwise
        """
        file_base_name = Path(zip_filename).stem

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            # Search on 3dsky.org
            search_url = f"https://3dsky.org/search?query={file_base_name}"
            print(search_url)
            print(file_base_name)
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Target the specific Angular structure we found
            image_tag = soup.select_one("app-model-card img[applazyload]")

            if not image_tag or "src" not in image_tag.attrs:
                self.logger.warning(f"No preview image found for {zip_filename}")
                return None

            # Download preview image
            image_url = image_tag["src"]
            if not image_url.startswith("http"):
                image_url = f"https://3dsky.org{image_url}"

            image_response = requests.get(
                image_url, headers=headers, stream=True, timeout=10
            )
            image_response.raise_for_status()

            preview_path = self.download_path / f"{file_base_name}_preview.jpg"
            with open(preview_path, "wb") as f:
                for chunk in image_response.iter_content(8192):
                    f.write(chunk)

            self.logger.info(f"Successfully downloaded preview for {zip_filename}")
            return preview_path

        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch preview for {zip_filename}: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(
                f"Unexpected error while fetching preview for {zip_filename}: {str(e)}"
            )
            return None


async def main():
    """
    Main function to initialize the Telegram downloader and download files from a specified channel.

    This function:
    - Loads API credentials from environment variables.
    - Initializes the TelegramDownloader instance with the given credentials.
    - Connects to the Telegram service.
    - Retrieves the channel URL from the environment or user input.
    - Downloads files from the specified Telegram channel based on optional filters.

    The function demonstrates downloading files without filters and prints the number of files downloaded.

    Note: Adjust the date_filter and file_name_filter in the function call to apply specific filters as needed.
    """
    api_id = os.getenv("API_ID", None)
    if not api_id:
        api_id = input("Enter your API ID: ")

    api_hash = os.getenv("API_HASH", None)
    if not api_hash:
        api_hash = input("Enter your API HASH: ")

    downloader = TelegramDownloader(api_id=int(api_id), api_hash=api_hash)

    try:
        # Connect using existing session or create new one
        if not await downloader.connect():
            print("Failed to connect to Telegram")
            return

        channel_url = os.getenv("CHANNEL_URL") or input("Enter the channel URL: ")

        # Your download logic here
        downloaded_files = await downloader.download_files(
            channel_url=channel_url,
            date_filter=None,
            file_name_filter=None,
            before_after="before",
            limit=None,
        )

        print(f"Downloaded {len(downloaded_files)} files")
        await downloader.disconnect()

    except (KeyboardInterrupt, SystemExit):
        print("\nOperation cancelled by user")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
    finally:
        # Always disconnect properly
        await downloader.disconnect()  # type: ignore


if __name__ == "__main__":
    load_dotenv()
    import asyncio

    asyncio.run(main())
