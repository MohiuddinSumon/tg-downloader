import asyncio
import json
import logging
import os
import random
import signal
import time
from asyncio import Queue, Task
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

import pytz
import requests
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
    TelegramDownloader class for downloading files from Telegram channels with concurrent downloads.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "downloader_session",
        download_path: Union[str, Path] = os.getenv(
            "DOWNLOAD_BASE_PATH", "./downloads"
        ),
        log_level: int = logging.INFO,
        max_concurrent_downloads: int = 3,
        min_delay: float = 3.0,
        max_delay: float = 10.0,
    ):
        """
        Initialize the Telegram downloader.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_name: Name for the Telegram session
            download_path: Path where files will be saved
            log_level: Logging level (default: logging.INFO)
            max_concurrent_downloads: Maximum number of concurrent downloads (default: 3)
            min_delay: Minimum delay between downloads (seconds)
            max_delay: Maximum delay between downloads (seconds)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.base_download_path = Path(download_path)
        self.base_download_path.mkdir(parents=True, exist_ok=True)
        self.current_channel_path: Optional[Path] = None
        self.last_download_file: Optional[Path] = None
        self.session_name = session_name
        self.session_file = Path(f"{session_name}.session")
        self.max_concurrent_downloads = max_concurrent_downloads
        self.download_queue: Queue = Queue()
        self.active_downloads: Set[Task] = set()
        self.min_delay = min_delay
        self.max_delay = max_delay

        self.api_url = "https://3dsky.org/api/models"
        self.image_base_url = (
            "https://b6.3ddd.ru/media/cache/tuk_model_custom_filter_ang_en/"
        )

        # for error handling
        self.shutdown_event = asyncio.Event()
        self.failed_downloads: Set[Path] = set()
        self.in_progress_downloads: Dict[Path, datetime] = {}

        # Create logs directory
        self.logs_path = self.base_download_path / "logs"
        self.logs_path.mkdir(parents=True, exist_ok=True)

        # Get today's log file name
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.logs_path / f"downloader_{today}.log"

        # Setup logging with daily log file
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)
        self.client = TelegramClient(session_name, api_id, api_hash)

    async def download_preview_image(
        self, message: Message, file_path: Path
    ) -> Optional[Path]:
        """Download preview image from the message or from 3dsky.org."""
        base_filename = file_path.stem

        try:
            # First try to find preview in Telegram
            async for media_message in self.client.iter_messages(
                message.chat_id,
                search=base_filename,
                filter=InputMessagesFilterPhotos,
                limit=5,
            ):
                if media_message.photo and base_filename in (media_message.text or ""):
                    image_path = file_path.parent / f"{base_filename}.jpg"
                    await media_message.download_media(image_path)
                    self.logger.info(
                        f"Successfully downloaded Telegram preview image: {image_path}"
                    )
                    return image_path

            # If no preview found in Telegram, try 3dsky.org
            return await self.get_preview_image(file_path.name, message.chat_id)

        except Exception as e:
            self.logger.error(
                f"Error downloading preview image for {base_filename}: {str(e)}"
            )
            return None

    async def cleanup_incomplete_downloads(self):
        """Clean up any incomplete or zero-byte downloads."""
        if not self.current_channel_path:
            return

        self.logger.info("Cleaning up incomplete downloads...")

        # Clean up files that were in progress
        for file_path in self.in_progress_downloads.keys():
            if file_path.exists():
                try:
                    if (
                        file_path.stat().st_size == 0
                        or file_path in self.failed_downloads
                    ):
                        file_path.unlink()
                        self.logger.info(f"Removed incomplete download: {file_path}")

                        # Also remove any associated preview file
                        preview_path = file_path.parent / f"{file_path.stem}.jpg"
                        if preview_path.exists():
                            preview_path.unlink()
                            self.logger.info(
                                f"Removed associated preview: {preview_path}"
                            )
                except Exception as e:
                    self.logger.error(f"Error cleaning up file {file_path}: {str(e)}")

    async def download_worker(self, worker_id: int):
        """Worker function to process downloads from the queue."""
        while not self.shutdown_event.is_set():
            try:
                # Get the next download task from the queue
                try:
                    message, file_path = await asyncio.wait_for(
                        self.download_queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                self.in_progress_downloads[file_path] = datetime.now()
                success = False

                try:
                    # Add delay before starting new download
                    self.logger.info(
                        f"Worker {worker_id} waiting for delay before starting download..."
                    )
                    await self.random_delay()
                    self.logger.info(
                        f"Worker {worker_id} downloading: {message.file.name}"
                    )

                    # Create temporary file path
                    temp_file_path = file_path.with_suffix(f"{file_path.suffix}.tmp")

                    def progress_callback(current, total):
                        current_mb = current / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        print(
                            f"Worker {worker_id} - {message.file.name}: {current_mb:.2f}MB/{total_mb:.2f}MB ({(current/total)*100:.1f}%)"
                        )

                    # Download to temporary file first (, progress_callback=progress_callback)
                    await message.download_media(temp_file_path)

                    # Verify the download
                    if (
                        not temp_file_path.exists()
                        or temp_file_path.stat().st_size == 0
                    ):
                        raise Exception("Download failed or file is empty")

                    # If successful, rename to final filename
                    temp_file_path.rename(file_path)

                    # Download preview and save download info only if main file download succeeded
                    # Add delay before preview download
                    self.logger.info(
                        f"Worker {worker_id} waiting for delay before preview download..."
                    )
                    await self.random_delay()
                    preview_path = await self.get_preview_image(
                        message.file.name, message.chat_id
                    )

                    if preview_path:
                        self.logger.info(
                            f"Worker {worker_id} downloaded preview: {preview_path}"
                        )

                    self.save_last_download_info(message)
                    success = True

                except Exception as e:
                    self.logger.error(
                        f"Worker {worker_id} failed to download {message.file.name}: {str(e)}"
                    )
                    self.failed_downloads.add(file_path)
                    # Signal shutdown if it's a connection error
                    if "Connection" in str(e) or "NetworkError" in str(e):
                        self.logger.error(
                            "Network error detected, initiating shutdown..."
                        )
                        self.shutdown_event.set()

                finally:
                    # Cleanup if download failed
                    if not success:
                        for path in [file_path, temp_file_path]:
                            try:
                                if path.exists():
                                    path.unlink()
                                    self.logger.info(
                                        f"Cleaned up failed download: {path}"
                                    )
                            except Exception as e:
                                self.logger.error(f"Error cleaning up {path}: {str(e)}")

                    del self.in_progress_downloads[file_path]
                    # Mark the task as done
                    self.download_queue.task_done()

            except Exception as e:
                self.logger.error(f"Worker {worker_id} encountered error: {str(e)}")
                await asyncio.sleep(1)  # Prevent tight loop on persistent errors

    async def find_reference_message(
        self, channel, file_name_filter: str
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Find a specific message containing the file name to use as a reference point.

        Returns:
            Tuple of (reference message if found, message ID to start from)
        """

        try:
            async for message in self.client.iter_messages(
                channel,
                filter=InputMessagesFilterDocument,
                search=file_name_filter,
                limit=10,
            ):
                if (
                    message.file
                    and file_name_filter.lower() in message.file.name.lower()
                ):
                    self.logger.info(
                        f"Found reference file: {message.file.name} with message ID: {message.id} , message date: {message.date}"
                    )
                    return message, message.id

            self.logger.warning(
                f"Reference file '{file_name_filter}' not found in channel"
            )
            return None, None

        except Exception as e:
            self.logger.error(f"Error while searching for reference file: {str(e)}")
            return None, None

    async def download_files(
        self,
        channel_url: str,
        file_name_filter: Optional[str] = None,
        date_filter: Optional[datetime] = None,
        before_after: str = "after",
        limit: Optional[int] = None,
    ) -> List[Path]:
        """
        Download files concurrently from the specified channel with filtering options.
        """
        downloaded_files = []
        workers = []
        try:
            channel = await self.client.get_entity(channel_url)
            channel_name = channel.username or channel.title
            self.setup_channel_directory(channel_name)

            self.logger.info(f"Accessing channel: {channel.title}")

            # Initialize download queue and workers
            for i in range(self.max_concurrent_downloads):
                worker = asyncio.create_task(self.download_worker(i + 1))
                workers.append(worker)

            # Get environment date filters
            from_date_str = os.getenv("FROM_DATE")
            to_date_str = os.getenv("TO_DATE")

            reference_message = None
            reference_message_id = None
            offset_date = None

            # Priority 1: Date range from environment
            if from_date_str and to_date_str:
                from_date = datetime.fromisoformat(from_date_str).replace(
                    tzinfo=pytz.UTC
                )
                to_date = datetime.fromisoformat(to_date_str).replace(tzinfo=pytz.UTC)
                self.logger.info(f"Using date range filter: {from_date} to {to_date}")

                # Use the appropriate date as offset based on direction
                # offset_date is used to start the message iteration from
                offset_date = to_date if before_after == "before" else from_date
                self.logger.info(
                    f"Using offset date: {offset_date} with direction: {before_after}"
                )
            # Priority 2: File name filter
            elif file_name_filter:
                self.logger.info(f"Using file name filter: {file_name_filter}")
                reference_message, reference_message_id = (
                    await self.find_reference_message(channel, file_name_filter)
                )

            # Priority 3: Last download information
            else:
                last_download = self.get_last_download_info()
                # 0 is default value for message_id if no previous downloads
                reference_message_id = last_download.get("message_id", 0)
                before_after = last_download.get("direction_used", before_after)

            # Determine the correct message iteration parameters
            iter_params = {
                "limit": limit,
                "filter": InputMessagesFilterDocument,
                "reverse": before_after == "after",
            }

            if offset_date:
                iter_params["offset_date"] = offset_date
            elif reference_message_id:
                if before_after == "before":
                    # For "before", start from the reference ID and go backwards (older messages)
                    iter_params["offset_id"] = reference_message_id
                else:
                    # For "after", start from the reference ID and go forwards (newer messages)
                    # We need to add 1 to offset_id to exclude the reference message itself
                    iter_params["offset_id"] = reference_message_id + 1

            self.logger.info(
                f"Starting message iteration with parameters: {iter_params}"
            )

            # Determine the correct message iteration parameters
            iter_params = {
                "limit": limit,
                "filter": InputMessagesFilterDocument,
                "reverse": before_after == "after",
                # True for after (newer), False for before (older)
            }
            print(reference_message_id, iter_params)

            self.logger.info(
                f"Starting message iteration with parameters: {iter_params}"
            )
            self.logger.info(
                f"File will be downoaded in {self.base_download_path, self.current_channel_path}"
            )

            compressed_extensions = (
                ".zip",
                ".rar",
                ".7z",
                ".tar",
                ".tar.gz",
                ".tgz",
                ".tar.bz2",
                ".tbz",
                ".gz",
                ".bz2",
                ".xz",
                ".zipx",
                ".z",
            )

            async for message in self.client.iter_messages(channel, **iter_params):
                if self.shutdown_event.is_set():
                    self.logger.info("Shutdown event detected during message iteration")
                    break

                if message.file and message.file.name.endswith(compressed_extensions):
                    file_path = self.current_channel_path / message.file.name
                    preview_path = (
                        self.current_channel_path
                        / f"{Path(message.file.name).stem}.jpeg"
                    )

                    # Check if file exists and handle preview
                    if file_path.exists() and file_path.stat().st_size > 0:
                        self.logger.info(f"File exists: {message.file.name}")
                        if not preview_path.exists():
                            self.logger.info(
                                f"Missing preview for existing file: {message.file.name}"
                            )
                            await self.random_delay()
                            preview = await self.get_preview_image(
                                message.file.name, message.chat_id
                            )
                            if preview:
                                self.logger.info(
                                    f"Downloaded missing preview: {preview}"
                                )
                        downloaded_files.append(file_path)
                        continue
                    elif file_path.exists() and file_path.stat().st_size == 0:
                        self.logger.info(
                            f"File exists but is empty, removing: {message.file.name}"
                        )
                        file_path.unlink()

                    # Add download task to queue
                    await self.download_queue.put((message, file_path))
                    downloaded_files.append(file_path)

            # Now wait for downloads to complete or shutdown
            self.logger.info(
                "All messages queued, waiting for downloads to complete..."
            )

            while not self.download_queue.empty():
                if self.shutdown_event.is_set():
                    self.logger.info("Shutdown requested, stopping downloads...")
                    break
                await asyncio.sleep(1)

            # Wait for remaining downloads with timeout
            try:
                await asyncio.wait_for(self.download_queue.join(), timeout=30.0)
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for downloads to complete")
                self.shutdown_event.set()

        except Exception as e:
            self.logger.error(f"Error during download process: {str(e)}")
            self.shutdown_event.set()
        finally:
            # Cancel all workers
            for worker in workers:
                worker.cancel()

            # Wait for workers to complete
            await asyncio.gather(*workers, return_exceptions=True)

            # Clean up any incomplete downloads
            await self.cleanup_incomplete_downloads()

            # Reset state
            self.shutdown_event.clear()
            self.failed_downloads.clear()
            self.in_progress_downloads.clear()

        return downloaded_files

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
            "direction_used": os.getenv(
                "BEFORE_AFTER", "before"
            ),  # Changed to direction_used
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
            self.shutdown_event.set()
            await self.cleanup_incomplete_downloads()
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

    # def random_delay(self, min_seconds: float = 3.0, max_seconds: float = 10.0):
    async def random_delay(self):
        """Add random delay to avoid detection."""
        delay = random.uniform(self.min_delay, self.max_delay)
        self.logger.debug(f"Adding delay of {delay:.2f} seconds")
        await asyncio.sleep(delay)

    async def get_preview_image(
        self, zip_filename: str, chat_id: int
    ) -> Optional[Path]:
        """
        Fetch preview image for a given filename, first trying 3dsky.org API,
        then falling back to Telegram channel search if API fails.

        Args:
            zip_filename: Name of the ZIP file

        Returns:
            Path to saved preview image if successful, None otherwise
        """
        file_base_name = Path(zip_filename).stem

        # First try downloading from 3dsky API - don't specify extension
        preview_base_path = self.current_channel_path / file_base_name
        if api_preview := await self.download_preview_from_api(
            file_base_name, preview_base_path
        ):
            return api_preview

        # For Telegram fallback, use .jpg extension
        telegram_preview_path = self.current_channel_path / f"{file_base_name}.jpg"
        self.logger.info(
            f"3dsky API download failed for {zip_filename}, trying Telegram channel..."
        )
        return await self.download_preview_from_telegram(
            chat_id, file_base_name, telegram_preview_path
        )

    async def download_preview_from_api(
        self, file_id: str, preview_base_path: Path
    ) -> Optional[Path]:
        """
        Download preview image using 3dsky.org API.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
        }
        payload = {"query": file_id, "order": "relevance"}

        try:
            self.logger.info(
                f"Attempting to download preview from 3dsky API for {file_id}"
            )

            # Make API request
            response = requests.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data.get("data", {}).get("models"):
                self.logger.warning(f"No models found in API for {file_id}")
                return None

            # Get the first model's images
            model = data["data"]["models"][0]
            image_info = None

            # Find matching image and get its information
            for image in model.get("images", []):
                if image.get("file_name", "").startswith(file_id.split(".")[0]):
                    image_info = image
                    break

            if not image_info:
                self.logger.warning(f"No matching image found in API for {file_id}")
                return None

            # Get image path and extract extension from the file_name
            image_path = image_info.get("web_path")
            original_filename = image_info.get("file_name", "")
            extension = (
                Path(image_path).suffixes[-1] or ".jpeg"
            )  # Default to .jpeg if no extension

            self.logger.info(
                f"image_path: {image_path}, original_filename: {original_filename}, extension: {extension}"
            )

            # Construct full image URL and final preview path with correct extension
            image_url = f"{self.image_base_url}{image_path}"
            final_preview_path = preview_base_path.with_suffix(extension)

            if await self.download_image(image_url, final_preview_path):
                self.logger.info(
                    f"Successfully downloaded preview from API for {file_id}"
                )
                return final_preview_path

            return None

        except Exception as e:
            self.logger.error(
                f"Error downloading preview from API for {file_id}: {str(e)}"
            )
            return None

    async def download_image(self, image_url: str, destination: Path) -> bool:
        """
        Download image from URL with proper error handling and timeout.
        """
        try:
            self.logger.info(f"Downloading image from {image_url}, to {destination}")
            response = requests.get(image_url, stream=True, timeout=30)
            response.raise_for_status()

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self.logger.info(f"Successfully downloaded image to {destination}")
            return True

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout downloading image {image_url}")
            return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request error downloading image {image_url}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error downloading image {image_url}: {str(e)}"
            )
            return False

    async def download_preview_from_telegram(
        self, chat_id: int, file_base_name: str, preview_path: Path
    ) -> Optional[Path]:
        """
        Download preview image from Telegram channel.
        """
        try:

            async for media_message in self.client.iter_messages(
                chat_id,
                search=file_base_name,
                filter=InputMessagesFilterPhotos,
                limit=5,
            ):
                if media_message.photo and file_base_name in (media_message.text or ""):
                    await media_message.download_media(preview_path)
                    self.logger.info(
                        f"Successfully downloaded Telegram preview image: {preview_path}"
                    )
                    return preview_path

            # If not found, check the previous and next messages
            async for media_message in self.client.iter_messages(
                chat_id,
                limit=10,  # Check a few messages before and after
            ):
                # Check if the message is one before or after the current one
                if media_message.photo and (
                    file_base_name.lower() in (media_message.text or "").lower()
                ):
                    await media_message.download_media(preview_path)
                    self.logger.info(
                        f"Successfully downloaded Telegram preview image from nearby message: {preview_path}"
                    )
                    return preview_path

            self.logger.warning(f"No preview found in Telegram for {file_base_name}")
            return None

        except Exception as e:
            self.logger.error(
                f"Error downloading preview from Telegram for {file_base_name}: {str(e)}"
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

    # Configure number of concurrent downloads
    max_concurrent = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 3))
    min_delay = float(os.getenv("MIN_DELAY", 10))
    max_delay = float(os.getenv("MAX_DELAY", 30))
    download_path = os.getenv("DOWNLOAD_BASE_PATH")

    downloader = TelegramDownloader(
        api_id=int(api_id),
        api_hash=api_hash,
        max_concurrent_downloads=max_concurrent,
        min_delay=min_delay,
        max_delay=max_delay,
        download_path=download_path,
    )

    try:
        # Connect using existing session or create new one
        if not await downloader.connect():
            print("Failed to connect to Telegram")
            return

        channel_url = os.getenv("CHANNEL_URL") or input("Enter the channel URL: ")
        file_filter = os.getenv("FILE_NAME_FILTER", None)
        before_after = os.getenv("BEFORE_AFTER", "before")

        # Your download logic here
        downloaded_files = await downloader.download_files(
            channel_url=channel_url,
            date_filter=None,
            file_name_filter=file_filter,
            before_after=before_after,
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
