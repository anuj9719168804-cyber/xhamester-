"""xhamster_resolver.py — resolves an xHamster video URL to every
playable format yt-dlp can find for it, shaped into the same response
envelope the person asked to match (a real API response they'd seen
elsewhere: "links"/"m3u8_links"/"videoDetails"/"entitlement", credited
"Ak").

Two things from that original sample are deliberately NOT replicated:
  - Its "links"/"m3u8_links" URLs for HLS formats were wrapped in a
    "vidquickly://open?..." custom URI scheme (base64-encoded data/
    file_name/title inside) — that's some OTHER app's own proprietary
    deep-link format for opening a stream in ITS player, not a real,
    directly-playable URL. This returns yt-dlp's actual format URL
    instead (a real .m3u8/.mp4 link), since that's what's genuinely
    usable by a caller of THIS API.
  - Its "entitlement"/"isPro"/"gatedHd"/"lockReason" fields implement
    that other service's own login/subscription paywall (720p+ locked
    behind "signin"). This service has no such system, so nothing here
    is actually gated — every quality yt-dlp finds is included in
    "links"/"m3u8_links" — but the envelope fields are kept (with
    "allowed": true, no lock reasons) purely for shape-compatibility
    with anything already coded against that original response shape.
"""
import logging

import yt_dlp

logger = logging.getLogger("diskwala_api")


def is_xhamster_link(url: str) -> bool:
    return "xhamster" in url.lower()


def resolve_xhamster(url: str) -> dict:
    """Runs yt-dlp's extract_info (metadata only, skip_download) and
    buckets every format it finds into "links" (progressive, direct
    video files — MP4 and similar) or "m3u8_links" (HLS manifests),
    plus "audio_links" for any audio-only format. Every entry keeps
    yt-dlp's own URL as-is: no re-wrapping, no proprietary scheme, no
    gating. Raises on any yt-dlp failure (private/removed video, network
    error, etc.) — the /api/xhamster route below turns that into a 502
    with the error message, same pattern as this project's other routes."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        # xHamster serves separate progressive-MP4 and HLS format lists;
        # requesting both explicitly (rather than yt-dlp's default best-
        # match subset) is what makes "all quality yt-dlp gets" mean ALL
        # of them, not just the one yt-dlp would pick to actually play.
        "format": "all",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info.get("formats") or []
    links, m3u8_links, audio_links = [], [], []

    for f in formats:
        f_url = f.get("url")
        if not f_url:
            continue
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        height = f.get("height")
        is_hls = (f.get("protocol") or "").startswith("m3u8") or ".m3u8" in f_url.lower()
        is_audio_only = vcodec in (None, "none") and acodec not in (None, "none")

        if is_audio_only:
            audio_links.append({
                "title": f.get("format_note") or f.get("format_id") or "Audio",
                "url": f_url,
            })
            continue

        label = f"Video {height}p" if height else (f.get("format_note") or f.get("format_id") or "Video")
        if is_hls:
            m3u8_links.append({"title": f"{label} (HLS)", "url": f_url})
        else:
            links.append({"title": label, "url": f_url})

    # yt-dlp can report the same height as both a progressive and an HLS
    # variant, or the same format twice with a different CDN edge — keep
    # every one exactly as found rather than de-duplicating, since "all
    # quality" was asked for specifically, not just the unique ones.

    thumbnails = []
    seen = set()
    for t_url in [info.get("thumbnail")] + [t.get("url") for t in (info.get("thumbnails") or [])]:
        if t_url and t_url not in seen:
            thumbnails.append({"url": t_url})
            seen.add(t_url)

    return {
        "audio_links": audio_links,
        "entitlement": {
            "adsAllowed": True,
            "countdownSeconds": 0,
            "hd": {"allowed": True, "limit": 0, "remaining": 0, "resetsAt": None},
            "tier": "anon",
        },
        "isAuthenticated": False,
        "isPro": False,
        "links": links,
        "m3u8_links": m3u8_links,
        "tier": "anon",
        "videoDetails": {
            "lengthSeconds": info.get("duration"),
            "thumbnails": thumbnails,
            "title": info.get("title"),
        },
    }
