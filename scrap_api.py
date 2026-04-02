from __future__ import annotations

import json
import os
from functools import lru_cache
from flask import Blueprint, Flask, jsonify, request
import requests
from urllib.parse import parse_qs, urlparse

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests.exceptions import RequestException as CurlRequestException
except ImportError:
    curl_requests = None
    CurlRequestException = None

try:
    from yt_dlp import YoutubeDL
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except ImportError:
        ImpersonateTarget = None
except ImportError:
    YoutubeDL = None
    ImpersonateTarget = None


scrap_api = Blueprint("scrap_api", __name__)

DIRECT_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
    ".pdf",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
)

YTDLP_SUPPORTED_DOMAINS = (
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
)

BROWSER_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class UpstreamResolveError(RuntimeError):
    """Raised when the upstream provider rejects or drops the extraction request."""


REQUEST_EXCEPTIONS = (requests.RequestException,) + ((CurlRequestException,) if CurlRequestException else ())
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str) -> bool:
    value = os.getenv(name)
    return bool(value and value.strip().lower() in TRUTHY_ENV_VALUES)


def should_ignore_system_proxy() -> bool:
    return env_flag("SCRAP_DISABLE_SYSTEM_PROXY") or env_flag("SCRAP_IGNORE_SYSTEM_PROXY")


def get_cookie_file() -> str | None:
    value = os.getenv("SCRAP_COOKIE_FILE") or os.getenv("SCRAP_COOKIEFILE")
    if not value:
        return None

    value = value.strip()
    return value or None


def get_proxy_url() -> str | None:
    explicit_proxy = os.getenv("SCRAP_PROXY_URL")
    if explicit_proxy:
        return explicit_proxy

    if should_ignore_system_proxy():
        return None

    return (
        os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("http_proxy")
    )


def http_get(url: str, *, timeout: int, headers: dict, proxy_url: str | None = None):
    if curl_requests is not None and not (should_ignore_system_proxy() and not proxy_url):
        kwargs = {
            "timeout": timeout,
            "headers": headers,
            "impersonate": "chrome",
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        return curl_requests.get(url, **kwargs)

    with requests.Session() as session:
        if should_ignore_system_proxy() and not proxy_url:
            session.trust_env = False

        return session.get(
            url,
            timeout=timeout,
            headers=headers,
            proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None,
        )


def http_head(url: str, *, timeout: int, headers: dict, allow_redirects: bool, proxy_url: str | None = None):
    if curl_requests is not None and not (should_ignore_system_proxy() and not proxy_url):
        kwargs = {
            "timeout": timeout,
            "headers": headers,
            "allow_redirects": allow_redirects,
            "impersonate": "chrome",
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        return curl_requests.head(url, **kwargs)

    with requests.Session() as session:
        if should_ignore_system_proxy() and not proxy_url:
            session.trust_env = False

        return session.head(
            url,
            allow_redirects=allow_redirects,
            timeout=timeout,
            headers=headers,
            proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None,
        )


def parse_quality(value: str | None) -> int | str | None:
    if value is None:
        return None

    value = value.strip().lower()
    if not value:
        return None

    if value in {"best", "worst"}:
        return value

    if value.endswith("p"):
        value = value[:-1]

    if value.isdigit():
        return int(value)

    raise ValueError("quality must be a number like 360 or 720, or one of: best, worst")


def is_direct_by_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(DIRECT_EXTENSIONS)


def looks_like_downloadable_content(content_type: str | None) -> bool:
    if not content_type:
        return False
    content_type = content_type.lower()
    return any(
        token in content_type
        for token in (
            "video/",
            "audio/",
            "application/pdf",
            "application/zip",
            "image/",
            "application/octet-stream",
        )
    )


def should_try_social_extractor(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in YTDLP_SUPPORTED_DOMAINS)


def is_youtube_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def normalize_formats(info: dict) -> list[dict]:
    formats = []
    for fmt in info.get("formats") or []:
        fmt_url = fmt.get("url")
        if not fmt_url:
            continue

        height = fmt.get("height")
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")

        formats.append(
            {
                "format_id": fmt.get("format_id"),
                "url": fmt_url,
                "ext": fmt.get("ext"),
                "protocol": fmt.get("protocol"),
                "height": height,
                "width": fmt.get("width"),
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                "vcodec": vcodec,
                "acodec": acodec,
                "has_video": vcodec not in {None, "none"},
                "has_audio": acodec not in {None, "none"},
            }
        )
    return formats


def sort_formats(formats: list[dict]) -> list[dict]:
    preferred_protocols = {"https": 2, "http": 1}
    return sorted(
        formats,
        key=lambda fmt: (
            fmt["has_video"],
            fmt["has_audio"],
            fmt["height"] or 0,
            preferred_protocols.get(fmt["protocol"], 0),
            fmt["filesize"] or 0,
        ),
    )


def summarize_available_formats(formats: list[dict]) -> list[dict]:
    seen_keys = set()
    summarized = []

    for fmt in sort_formats(formats):
        key = (
            fmt.get("height"),
            fmt.get("ext"),
            fmt.get("has_video"),
            fmt.get("has_audio"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)

        summarized.append(
            {
                "format_id": fmt.get("format_id"),
                "quality": fmt.get("height"),
                "download_url": fmt.get("url"),
                "ext": fmt.get("ext"),
                "has_video": fmt.get("has_video"),
                "has_audio": fmt.get("has_audio"),
            }
        )

    return summarized


def pick_format(formats: list[dict], quality: int | str | None) -> dict | None:
    if not formats:
        return None

    ordered_formats = sort_formats(formats)
    video_formats = [fmt for fmt in ordered_formats if fmt["has_video"]]
    candidates = video_formats or ordered_formats

    if quality == "worst":
        return candidates[0]

    if quality == "best" or quality is None:
        return candidates[-1]

    exact_matches = [fmt for fmt in candidates if fmt["height"] == quality]
    if exact_matches:
        return exact_matches[-1]

    lower_or_equal = [fmt for fmt in candidates if fmt["height"] and fmt["height"] <= quality]
    if lower_or_equal:
        return lower_or_equal[-1]

    higher = [fmt for fmt in candidates if fmt["height"]]
    if higher:
        return higher[0]

    return candidates[-1]


def pick_download_url(info: dict, quality: int | str | None) -> tuple[str | None, dict | None]:
    formats = normalize_formats(info)
    selected_format = pick_format(formats, quality)
    if selected_format:
        return selected_format["url"], selected_format

    requested_downloads = info.get("requested_downloads") or []
    for item in requested_downloads:
        if item.get("url"):
            return item["url"], {
                "format_id": item.get("format_id"),
                "ext": item.get("ext"),
                "height": item.get("height"),
                "width": item.get("width"),
            }

    if info.get("url"):
        return info["url"], {
            "format_id": info.get("format_id"),
            "ext": info.get("ext"),
            "height": info.get("height"),
            "width": info.get("width"),
        }

    thumbnails = info.get("thumbnails") or []
    for thumb in reversed(thumbnails):
        if thumb.get("url"):
            return thumb["url"], {"ext": "image"}

    return None, None


def compact_exception(exc: Exception, limit: int = 240) -> str:
    message = " ".join(str(exc).split())
    if len(message) <= limit:
        return message
    return f"{message[: limit - 3]}..."


def build_upstream_error_message(attempt_errors: list[str]) -> str:
    message = (
        "Unable to resolve media URL from upstream provider after multiple extraction attempts. "
        + " | ".join(attempt_errors[-4:])
    )

    normalized_errors = " | ".join(attempt_errors).lower()
    hints = []

    if any(
        token in normalized_errors
        for token in (
            "connectionreseterror",
            "forcibly closed by the remote host",
            "connection aborted",
            "timed out",
            "transporterror",
        )
    ):
        hints.append("Likely cause: the hosting server egress IP/network is blocked or rate-limited by the social platform")

    if not get_proxy_url():
        hints.append("Set SCRAP_PROXY_URL to a residential/mobile proxy or another outbound IP")

    if (
        not should_ignore_system_proxy()
        and not os.getenv("SCRAP_PROXY_URL")
        and any(os.getenv(name) for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"))
    ):
        hints.append("If the host injects HTTP(S)_PROXY, try SCRAP_DISABLE_SYSTEM_PROXY=1")

    if not get_cookie_file():
        hints.append("For Facebook/Instagram and other protected pages, set SCRAP_COOKIE_FILE to an exported Netscape cookies.txt")

    if hints:
        message += ". Hints: " + "; ".join(hints[:3])

    return message


def infer_ext_from_mime_type(mime_type: str | None) -> str | None:
    if not mime_type:
        return None

    mime_type = mime_type.lower()
    if "mp4" in mime_type:
        return "mp4"
    if "webm" in mime_type:
        return "webm"
    if "mp3" in mime_type:
        return "mp3"
    if "m4a" in mime_type:
        return "m4a"
    return None


def extract_assigned_json(text: str, marker: str) -> dict | None:
    marker_index = text.find(marker)
    if marker_index == -1:
        return None

    json_start = text.find("{", marker_index)
    if json_start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(json_start, len(text)):
        char = text[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[json_start : index + 1])
                except json.JSONDecodeError:
                    return None

    return None


def build_format_from_watch_page(fmt: dict) -> dict | None:
    fmt_url = fmt.get("url")

    # Most watch pages expose at least one muxed format with a direct URL.
    # Cipher-only formats are skipped here because they need JS signature deciphering.
    if not fmt_url:
        cipher = fmt.get("signatureCipher") or fmt.get("cipher")
        if cipher:
            parsed_cipher = parse_qs(cipher)
            fmt_url = (parsed_cipher.get("url") or [None])[0]

    if not fmt_url:
        return None

    mime_type = fmt.get("mimeType")

    return {
        "format_id": fmt.get("itag"),
        "url": fmt_url,
        "ext": infer_ext_from_mime_type(mime_type),
        "protocol": "https",
        "height": fmt.get("height"),
        "width": fmt.get("width"),
        "filesize": int(fmt["contentLength"]) if str(fmt.get("contentLength", "")).isdigit() else None,
        "vcodec": None if "audio/" in (mime_type or "") else "unknown",
        "acodec": "unknown" if "audio/" in (mime_type or "") or "audioQuality" in fmt else None,
        "has_video": "audio/" not in (mime_type or ""),
        "has_audio": "audio/" in (mime_type or "") or "audioQuality" in fmt,
    }


def extract_youtube_watch_page_info(url: str) -> dict | None:
    proxy_url = get_proxy_url()
    response = http_get(
        url,
        timeout=20,
        headers=BROWSER_REQUEST_HEADERS,
        proxy_url=proxy_url,
    )
    response.raise_for_status()

    player_response = extract_assigned_json(response.text, "ytInitialPlayerResponse = ")
    if not player_response:
        player_response = extract_assigned_json(response.text, "var ytInitialPlayerResponse = ")
    if not player_response:
        return None

    streaming_data = player_response.get("streamingData") or {}
    raw_formats = (streaming_data.get("formats") or []) + (streaming_data.get("adaptiveFormats") or [])
    formats = [item for item in (build_format_from_watch_page(fmt) for fmt in raw_formats) if item]
    if not formats:
        return None

    video_details = player_response.get("videoDetails") or {}
    thumbnails = ((video_details.get("thumbnail") or {}).get("thumbnails") or [])

    return {
        "extractor": "youtube_watch_page",
        "title": video_details.get("title"),
        "webpage_url": url,
        "thumbnail": thumbnails[-1]["url"] if thumbnails else None,
        "formats": formats,
    }


@lru_cache(maxsize=1)
def get_impersonation_target():
    if YoutubeDL is None or ImpersonateTarget is None:
        return None

    try:
        target = ImpersonateTarget.from_str("chrome")
        with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as probe:
            if probe._impersonate_target_available(target):
                return target
    except Exception:
        return None

    return None


def build_ydl_profiles(url: str) -> list[tuple[str, dict]]:
    base_options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 20,
        "extractor_retries": 5,
        "retries": 3,
        "http_headers": BROWSER_REQUEST_HEADERS,
    }
    proxy_url = get_proxy_url()
    if proxy_url:
        base_options["proxy"] = proxy_url
    elif should_ignore_system_proxy():
        base_options["proxy"] = ""

    cookie_file = get_cookie_file()
    if cookie_file:
        base_options["cookiefile"] = cookie_file

    if not is_youtube_url(url):
        return [("default", base_options)]

    youtube_base = {
        **base_options,
        # Force IPv4 first. This avoids common datacenter/server issues with broken IPv6 routes.
        "source_address": "0.0.0.0",
    }
    profiles = [
        (
            "youtube_android_ipv4",
            {
                **youtube_base,
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            },
        ),
        (
            "youtube_ios_ipv4",
            {
                **youtube_base,
                "extractor_args": {"youtube": {"player_client": ["ios", "android", "web"]}},
            },
        ),
        ("youtube_default_ipv4", youtube_base),
    ]

    impersonation_target = get_impersonation_target()
    if impersonation_target is not None:
        profiles.insert(
            0,
            (
                "youtube_chrome_impersonation",
                {
                    **youtube_base,
                    "impersonate": impersonation_target,
                    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
                },
            ),
        )

    return profiles


def extract_social_info(url: str) -> dict | None:
    attempt_errors = []

    for profile_name, options in build_ydl_profiles(url):
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)

            if "entries" in info and info["entries"]:
                info = next((entry for entry in info["entries"] if entry), None)

            if info:
                return info
        except Exception as exc:
            attempt_errors.append(f"{profile_name}: {compact_exception(exc)}")

    if is_youtube_url(url):
        try:
            info = extract_youtube_watch_page_info(url)
            if info:
                return info
        except Exception as exc:
            attempt_errors.append(f"youtube_watch_page: {compact_exception(exc)}")

    if attempt_errors:
        raise UpstreamResolveError(build_upstream_error_message(attempt_errors))

    return None


def extract_social_download(url: str, quality: int | str | None) -> dict | None:
    if YoutubeDL is None:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp")

    info = extract_social_info(url)

    if not info:
        return None

    formats = normalize_formats(info)
    available_formats = summarize_available_formats(formats)
    available_qualities = sorted(
        {fmt["quality"] for fmt in available_formats if isinstance(fmt.get("quality"), int)}
    )
    available_downloads = [
        {
            "quality": fmt.get("quality"),
            "download_url": fmt.get("download_url"),
            "format_id": fmt.get("format_id"),
            "ext": fmt.get("ext"),
        }
        for fmt in available_formats
        if fmt.get("download_url")
    ]

    download_url, selected_format = pick_download_url(info, quality)
    if not download_url:
        return None

    return {
        "ok": True,
        "type": "social",
        "extractor": info.get("extractor"),
        "title": info.get("title"),
        "download_url": download_url,
        "requested_quality": quality or "best",
        "selected_quality": selected_format.get("height") if selected_format else None,
        "quality_matched_exactly": (
            isinstance(quality, int)
            and selected_format is not None
            and selected_format.get("height") == quality
        ),
        "format_id": selected_format.get("format_id") if selected_format else None,
        "ext": selected_format.get("ext") if selected_format else info.get("ext"),
        "webpage_url": info.get("webpage_url") or url,
        "thumbnail": info.get("thumbnail"),
        "available_qualities": available_qualities,
        "available_downloads": available_downloads,
        "available_formats": available_formats,
    }


def resolve_direct_url(url: str):
    if is_direct_by_extension(url):
        return (
            jsonify(
                {
                    "ok": True,
                    "type": "direct",
                    "download_url": url,
                }
            ),
            200,
        )

    proxy_url = get_proxy_url()
    response = http_head(
        url,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
        allow_redirects=True,
        proxy_url=proxy_url,
    )

    final_url = response.url
    content_type = response.headers.get("Content-Type")
    content_length = response.headers.get("Content-Length")

    if is_direct_by_extension(final_url) or looks_like_downloadable_content(content_type):
        return (
            jsonify(
                {
                    "ok": True,
                    "type": "direct",
                    "download_url": final_url,
                    "content_type": content_type,
                    "content_length": content_length,
                }
            ),
            200,
        )

    return (
        jsonify(
            {
                "ok": False,
                "type": "page",
                "message": "This URL is not a direct downloadable file.",
            }
        ),
        400,
    )


@scrap_api.get("/resolve")
def resolve():
    url = request.args.get("url", "").strip()
    quality_raw = request.args.get("quality")
    if not url:
        return jsonify({"error": "url is required"}), 400

    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify({"error": "invalid url"}), 400

    try:
        quality = parse_quality(quality_raw)

        if should_try_social_extractor(url):
            social_result = extract_social_download(url, quality)
            if social_result:
                return jsonify(social_result)

        return resolve_direct_url(url)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except UpstreamResolveError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    except REQUEST_EXCEPTIONS as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def register_scrap_api(app: Flask) -> Flask:
    if "scrap_api" not in app.blueprints:
        app.register_blueprint(scrap_api)
    return app


def create_app() -> Flask:
    app = Flask(__name__)
    register_scrap_api(app)
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
