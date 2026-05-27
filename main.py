"""
main.py — YouTube → Telegram transcript bot
Runs every 5 minutes via GitHub Actions.
No paid APIs required.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
import requests
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── File paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CHANNELS_FILE = BASE_DIR / "channels.json"
POSTED_FILE = BASE_DIR / "posted.json"

# ── Constants ─────────────────────────────────────────────────────────────────
YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TELEGRAM_CHARS = 4000   # Telegram limit is 4096; we use 4000 for safety
TRANSCRIPT_PREVIEW_CHARS = 500


# ══════════════════════════════════════════════════════════════════════════════
#  Config helpers
# ══════════════════════════════════════════════════════════════════════════════

def load_channels() -> list[dict]:
    """Load channel list from channels.json."""
    if not CHANNELS_FILE.exists():
        log.error(f"{CHANNELS_FILE} not found.")
        sys.exit(1)
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    channels = data if isinstance(data, list) else data.get("channels", [])
    log.info(f"Loaded {len(channels)} channel(s).")
    return channels


def load_posted() -> set[str]:
    """Load already-posted video IDs from posted.json."""
    if not POSTED_FILE.exists():
        return set()
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_posted(posted_ids: set[str]) -> None:
    """Save video IDs to posted.json."""
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(posted_ids), f, indent=2)
    log.debug(f"Saved {len(posted_ids)} posted IDs.")


def get_env(key: str) -> str:
    """Get required environment variable or exit."""
    value = os.getenv(key, "").strip()
    if not value:
        log.error(f"Missing environment variable: {key}")
        sys.exit(1)
    return value


# ══════════════════════════════════════════════════════════════════════════════
#  YouTube helpers
# ══════════════════════════════════════════════════════════════════════════════

def fetch_latest_video(channel_id: str) -> Optional[dict]:
    """
    Fetch the latest video from a channel's RSS feed.
    Returns a dict with video details, or None on failure.
    """
    url = YT_RSS_URL.format(channel_id=channel_id)
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            log.warning(f"No entries in RSS feed for channel: {channel_id}")
            return None

        entry = feed.entries[0]  # Latest video is always first

        # Extract video ID from the yt:videoId tag or the link
        video_id = entry.get("yt_videoid") or _extract_id_from_link(entry.get("link", ""))
        if not video_id:
            log.warning(f"Could not extract video ID for channel {channel_id}")
            return None

        # Channel name from feed
        channel_name = feed.feed.get("title", "Unknown Channel")

        # Published time
        published_raw = entry.get("published", "")
        published_pretty = _format_published(entry.get("published_parsed"))

        return {
            "video_id": video_id,
            "title": entry.get("title", "No Title"),
            "link": entry.get("link", f"https://youtube.com/watch?v={video_id}"),
            "channel_name": channel_name,
            "channel_id": channel_id,
            "published": published_pretty,
        }

    except Exception as e:
        log.error(f"RSS fetch error for {channel_id}: {e}")
        return None


def _extract_id_from_link(link: str) -> Optional[str]:
    """Extract video ID from a YouTube URL."""
    if "v=" in link:
        return link.split("v=")[-1].split("&")[0]
    if "youtu.be/" in link:
        return link.split("youtu.be/")[-1].split("?")[0]
    return None


def _format_published(parsed_time) -> str:
    """Convert time.struct_time to a readable string."""
    if not parsed_time:
        return "Unknown time"
    try:
        dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
        return dt.strftime("%B %d, %Y at %H:%M UTC")
    except Exception:
        return "Unknown time"


def fetch_transcript(video_id: str) -> Optional[str]:
    """
    Try to fetch the video transcript.
    Returns clean text string, or None if unavailable.
    """
    try:
        # Try to get transcript — prefers English, then any language
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = None
        # 1. Try manual English transcript
        try:
            transcript = transcript_list.find_manually_created_transcript(["en"])
        except Exception:
            pass

        # 2. Try auto-generated English
        if not transcript:
            try:
                transcript = transcript_list.find_generated_transcript(["en"])
            except Exception:
                pass

        # 3. Any available transcript
        if not transcript:
            try:
                transcript = transcript_list.find_transcript(
                    [t.language_code for t in transcript_list]
                )
            except Exception:
                pass

        if not transcript:
            return None

        # Fetch and join all segments into plain text
        segments = transcript.fetch()
        text = " ".join(seg["text"] for seg in segments)

        # Clean up common artefacts like [Music], [Applause]
        import re
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    except (NoTranscriptFound, TranscriptsDisabled):
        log.info(f"No transcript available for {video_id}")
        return None
    except VideoUnavailable:
        log.warning(f"Video unavailable: {video_id}")
        return None
    except Exception as e:
        log.error(f"Transcript error for {video_id}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Telegram helpers
# ══════════════════════════════════════════════════════════════════════════════

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """
    Send a single Telegram message (MarkdownV2 format).
    Returns True on success.
    """
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",          # HTML is more forgiving than MarkdownV2
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return True
    except requests.HTTPError as e:
        log.error(f"Telegram HTTP error: {e} — response: {resp.text[:200]}")
        return False
    except Exception as e:
        log.error(f"Telegram send error: {e}")
        return False


def send_long_message(token: str, chat_id: str, text: str) -> bool:
    """
    Split and send a long message in chunks.
    Splits at sentence boundaries to keep text readable.
    Returns True if all chunks sent successfully.
    """
    if len(text) <= MAX_TELEGRAM_CHARS:
        return send_telegram(token, chat_id, text)

    chunks = _split_text(text, MAX_TELEGRAM_CHARS)
    log.info(f"Message split into {len(chunks)} parts.")

    for i, chunk in enumerate(chunks, 1):
        # Add part indicator for multi-part messages
        labeled = f"<b>— Part {i}/{len(chunks)} —</b>\n\n{chunk}"
        success = send_telegram(token, chat_id, labeled)
        if not success:
            log.error(f"Failed to send part {i}/{len(chunks)}")
            return False
        if i < len(chunks):
            time.sleep(1)  # Small delay to avoid Telegram rate limits

    return True


def _split_text(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks at sentence boundaries ('. ') or newlines.
    Falls back to hard split if no boundary found.
    """
    chunks = []
    while len(text) > max_chars:
        # Try to find a sentence end near the limit
        split_at = text.rfind(". ", 0, max_chars)
        if split_at == -1:
            split_at = text.rfind("\n", 0, max_chars)
        if split_at == -1:
            split_at = max_chars  # Hard cut as last resort

        chunks.append(text[: split_at + 1].strip())
        text = text[split_at + 1:].strip()

    if text:
        chunks.append(text)
    return chunks


def build_telegram_message(video: dict, transcript: Optional[str]) -> str:
    """
    Build the full Telegram message from video details and transcript.
    Uses HTML formatting.
    """
    title = _escape_html(video["title"])
    channel = _escape_html(video["channel_name"])
    link = video["link"]
    published = _escape_html(video["published"])

    lines = [
        "🎬 <b>New YouTube Video!</b>",
        "",
        f"📺 <b>Channel:</b> {channel}",
        f"🎥 <b>Title:</b> {title}",
        f"🔗 <b>Link:</b> {link}",
        f"🕐 <b>Published:</b> {published}",
    ]

    if transcript:
        preview = transcript[:TRANSCRIPT_PREVIEW_CHARS].strip()
        if len(transcript) > TRANSCRIPT_PREVIEW_CHARS:
            preview += "…"

        lines += [
            "",
            "📝 <b>Transcript Preview:</b>",
            f"<i>{_escape_html(preview)}</i>",
            "",
            "—" * 20,
            "",
            "📄 <b>Full Transcript:</b>",
            _escape_html(transcript),
        ]
    else:
        lines += [
            "",
            "⚠️ <b>Transcript:</b> Not available for this video.",
            "<i>You can try the YouTube auto-captions on the video page.</i>",
        ]

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape special HTML characters for Telegram HTML mode."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("=" * 50)
    log.info("YT→Telegram bot starting")
    log.info("=" * 50)

    # Load credentials from environment
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")

    # Load config files
    channels = load_channels()
    posted_ids = load_posted()

    new_videos_found = 0

    for channel in channels:
        channel_id = channel.get("id", "").strip()
        if not channel_id:
            log.warning(f"Skipping channel entry with missing id: {channel}")
            continue

        log.info(f"Checking channel: {channel_id}")

        # Fetch latest video from RSS
        video = fetch_latest_video(channel_id)
        if not video:
            log.warning(f"Could not fetch video for channel {channel_id}")
            continue

        video_id = video["video_id"]
        log.info(f"Latest video: [{video_id}] {video['title'][:60]}")

        # Skip if already posted
        if video_id in posted_ids:
            log.info(f"Already posted — skipping {video_id}")
            continue

        log.info(f"New video found! Fetching transcript …")

        # Fetch transcript
        transcript = fetch_transcript(video_id)
        if transcript:
            log.info(f"Transcript fetched: {len(transcript)} chars")
        else:
            log.info("No transcript available — will notify anyway")

        # Build and send Telegram message
        message = build_telegram_message(video, transcript)
        log.info(f"Sending to Telegram (message length: {len(message)} chars) …")

        success = send_long_message(bot_token, chat_id, message)

        if success:
            posted_ids.add(video_id)
            save_posted(posted_ids)
            new_videos_found += 1
            log.info(f"✅ Sent and saved: {video_id}")
        else:
            log.error(f"❌ Failed to send message for {video_id}")

        # Polite pause between channels
        time.sleep(1)

    log.info(f"Done. {new_videos_found} new video(s) sent.")


if __name__ == "__main__":
    main()
