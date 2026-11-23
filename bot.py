"""Telegram audio-to-voice-message converter."""

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain how to use the bot."""
    await update.message.reply_text(
        "Пришлите мне аудиофайл MP3, WAV или OGG — я верну его как голосовое сообщение."
    )


def input_file_from_message(update: Update):
    """Return the Telegram file and a safe extension, or (None, None)."""
    message = update.message
    if message.audio:
        return message.audio, Path(message.audio.file_name or "audio.mp3").suffix.lower()
    if message.voice:
        return message.voice, ".ogg"
    if message.document:
        return message.document, Path(message.document.file_name or "").suffix.lower()
    return None, None


def convert_to_voice(source: Path, destination: Path) -> None:
    """Create an OGG/Opus file accepted by Telegram as a voice message."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            "-vbr",
            "on",
            "-application",
            "voip",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download, transcode, and return supported audio as a voice message."""
    telegram_file, extension = input_file_from_message(update)
    if telegram_file is None or extension not in SUPPORTED_EXTENSIONS:
        await update.message.reply_text("Поддерживаются только файлы MP3, WAV и OGG.")
        return

    status = await update.message.reply_text("Конвертирую аудио…")
    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)

    try:
        remote_file = await context.bot.get_file(telegram_file.file_id)
        with tempfile.TemporaryDirectory(prefix="voice_converter_") as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / f"source{extension}"
            result = temp_path / "voice.ogg"
            await remote_file.download_to_drive(custom_path=source)
            await asyncio.to_thread(convert_to_voice, source, result)
            with result.open("rb") as voice:
                await update.message.reply_voice(voice=voice)
        await status.delete()
    except subprocess.CalledProcessError as error:
        logger.warning("ffmpeg could not convert a file: %s", error.stderr)
        await status.edit_text("Не получилось обработать этот файл. Проверьте, что он не повреждён.")
    except Exception:
        logger.exception("Audio conversion failed")
        await status.edit_text("Возникла ошибка при обработке файла. Попробуйте ещё раз.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required. Add it to the .env file.")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.ALL, handle_audio)
    )
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
