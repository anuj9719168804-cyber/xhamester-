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
import re
from urllib.parse import urlparse

import yt_dlp

logger = logging.getLogger("diskwala_api")


def _format_duration(seconds) -> str | None:
    """seconds -> "MM:SS", or "H:MM:SS" once it's an hour or longer —
    same convention YouTube/most players use for a duration label, since
    lengthSeconds alone (a raw int) isn't something a UI can just drop
    into a caption/badge without formatting it first. None in, None out
    (no duration known), so callers can still fall back on lengthSeconds
    alone the way they always could."""
    if seconds is None:
        return None
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    if total < 0:
        return None
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

# Mirrors yt-dlp's own yt_dlp.extractor.xhamster.XHamsterIE._DOMAINS list —
# not reproduced here as a raw copy-paste, but checked against it directly
# (https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/xhamster.py)
# since resolve_xhamster() (pure yt-dlp) can only actually resolve a URL
# whose host yt-dlp's OWN extractor recognizes: xhamster.com/.one/.desi,
# xhms.pro, numbered mirrors (xhamster2.com, xhamster42.desi, ...), and the
# xhday.com/xhvid.com alt-domains. Anchored against the URL's hostname
# (with any number of subdomain labels allowed in front, e.g. "www.",
# "m.", "es.") rather than yt-dlp's own regex being re-derived by hand, so
# this only needs updating here if/when yt-dlp adds another mirror.
_XHAMSTER_YTDLP_NATIVE_RE = re.compile(
    r"^(?:[\w-]+\.)*(?:xhamster\.(?:com|one|desi)|xhms\.pro|xhamster\d+\.(?:com|desi)|xhday\.com|xhvid\.com)$",
    re.IGNORECASE,
)

# A second, WIDER set: real xHamster clone/mirror domains that are NOT in
# yt-dlp's own _DOMAINS regex, so yt-dlp's XHamsterIE won't match them
# on its own — resolve_xhamster() below has to actively rewrite these to
# xhamster.com before handing off to yt-dlp (see that function's
# docstring). Confirmed as the same xHamster network (not guessed) via a
# maintained ad-block filter list that has to track real live mirrors to
# be useful — easylist/easylist#22752 lists every one of these as sharing
# xHamster's own page markup/ad slots — plus independent site-scanner
# write-ups on xhaccess.com specifically describing it as "a clone
# domain for xHamster... displays xHamster's branding, title, and meta
# description verbatim" and loading assets straight from xHamster's own
# xhcdn.com CDN. Same URL/ID shape as xhamster.com throughout
# (/videos/<slug>-<id>), which is what makes rewriting just the host safe.
_XHAMSTER_MIRROR_ONLY_RE = re.compile(
    r"^(?:[\w-]+\.)*(?:megaxh|xhopen|xhaccess|xhbranch\d*|xhbig|xhchannel|xhofficial|xhmoon\d*|xhspot|xhtotal|xhwide\d*)\.(?:com|net|desi)$",
    re.IGNORECASE,
)

_XHAMSTER_HOST_RE = re.compile(
    r"^(?:[\w-]+\.)*(?:"
    r"xhamster\.(?:com|one|desi)|xhms\.pro|xhamster\d+\.(?:com|desi)|xhday\.com|xhvid\.com"
    r"|(?:megaxh|xhopen|xhaccess|xhbranch\d*|xhbig|xhchannel|xhofficial|xhmoon\d*|xhspot|xhtotal|xhwide\d*)\.(?:com|net|desi)"
    r")$",
    re.IGNORECASE,
)


def is_xhamster_link(url: str) -> bool:
    """BUG FIX: this was `"xhamster" in url.lower()` — a crude substring
    check that both under- and over-matched relative to what
    resolve_xhamster() (pure yt-dlp, plus the mirror-host rewrite it now
    does — see its docstring) can actually resolve:
      - Under-matched: several confirmed xHamster mirror domains don't
        contain the substring "xhamster" at all (xhday.com, xhvid.com,
        xhms.pro — all yt-dlp-native; xhaccess.com, xhopen.com,
        megaxh.com, and others — all clone domains yt-dlp itself doesn't
        recognize, see _XHAMSTER_MIRROR_ONLY_RE above), so every one of
        them always failed this check and never reached resolve_xhamster()
        at all — a fully resolvable link 400'd as "unsupported" for no
        real reason.
      - Over-matched: ANY url containing "xhamster" anywhere in it passed
        this — including a path/query on a totally unrelated domain, e.g.
        some-redirector.example/out?to=https://xhamster.com/videos/x, or
        even just a title/query string mentioning the word. That would
        reach resolve_xhamster() and get handed straight to yt-dlp's
        extract_info() on a URL yt-dlp's own _VALID_URL would reject,
        producing a confusing yt-dlp error instead of this function's own
        clear "not a supported link" rejection.

    Now checks the URL's actual hostname (not the whole string) against
    the combined yt-dlp-native + confirmed-mirror host sets above."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return bool(_XHAMSTER_HOST_RE.match(host))


def resolve_xhamster(url: str) -> dict:
    """Runs yt-dlp's extract_info (metadata only, skip_download) and
    buckets every format it finds into "links" (progressive, direct
    video files — MP4 and similar) or "m3u8_links" (HLS manifests),
    plus "audio_links" for any audio-only format. Every entry keeps
    yt-dlp's own URL as-is: no re-wrapping, no proprietary scheme, no
    gating. Raises on any yt-dlp failure (private/removed video, network
    error, etc.) — the /api/xhamster route below turns that into a 502
    with the error message, same pattern as this project's other routes.

    BUG FIX: a link on one of the confirmed-mirror-but-not-yt-dlp-native
    domains (_XHAMSTER_MIRROR_ONLY_RE in is_xhamster_link() above —
    xhaccess.com and the like) used to get handed to yt-dlp completely
    unchanged. is_xhamster_link() accepting it doesn't mean yt-dlp's own
    XHamsterIE will: its _VALID_URL regex doesn't include these hosts at
    all, so extract_info() fell through to yt-dlp's generic extractor,
    which can't parse xHamster's JS-driven player and just raised
    "Unsupported URL" — passing this project's own domain check while
    still failing one step later, for a reason that had nothing to do
    with the video itself. These mirrors serve byte-identical pages to
    xhamster.com under the exact same /videos/<slug>-<id> URL shape (per
    site-scanner write-ups on xhaccess.com specifically: "displays
    xHamster's branding, title, and meta description verbatim" off
    xHamster's own xhcdn.com CDN) — a clone, not a different site with
    its own layout — so rewriting just the host to xhamster.com before
    calling yt-dlp is safe and keeps the path/query (and therefore the
    actual video ID) untouched."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host and not _XHAMSTER_YTDLP_NATIVE_RE.match(host):
        url = parsed._replace(netloc="xhamster.com").geturl()
        logger.info(f"[xhamster] mirror host {host!r} not recognized by yt-dlp natively, rewritten to xhamster.com")

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
    seen_hls_heights = set()

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

        # BUG FIX (3rd pass): "links" (progressive MP4) is no longer
        # populated at all — only "m3u8_links" (HLS) qualities are
        # wanted now, so a non-HLS video format is simply skipped rather
        # than collected into "links". The key itself stays in the
        # response shape (as an always-empty list) purely for
        # shape-compatibility with the original sample response this
        # envelope matches — see this file's module docstring.
        if not is_hls:
            continue

        # BUG FIX (2nd pass): the first fix here tried to keep BOTH an
        # H264 and an AV1 copy of every height distinct by codec — but
        # xHamster hands back several redundant CDN-edge mirrors of each
        # codec too (same codec, same height, different edge server), and
        # yt-dlp doesn't reliably set `vcodec` on the HLS variants that
        # come from those alternate-edge (ahcdn.com) URLs specifically —
        # only the "canonical" xhcdn.com ones. So codec-based deduping
        # only ever caught HALF the real duplicates: the two entries
        # missing `vcodec` both fell back to a coin-flip URL-text sniff
        # that doesn't find "h264"/"av1" in an ahcdn.com URL at all (no
        # codec hint in that URL shape), so codec_family stayed None for
        # both and neither got deduped against the other. Confirmed live:
        # 2160p (and effectively every height) still showed up twice.
        #
        # Simplified to what actually matters for a caller of this API:
        # ONE link per actual quality tier, full stop — codec, CDN edge,
        # and any other "different URL, same playable resolution"
        # distinction collapse to whichever format yt-dlp listed first
        # for that height. yt-dlp's own format order is its own
        # preference ranking, so "first" is already a reasonable one to
        # keep, not an arbitrary pick.
        if height:
            if height in seen_hls_heights:
                continue
            seen_hls_heights.add(height)

        label = f"Video {height}p" if height else (f.get("format_note") or f.get("format_id") or "Video")
        m3u8_links.append({"title": f"{label} (HLS)", "url": f_url})

    # NOTE on quality ceiling: nothing here caps resolution — every
    # height yt-dlp's extractor finds in the HLS master playlist is kept
    # (up to and including 2160p when the source has it). Whether 2160p
    # actually shows up depends entirely on what xHamster itself encoded
    # for THIS specific upload; not every video has a 4K rendition
    # available — one that only goes up to 1080p in the site's own player
    # will only ever report a max of 1080p here too, same as it would
    # from yt-dlp run directly against that URL with no options at all.

    thumbnails = []
    seen = set()
    for t_url in [info.get("thumbnail")] + [t.get("url") for t in (info.get("thumbnails") or [])]:
        if t_url and t_url not in seen:
            thumbnails.append({"url": t_url})
            seen.add(t_url)

    # Key order here is the actual JSON response's key order (dict
    # insertion order is preserved through json.dumps) — videoDetails
    # (title/thumbnail) now comes before links/m3u8_links so a consumer
    # reading the response top-down sees what the video IS before the
    # (often long) format lists.
    return {
        "videoDetails": {
            "lengthSeconds": info.get("duration"),
            "duration": _format_duration(info.get("duration")),
            "thumbnails": thumbnails,
            "title": info.get("title"),
        },
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
    }
