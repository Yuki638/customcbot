"""YouTube videos: captions when they exist, speech-to-text when they do not."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .chunking import Unit

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_NOISE = re.compile(r"\[(?:music|applause|laughter|música|musik)\]", re.I)


class YouTubeError(Exception):
    """Something the user should be told about in plain words."""


def video_id(url: str) -> str | None:
    """Pull the video id out of any common YouTube link."""
    url = url.strip()
    if _ID.match(url):
        return url
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            match = re.match(r"^/(?:shorts|embed|live|v)/([^/?#]+)", parsed.path)
            candidate = match.group(1) if match else ""
    else:
        return None
    return candidate if _ID.match(candidate) else None


def is_playlist(url: str) -> bool:
    parsed = urlparse(url if "://" in url else "https://" + url)
    return "list" in parse_qs(parsed.query) and (parsed.path == "/playlist" or video_id(url) is None)


def watch_url(vid: str, start_sec: float | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={vid}"
    return f"{url}&t={int(start_sec)}s" if start_sec else url


def expand_playlist(url: str) -> list[tuple[str, str]]:
    """Return (video id, title) for every video in a playlist."""
    import yt_dlp

    options = {"extract_flat": True, "quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp raises many unrelated error types
        raise YouTubeError(f"Could not read that playlist: {_short(exc)}") from exc
    entries = [e for e in (info or {}).get("entries") or [] if e and e.get("id")]
    return [(e["id"], e.get("title") or f"YouTube video {e['id']}") for e in entries]


def fetch_title(vid: str) -> str | None:
    try:
        response = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": watch_url(vid), "format": "json"},
            timeout=10,
        )
        return response.raise_for_status().json().get("title")
    except (httpx.HTTPError, ValueError):
        return None


def fetch_captions(vid: str) -> list[Unit] | None:
    """Return caption lines with timestamps, or None when the video has no captions."""
    from youtube_transcript_api import (
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApi,
        YouTubeTranscriptApiException,
    )

    api = YouTubeTranscriptApi()
    try:
        transcripts = list(api.list(vid))
        if not transcripts:
            return None
        # Captions a person wrote are more accurate than automatic ones.
        chosen = next((t for t in transcripts if not t.is_generated), transcripts[0])
        fetched = chosen.fetch()
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except VideoUnavailable as exc:
        raise YouTubeError("That video is unavailable or private.") from exc
    except (RequestBlocked, IpBlocked) as exc:
        raise YouTubeError(
            "YouTube refused the request from this network. This usually happens on "
            "servers and VPNs; it works from a normal home or campus connection."
        ) from exc
    except YouTubeTranscriptApiException as exc:
        raise YouTubeError(f"Could not get captions: {_short(exc)}") from exc

    units = []
    for snippet in fetched:
        text = _NOISE.sub("", snippet.text.replace("\n", " ")).strip()
        if text:
            units.append(Unit(text=text, start_sec=float(snippet.start), method="captions"))
    return units or None


def download_audio(vid: str, folder: Path) -> Path:
    """Fetch the audio track in its original format (no ffmpeg needed)."""
    import yt_dlp

    folder.mkdir(parents=True, exist_ok=True)
    options = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(folder / "audio.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(watch_url(vid), download=True)
            return Path(ydl.prepare_filename(info))
    except Exception as exc:
        raise YouTubeError(
            f"This video has no captions and its audio could not be downloaded: {_short(exc)}"
        ) from exc


def _short(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
