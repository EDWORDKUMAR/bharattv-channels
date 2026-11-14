#!/usr/bin/env python3
"""Bharat TV Smart Bot v3.1 — India-first IPTV and premium sports discovery diagnostics.

Python 3.11+; only stdlib. GitHub Actions friendly. Preserves the existing
channels.json / channels.m3u *live channel* interface. Offline channels are
written to a separate report to avoid breaking Android player integrations.

Important: public community IPTV metadata does not confer redistribution rights.
Public premium candidates can be PROBED for diagnostics, not automatically republished.
The bot does not bypass authentication, DRM, tokens or geographic restrictions.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import ipaddress
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_BASE = 'https://iptv-org.github.io/api'
API_ENDPOINTS = {
    'channels': f'{API_BASE}/channels.json',
    'streams': f'{API_BASE}/streams.json',
    'feeds': f'{API_BASE}/feeds.json',
    'logos': f'{API_BASE}/logos.json',
    'blocklist': f'{API_BASE}/blocklist.json',
}
M3U_SOURCES = [
    ('IPTV-org India', 'https://iptv-org.github.io/iptv/countries/in.m3u'),
    *[(f'IPTV-org {language}', f'https://iptv-org.github.io/iptv/languages/{code}.m3u')
      for language, code in [
          ('Hindi','hin'), ('Tamil','tam'), ('Telugu','tel'), ('Malayalam','mal'),
          ('Kannada','kan'), ('Marathi','mar'), ('Bengali','ben'), ('Gujarati','guj'),
          ('Punjabi','pan'), ('Odia','ori'), ('Assamese','asm'), ('Bhojpuri','bho'),
          ('Urdu','urd')
      ]]
]
USER_AGENT = 'BharatTV-SmartBot/3.1 (+India feeds, sports diagnostics)'
WORKERS = max(4, min(40, int(os.getenv('SCAN_WORKERS', '24'))))
ALLOW_COMMUNITY_FTA = os.getenv('ALLOW_COMMUNITY_FTA', '0') == '1'
SPORTS_DISCOVERY = os.getenv('SPORTS_DISCOVERY', '1') == '1'
PREMIUM_DISCOVERY = os.getenv('PREMIUM_DISCOVERY', '1') == '1'
SPORTS_MAX_CANDIDATES = max(1, min(400, int(os.getenv('SPORTS_MAX_CANDIDATES', '160'))))
OUTPUT_JSON = Path('channels.json')
OUTPUT_M3U = Path('channels.m3u')
OFFLINE_JSON = Path('offline_channels.json')
REPORT_JSON = Path('scan_report.json')
SPORTS_REPORT_JSON = Path('sports_discovery.json')
SPORTS_TARGETS_JSON = Path(__file__).with_name('sports_targets.json')
MAX_TEXT = 1_000_000
MAX_PLAYLIST = 256_000
LANGUAGE_CODES = {name: code for code, name in [
    ('hin', 'Hindi'), ('eng', 'English'), ('tam', 'Tamil'), ('tel', 'Telugu'),
    ('mal', 'Malayalam'), ('kan', 'Kannada'), ('mar', 'Marathi'), ('ben', 'Bengali'),
    ('guj', 'Gujarati'), ('pan', 'Punjabi'), ('ori', 'Odia'), ('asm', 'Assamese'),
    ('bho', 'Bhojpuri'), ('urd', 'Urdu'),
]}

INDIAN_LANG_CODES: dict[str, str] = {
    "hin": "Hindi",
    "eng": "English",
    "tam": "Tamil",
    "tel": "Telugu",
    "kan": "Kannada",
    "mal": "Malayalam",
    "mar": "Marathi",
    "ben": "Bengali",
    "guj": "Gujarati",
    "pan": "Punjabi",
    "ori": "Odia",
    "ory": "Odia",
    "asm": "Assamese",
    "urd": "Urdu",
    "bho": "Bhojpuri",
    "nep": "Nepali",
    "kok": "Konkani",
    "san": "Sanskrit",
    "mai": "Maithili",
    "kas": "Kashmiri",
    "snd": "Sindhi",
}

# Only native regional/national Indian broadcast languages trigger non-.in diaspora discovery.
# English ("eng") / Urdu ("urd") / Nepali ("nep") are excluded here so global US/UK/EU/PK/NP
# feeds are not pulled unless the channel's own country/broadcast area is India ("IN" / "c/IN").
INDIAN_FEED_TRIGGER_LANGS: frozenset[str] = frozenset(INDIAN_LANG_CODES) - {"eng", "urd", "nep"}

DEAD_HOST_SUBSTRINGS: tuple[str, ...] = (
    "d1g8wgjurz8via.cloudfront.net",
    "103.151.60.162",
    "103.178.78.151",
    "103.175.73.12:8080",
    "103.135.253.32",
    "gpcdn.net",
    "dinesh29.com.np",
    "localhost",
    "127.0.0.1",
)

# ---------------------------------------------------------------------------
# 2. Strict Channel-Stream Mismatch Protection
# ---------------------------------------------------------------------------

def canonical_channel_key(name: str, tvg_id: str = "") -> str:
    """
    Produces an identity-safe key that preserves channel numbers, variants,
    and regional language qualifiers so distinct channels NEVER merge.
    """
    raw = (name or "").strip().lower()
    if not raw and tvg_id:
        raw = tvg_id.split("@")[0].replace(".in", "").lower()

    # Extract any meaningful language or variant inside parentheses before stripping resolution tags
    paren_tokens: list[str] = []
    for m in re.finditer(r"[\(\[]([^\)\]]+)[\)\]]", raw):
        inner = m.group(1).strip().lower()
        # Ignore pure resolution or status notes like (1080p), (1080i), (720p), [Not 24/7], [Geo-blocked]
        if re.fullmatch(r"\d{3,4}[pi]|hd|sd|fhd|4k|uhd|not\s*24/7|geo[-\s]*blocked|backup|mirror|india|in", inner):
            continue
        paren_tokens.append(re.sub(r"[^a-z0-9]+", "", inner))

    # Strip resolution/status brackets from main string
    cleaned = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", raw)

    # Normalize common aliases without losing identity
    cleaned = re.sub(r"\bset\s*max\b", "sonymax", cleaned)
    cleaned = re.sub(r"\bset\s*india\b", "sonyentertainmenttelevision", cleaned)
    cleaned = re.sub(r"\bsony\s*set\b", "sonyentertainmenttelevision", cleaned)
    cleaned = re.sub(r"\bsub\s*tv\b", "sonysab", cleaned)
    cleaned = re.sub(r"\bsab\s*tv\b", "sonysab", cleaned)
    cleaned = re.sub(r"&tv\b", "andtv", cleaned)

    # Remove only generic suffix tokens, NEVER remove numbers or 'sports'/'movies'/'news'
    cleaned = re.sub(r"\b(hd|sd|fhd|4k|india|official|live|stream)\b", " ", cleaned)
    # Remove trailing 'tv' or 'channel' only when the remaining name has >= 4 chars
    base_no_tv = re.sub(r"\b(tv|channel|television)\b", " ", cleaned)
    if len(re.sub(r"[^a-z0-9]", "", base_no_tv)) >= 4:
        cleaned = base_no_tv

    key = re.sub(r"[^a-z0-9]", "", cleaned)
    if paren_tokens:
        for pt in paren_tokens:
            if pt and pt not in key:
                key += "_" + pt
    return key


def is_cross_channel_mismatch(channel_name: str, stream_url: str, stream_title: str = "") -> bool:
    """
    Blocks streams that belong to a different TV network or channel from being
    assigned to `channel_name`. Fixes issues where SET Max played Zee Cinema
    or Star Sports 1 played a generic sports stream.
    """
    ck = canonical_channel_key(channel_name)
    url = (stream_url or "").strip().lower()
    stitle = (stream_title or "").strip().lower()

    if not url:
        return True
    if any(dead in url for dead in DEAD_HOST_SUBSTRINGS):
        return True

    # 1. Sony Max / SET Max must NEVER play Zee Cinema, Goldmines, or Colors Cineplex
    if "sonymax" in ck or "setmax" in ck:
        if any(bad in url for bad in ("zeecinema", "/live/53/", "colorscineplex", "b4u", "dangal", "shemaroo")):
            return True

    # 2. Star Sports 1 / Star Sports 2 / Star Sports Hindi must NEVER play generic unrelated feeds
    if "starsports" in ck:
        if any(bad in url for bad in (
            "b17adfe543354fdd8d189b110617cddd",
            "pishow.tv/ott/live/1161",
            "nellaiiptv.com/sdmedia",
            "sportsgrid",
            "cricketgold",
            "tennis2",
        )):
            return True
        if "starsports1" in ck and "starsports2" in url:
            return True
        if "starsports2" in ck and "starsports1" in url:
            return True

    # 3. Ten Sports / Sony Sports Ten / Eurosport must NEVER play generic DD/CricketGold feeds
    if "tensports" in ck or "sonyten" in ck or "eurosport" in ck:
        if any(bad in url for bad in (
            "b17adfe543354fdd8d189b110617cddd",
            "pishow.tv/ott/live/1161",
            "nellaiiptv.com/sdmedia",
        )):
            return True

    # 4. Sony SAB must NEVER play Colors, Dangal, Shemaroo, or Sony SET
    if "sonysab" in ck:
        if any(bad in url for bad in ("colorsapac", "colors", "live-dangal", "shemaroo", "/sonyhd/")):
            return True

    # 5. Star Gold must NEVER play Colors Cineplex or ektv FTA movie feeds
    if "stargold" in ck or "utsavgold" in ck:
        if any(bad in url for bad in ("colorscineplex", "/live/52/", "/live/47/", "/live/53/", "zeecinema")):
            return True

    # 6. Cartoon Network / Nickelodeon must NEVER play Animax or Green Gold
    if "cartoonnetwork" in ck or "nickelodeon" in ck or ck.startswith("nick"):
        if any(bad in url for bad in ("animax", "greengold", "grngld", "zillarbarta", "pishow.tv/ott/live/32")):
            return True

    # 7. Pogo / Sony YAY / Hungama / Discovery Kids must NEVER cross-play Green Gold or Animax
    if any(k in ck for k in ("pogo", "sonyyay", "hungama", "discoverykids", "gubbare")):
        if any(bad in url for bad in ("animax", "greengold", "grngld", "zillarbarta")):
            return True

    # 8. Zee TV must NEVER play Anand TV; B4U Movies must NEVER play B4U Bhojpuri; India TV must NEVER play Awaaz India
    if "zeetv" in ck and "anandtv" in url:
        return True
    if "b4umovies" in ck and "bhojpuri" in url:
        return True
    if "indiatv" in ck and "awaazind" in url:
        return True

    # 9. General URL-to-Network sanity guard: if URL explicitly names a rival channel
    rival_signatures = [
        ("zeecinema", ("zeecinema",)),
        ("colorsapac", ("colors",)),
        ("colorscineplex", ("colorscineplex",)),
        ("colorstamil", ("colorstamil",)),
        ("live-dangal2", ("dangal2",)),
        ("live-dangal.", ("dangal",)),
        ("b4u_bhojpuri", ("b4ubhojpuri",)),
        ("shemarootv", ("shemaroo",)),
        ("shemarooumang", ("shemarooumang",)),
        ("aajtakhd", ("aajtak",)),
        ("abpnews", ("abpnews",)),
        ("ndtvindia", ("ndtvindia",)),
        ("ndtv24x7", ("ndtv24x7", "ndtv")),
        ("republicbharat", ("republicbharat",)),
        ("timesnownavbharat", ("timesnownavbharat",)),
    ]
    for sig, allowed_keys in rival_signatures:
        if sig in url and not any(ak in ck for ak in allowed_keys):
            return True

    # 10. If stream_title is present and clearly belongs to a different channel
    if stitle:
        st_key = canonical_channel_key(stitle)
        if st_key and ck and st_key != ck and (len(st_key) >= 5 and st_key not in ck and ck not in st_key):
            return True

    return False


# ---------------------------------------------------------------------------
# 3. Category, Region, Zone & Tier (FTA vs Paid) Classification
# ---------------------------------------------------------------------------

PAID_BRAND_PATTERNS: tuple[str, ...] = (
    "star plus", "star gold", "star bharat", "star maa", "star vijay", "star jalsha",
    "star pravah", "star suvarna", "star kirano", "star sports", "utsav plus", "utsav gold",
    "utsav bharat", "sony", "set max", "sab tv", "ten sports", "pix", "bbc earth",
    "zee tv", "zee cinema", "zee cafe", "zee studio", "zee talkies", "zee marathi",
    "zee bangla", "zee tamil", "zee telugu", "zee kannada", "zee keralam", "zee punjabi",
    "zee sarthak", "zee picchar", "zee cinemalu", "zee thirai", "zee zest", "&tv", "and tv",
    "&pictures", "and pictures", "&flix", "and flix", "&privé",
    "colors", "mtv", "nick", "nickelodeon", "sonic", "vh1", "comedy central", "sports18",
    "cartoon network", "pogo", "wb channel", "warner", "hbo", "cnn",
    "disney", "hungama", "super hungama", "national geographic", "nat geo", "fox life",
    "discovery", "animal planet", "tlc", "eurosport", "investigation discovery",
    "discovery science", "science channel",
    "history tv18", "fyi tv18", "cnbc", "et now",
    "sun tv", "ktv", "adithya", "sun music", "sun life", "gemini", "udaya",
    "surya tv", "surya movies", "surya comedy", "surya music",
    "asianet", "mazhavil", "etv", "raj tv", "jaya tv", "polimer",
)

FTA_BRAND_PATTERNS: tuple[str, ...] = (
    "dd", "doordarshan", "sansad", "lok sabha", "rajya sabha", "all india radio",
    "star utsav", "zee anmol", "sony pal", "sony wah", "colors rishtey",
    "dangal", "shemaroo", "goldmines", "b4u", "enterr10", "manoranjan", "dhamaal",
    "mastiii", "9xm", "9x jalwa", "9x tashan", "9x jhakaas", "zoom", "showbox",
    "aaj tak", "abp", "india tv", "republic", "tv9", "ndtv india", "news18", "zee news",
    "zee bharat", "zee hindustan", "zee business", "good news today", "gnt", "news 24",
    "news nation", "india news", "sudarshan", "public tv", "otv", "kanak", "kalinga",
    "surya samachar", "ktv bangla", "etv bharat",
    "aastha", "sanskar", "sadhna", "ishwar", "paras", "peace of mind", "mh one",
    "ptc", "chardikla", "bhojpuri cinema", "fakt marathi", "faktananda",
)


def _compile_brand_regex(patterns: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(re.escape(p) for p in patterns)
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


_PAID_BRAND_RE = _compile_brand_regex(PAID_BRAND_PATTERNS)
_FTA_BRAND_RE = _compile_brand_regex(FTA_BRAND_PATTERNS)
_FTA_REGIONAL_NEWS_RE = re.compile(
    r"(?<!\w)(?:zee|asianet|polimer|etv|sun)\b.*\b(?:news|samachar|khabar|seithigal)(?!\w)",
    re.IGNORECASE,
)


def classify_tier(name: str, raw_group: str = "") -> str:
    clean_name = (name or "").strip().lower()
    if not clean_name:
        return "FTA"
    if _FTA_BRAND_RE.search(clean_name) or _FTA_REGIONAL_NEWS_RE.search(clean_name):
        return "FTA"
    if _PAID_BRAND_RE.search(clean_name):
        return "PAID"
    return "FTA"


def classify_category(raw_group: str, name: str) -> str:
    lower_name = (name or "").lower()
    if "&tv" in lower_name or "and tv" in lower_name:
        return "Entertainment"
    text = f"{raw_group or ''} {name or ''}".lower()

    if any(k in text for k in ("movie", "cinema", "film", "talkies", "goldmines", "max", "pictures", "flix", "blockbuster", "cinemalu", "picchar", "thirai")):
        return "Movies"
    if any(k in text for k in ("kid", "cartoon", "anime", "animax", "child", "disney", "hungama", "nick", "sonic", "pogo", "yay", "gubbare", "chhota bheem", "green gold", "bal bharat")):
        return "Kids"
    if any(k in text for k in ("music", "song", "mastiii", "9xm", "jalwa", "tashan", "jhakaas", "zoom", "beats", "mtv", "vh1", "sangeet", "filmi gaane", "balle balle", "isai", "murasu")):
        return "Music"
    if any(k in text for k in ("sport", "cricket", "football", "fifa", "wwe", "ten ", "star sports", "sports18", "sony six", "eurosport", "tennis", "racing", "khel")):
        return "Sports"
    if any(k in text for k in ("business", "finance", "market", "money", "stock", "sensex", "nifty", "profit", "cnbc", "et now", "bloomberg")):
        return "Business"
    if any(k in text for k in ("bhakti", "aarti", "pooja", "devot", "relig", "aastha", "sanskar", "sadhna", "gurbani", "spiritual", "darshan", "ishwar", "paras", "subharti", "om ", "vedic", "quran", "bible", "god", "prarthana")):
        return "Devotional"
    if any(k in text for k in ("doc", "info", "science", "learn", "history", "nat geo", "national geographic", "discovery", "animal planet", "wild", "travel", "epic", "kisan", "knowledge", "gyan", "pmevidya", "swayam", "education", "bbc earth")):
        return "Education"
    if any(k in text for k in ("news", "samachar", "khabar", "aaj tak", "ndtv", "wion", "republic", "abp", "headline", "24x7", "tv9", "news18", "sandesh", "puthiya", "thanthi", "manorama", "mathrubhumi", "sakshi", "eenadu", "kanak", "argus", "pratidin", "zee 24")):
        return "News"
    if any(k in text for k in ("punjab", "marath", "tamil", "telugu", "bengal", "bangla", "gujarat", "malayal", "kannada", "odia", "oriya", "bhojpuri", "assam", "regional", "kashir", "girnar", "sahyadri", "podhigai", "saptagiri", "yadagiri", "chandana")):
        return "Regional"
    return "Entertainment"


def classify_zone_and_region(language: str, name: str) -> tuple[str, str, bool]:
    lang = (language or "Hindi").strip()
    text = f"{lang} {name}".lower()

    if any(k in text for k in ("tamil", "chennai", "podhigai", "sun tv", "star vijay", "kalaignar", "polimer", "thanthi")):
        return ("South India", "Tamil Nadu", True)
    if any(k in text for k in ("telugu", "andhra", "telangana", "hyderabad", "star maa", "gemini", "etv telugu", "sakshi", "tv9 telugu")):
        return ("South India", "Andhra & Telangana", True)
    if any(k in text for k in ("kannada", "karnataka", "bengaluru", "udaya", "suvarna", "chandana", "public tv")):
        return ("South India", "Karnataka", True)
    if any(k in text for k in ("malayalam", "kerala", "asianet", "surya", "mazhavil", "manorama", "mathrubhumi", "kairali", "flowers")):
        return ("South India", "Kerala", True)
    if any(k in text for k in ("marathi", "maharashtra", "mumbai", "sahyadri", "pravah", "majha", "lokmat", "saam", "24 taas")):
        return ("West India", "Maharashtra", True)
    if any(k in text for k in ("gujarati", "gujarat", "girnar", "asmita", "sandesh", "24 kalak", "gstv", "vtv")):
        return ("West India", "Gujarat", True)
    if any(k in text for k in ("rajasthani", "rajasthan", "marwar", "jaipur", "first india")):
        return ("West India", "Rajasthan", True)
    if any(k in text for k in ("bengali", "bangla", "kolkata", "jalsha", "ananda", "24 ghanta", "sangeet bangla", "aakash aath")):
        return ("East India", "West Bengal", True)
    if any(k in text for k in ("odia", "oriya", "odisha", "tarang", "sarthak", "kanak", "otv", "kalinga", "argus")):
        return ("East India", "Odisha", True)
    if any(k in text for k in ("bhojpuri", "bihar", "jharkhand", "maithili", "biskope", "kashish")):
        return ("East India", "Bihar & Jharkhand", True)
    if any(k in text for k in ("assamese", "assam", "northeast", "north east", "prag", "pratidin", "dy365", "rang", "rengoni")):
        return ("North-East India", "Assam & North-East", True)
    if any(k in text for k in ("punjabi", "punjab", "jalandhar", "ptc", "chardikla", "mh one", "pitaara")):
        return ("North India", "Punjab & Haryana", True)
    if any(k in text for k in ("urdu", "kashmiri", "kashir", "gulistan")):
        return ("North India", "Jammu & Kashmir", True)
    if any(k in text for k in ("madhya pradesh", "chhattisgarh", "ibc24", "bansal")):
        return ("Central India", "MP & Chhattisgarh", True)
    if any(k in text for k in ("uttar pradesh", "uttarakhand", "abp ganga")):
        return ("North India", "UP & Uttarakhand", True)

    return ("National", "All India", False)


# ---------------------------------------------------------------------------
# Network safety and source parsing
# ---------------------------------------------------------------------------

def safe_https(url: str) -> bool:
    """Never fetch non-HTTPS or obviously private/internal/untrusted URL schemes."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
        if parts.scheme.lower() != 'https' or not parts.hostname or parts.username or parts.password:
            return False
        hostname = parts.hostname.lower().rstrip('.')
        if hostname in {'localhost', 'metadata.google.internal'} or hostname.endswith(('.local', '.internal', '.localhost')):
            return False
        try:
            if not ipaddress.ip_address(hostname).is_global:
                return False
        except ValueError:
            pass
        return True
    except (ValueError, AttributeError):
        return False


class SafeHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_https(newurl):
            raise ValueError('unsafe_http_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HTTP_OPENER = urllib.request.build_opener(SafeHTTPSRedirectHandler())


def fetch(url: str, *, timeout: float = 12.0, max_bytes: int = MAX_TEXT,
          headers: dict[str, str] | None = None) -> tuple[bytes, int, str]:
    if not safe_https(url):
        raise ValueError('unsafe_or_insecure_url')
    h = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
    if headers:
        h.update({k: v for k, v in headers.items() if isinstance(k, str) and isinstance(v, str)
                  and '\r' not in v and '\n' not in v})
    req = urllib.request.Request(url, headers=h)
    # urllib follows redirects automatically; re-validate final URL afterwards.
    with _HTTP_OPENER.open(req, timeout=timeout) as resp:
        if not safe_https(resp.geturl()):
            raise ValueError('redirected_to_unsafe_url')
        status = getattr(resp, 'status', 200)
        data = resp.read(max_bytes)
        ctype = (resp.headers.get('Content-Type') or '').lower()
        return data, status, ctype


def fetch_json(url: str) -> list[dict[str, Any]]:
    for attempt in range(2):
        try:
            body, status, _ = fetch(url, timeout=20.0, max_bytes=15_000_000)
            parsed = json.loads(body.decode('utf-8'))
            if status == 200 and isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        except Exception as exc:
            if attempt == 1:
                print(f'[Fetch] {url}: {type(exc).__name__}: {exc}', file=sys.stderr)
            else:
                time.sleep(0.5)
    return []


def parse_m3u(text: str) -> list[dict[str, str]]:
    """Tolerate M3U metadata but NEVER infer a country's identity from language."""
    result: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('#EXTINF:'):
            attrs = dict((k.lower(), v) for k, v in re.findall(r'([\w-]+)="([^"]*)"', line))
            attrs['name'] = line.rsplit(',', 1)[-1].strip() if ',' in line else attrs.get('tvg-name', '')
            current = attrs
        elif current is not None and line.startswith('#EXTVLCOPT:'):
            if 'http-referrer=' in line or 'http-referer=' in line:
                current['referrer'] = line.split('=', 1)[-1].strip()
            elif 'http-user-agent=' in line:
                current['user_agent'] = line.split('=', 1)[-1].strip()
        elif current is not None and line.startswith(('https://', 'http://')):
            current['url'] = line.split('|', 1)[0]
            result.append(current)
            current = None
    return result


def sports_identity(name: str) -> tuple[str, str, bool]:
    """Normalize broadcaster + number + regional language, *never* confuse 1/2 or Hindi/Tamil.

    Resolution is returned separately: SD/HD variants may share IPTV-org channel ID.
    """
    raw = (name or '').lower()
    raw = re.sub(r'\bsony\s+sports\s+ten\b', 'sony ten', raw)
    raw = re.sub(r'\bstar\s+sports\s+hd\s*(\d+)\b', r'star sports \1 hd', raw)
    raw = re.sub(r'\bsony\s+ten\s+hd\s*(\d+)\b', r'sony ten \1 hd', raw)
    tokens = re.findall(r'[a-z]+|\d+', raw)
    hd = 'hd' in tokens or 'fhd' in tokens
    remove = {'hd', 'sd', 'fhd', 'uhd', 'live', 'india', 'channel', 'tv', 'stream'}
    compact = ''.join(t for t in tokens if t not in remove)
    return (compact, 'HD' if hd else 'unspecified', bool(compact))


def load_sports_targets() -> list[dict[str, Any]]:
    """Targets are an index of Indian channels, NOT playable stream URLs."""
    if not SPORTS_TARGETS_JSON.exists():
        return []
    obj = json.loads(SPORTS_TARGETS_JSON.read_text('utf-8'))
    if not isinstance(obj, dict) or not isinstance(obj.get('targets'), list):
        raise ValueError('sports_targets.json must have {"targets": [...]}')
    results = []
    for entry in obj['targets']:
        if isinstance(entry, dict) and entry.get('name'):
            results.append(entry)
    return results


def sports_matches(name: str, target: dict[str, Any], feed_id: str = '') -> bool:
    observed, _, nonempty = sports_identity(name)
    if not nonempty:
        return False
    # Do not equate Pakistani TEN Sports with Sony's Indian TEN network.
    for alias in [target['name'], *(target.get('aliases') or [])]:
        wanted, wanted_quality, _ = sports_identity(alias)
        if observed != wanted:
            continue
        if target.get('quality') == 'HD' and wanted_quality == 'HD':
            seen = sports_identity(name)[1] == 'HD' or bool(re.search(r'(^|\W)HD($|\W)', feed_id, re.I))
            if not seen:
                continue
        return True
    return False


def is_sports_channel(name: str, raw_group: str = '') -> bool:
    return classify_category(raw_group, name) == 'Sports'


def feed_is_indian(feed: dict[str, Any] | None, channel_country: str = 'IN') -> bool:
    if channel_country != 'IN':
        return False
    if not feed:
        return True  # Indian broadcast channel; feed unspecified
    areas = feed.get('broadcast_area') or []
    # Explicitly non-India regional feeds must not be used for an India-first app.
    country_codes = {a.upper()[2:] for a in areas if isinstance(a, str) and a.lower().startswith('c/')}
    if country_codes and 'IN' not in country_codes:
        return False
    return True


def contains_foreign_hint(*values: str) -> bool:
    text = ' '.join(x or '' for x in values).lower()
    if re.search(r'\b(pakistan|pakistani|bangladesh|nepal|sri lanka)\b', text):
        return True
    # Catch country-specific domains/path hints, but not arbitrary occurrences of "pk" in tokens.
    if re.search(r'https?://[^/\s]+\.pk(?::\d+)?(?:/|$)', text):
        return True
    return bool(re.search(r'[/_-](?:pakistan|pak-feed)(?:[/_.-]|$)', text))


def parse_channel_id(tvg_id: str) -> tuple[str, str]:
    base, _, feed = (tvg_id or '').strip().partition('@')
    return (base, feed)


def load_previous(path: Path = OUTPUT_JSON) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text('utf-8'))
        return {str(x['id']).split('@')[0]: x for x in payload.get('channels', []) if x.get('id')}
    except (OSError, ValueError, TypeError):
        return {}


@dataclass
class Candidate:
    channel_id: str
    url: str
    source: str
    tier: str
    identity_score: int = 0
    rights_confirmed: bool = False
    user_agent: str = ''
    referrer: str = ''
    feed_id: str = ''
    quality: str = ''
    publish_url: bool = False
    language: str = ''


@dataclass
class Result:
    ok: bool
    reason: str
    latency_ms: int = 99999
    content_type: str = ''
    has_drm: bool = False


def _probe(url: str, user_agent: str = '', referrer: str = '', timeout: float = 5.5) -> Result:
    """Prove manifest + media playlist + first segment availability; no DRM circumvention."""
    if not safe_https(url):
        return Result(False, 'unsafe_or_http_url')
    if any(bad in url.lower() for bad in DEAD_HOST_SUBSTRINGS):
        return Result(False, 'known_dead_host')
    headers = {'Accept': 'application/vnd.apple.mpegurl,application/x-mpegurl,*/*',
               'User-Agent': user_agent or USER_AGENT}
    if referrer:
        headers['Referer'] = referrer
    started = time.monotonic()
    visited: set[str] = set()
    current = url
    try:
        for _ in range(4):
            if current in visited or not safe_https(current):
                return Result(False, 'playlist_loop_or_unsafe_uri')
            visited.add(current)
            raw, status, ctype = fetch(current, timeout=timeout, max_bytes=MAX_PLAYLIST, headers=headers)
            if status not in (200, 206):
                return Result(False, f'http_{status}')
            content = raw.decode('utf-8', errors='replace').lstrip('\ufeff\n\r\t ')
            if not content.startswith('#EXTM3U'):
                # Direct binary MPEG-TS streams are allowed only for explicit TS MIME types.
                if 'video/mp2t' in ctype and raw:
                    return Result(True, 'direct_ts', int((time.monotonic()-started)*1000), ctype)
                return Result(False, 'invalid_hls_manifest')
            if re.search(r'#EXT-X-(?:SESSION-KEY|KEY):[^\n]*KEYFORMAT="(?!identity)', content, re.I) or re.search(r'#EXT-X-KEY:[^\n]*METHOD=SAMPLE-AES', content, re.I):
                return Result(False, 'drm_protected', has_drm=True)
            if '#EXT-X-STREAM-INF:' in content:
                lines = [s.strip() for s in content.splitlines() if s.strip()]
                variants = []
                for i, line in enumerate(lines):
                    if line.startswith('#EXT-X-STREAM-INF:') and i+1 < len(lines):
                        uri = lines[i+1]
                        if uri and not uri.startswith('#'):
                            bw = re.search(r'BANDWIDTH=(\d+)', line)
                            variants.append((int(bw.group(1)) if bw else 10000000, uri))
                if not variants:
                    return Result(False, 'master_without_variants')
                # Prefer a modest bitrate to reduce probe load; actual app can use master URL.
                next_uri = sorted(variants, key=lambda x: x[0])[0][1]
                current = urllib.parse.urljoin(current, next_uri)
                continue
            if '#EXTINF:' not in content and '#EXT-X-PART:' not in content:
                return Result(False, 'media_without_segments')
            segs = [s.strip() for s in content.splitlines() if s.strip() and not s.startswith('#')]
            if not segs:
                # LL-HLS: segment URL can be in a PART tag.
                part = re.search(r'#EXT-X-PART:[^\n]*URI="([^"]+)"', content)
                if part:
                    segs = [part.group(1)]
            if not segs:
                return Result(False, 'media_without_segments')
            segment = urllib.parse.urljoin(current, segs[0])
            if not safe_https(segment):
                return Result(False, 'unsafe_segment_uri')
            seg_headers = dict(headers)
            seg_headers['Range'] = 'bytes=0-255'
            chunk, seg_status, seg_type = fetch(segment, timeout=timeout, max_bytes=256, headers=seg_headers)
            if seg_status not in (200, 206) or len(chunk) < 16:
                return Result(False, f'unavailable_media_segment_{seg_status}')
            return Result(True, 'media_verified', int((time.monotonic()-started)*1000), seg_type)
        return Result(False, 'too_many_nested_playlists')
    except urllib.error.HTTPError as exc:
        return Result(False, f'http_{exc.code}')
    except urllib.error.URLError as exc:
        reason = str(exc.reason).lower()
        return Result(False, 'timeout' if 'timed out' in reason else 'network_error')
    except TimeoutError:
        return Result(False, 'timeout')
    except ValueError as exc:
        return Result(False, str(exc))
    except Exception as exc:
        return Result(False, f'probe_{type(exc).__name__}')


def _load_authorized_sources() -> list[dict[str, Any]]:
    """Sources provided by the channel distributor under a public-redistribution licence.

    Optionally supplied through GitHub secret LICENSED_SOURCES_JSON.
    The JSON can store candidates; final output is PUBLIC, so never publish signed
    URLs/tokens unless the provider explicitly permits publishing these URLs.
    """
    raw = os.getenv('LICENSED_SOURCES_JSON', '').strip()
    if raw:
        try:
            obj = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError(f'Invalid LICENSED_SOURCES_JSON: {exc}') from exc
    else:
        config = Path('authorized_sources.json')
        obj = json.loads(config.read_text('utf-8')) if config.exists() else {'sources': []}
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and isinstance(obj.get('sources'), list):
        return obj['sources']
    raise ValueError('authorized sources: expected {"sources": [...]}')


def catalogue_sources() -> tuple[dict[str, dict[str, Any]], list[Candidate], Counter[str]]:
    """Collect verified *Indian identities*, then potential stream candidates.

    Public paid sports candidates are probe-only (never returned as public URLs).
    Community FTA URLs require separate publication approval.
    """
    stats: Counter[str] = Counter()
    api: dict[str, list[dict[str, Any]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_json, url): name for name, url in API_ENDPOINTS.items()}
        for fut in concurrent.futures.as_completed(futures):
            api[futures[fut]] = fut.result()
    if not api.get('channels'):
        raise RuntimeError('IPTV-org Indian channel metadata unavailable; retaining last catalogue')
    blocked = {e.get('channel') for e in api.get('blocklist', []) if e.get('channel')}
    channels: dict[str, dict[str, Any]] = {}
    for ch in api['channels']:
        cid = ch.get('id') or ''
        if (ch.get('country') or '').upper() != 'IN' or cid in blocked or ch.get('is_nsfw') or ch.get('closed'):
            continue
        channels[cid] = ch
    stats['indian_metadata_channels'] = len(channels)
    if not channels:
        raise RuntimeError('No Indian channel IDs returned by metadata source')

    feeds: dict[tuple[str,str], dict[str, Any]] = {}
    by_ch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feed in api.get('feeds', []):
        if feed.get('channel') in channels:
            feeds[(feed.get('channel',''), str(feed.get('id') or ''))] = feed
            by_ch[feed['channel']].append(feed)
    logos: dict[str,str] = {}
    for logo in api.get('logos', []):
        cid = logo.get('channel')
        if cid in channels and logo.get('in_use') is not False and safe_https(logo.get('url') or ''):
            logos.setdefault(cid, logo['url'])

    # Known Indian channel aliases can match nameless M3U entries ONLY on India master.
    names: dict[str, set[str]] = defaultdict(set)
    for cid, ch in channels.items():
        for name in [ch.get('name') or '', *(ch.get('alt_names') or [])]:
            key = canonical_channel_key(name)
            if key:
                names[key].add(cid)

    candidates: list[Candidate] = []
    for st in api.get('streams', []):
        cid = st.get('channel')
        if cid not in channels:
            continue
        feed_id = str(st.get('feed') or '')
        known_feed = feeds.get((cid, feed_id))
        if feed_id and by_ch[cid] and not known_feed:
            stats['rejected_unknown_feed'] += 1
            continue
        if not feed_is_indian(known_feed):
            stats['rejected_non_india_feed'] += 1
            continue
        url = str(st.get('url') or '').strip()
        if not safe_https(url) or contains_foreign_hint(st.get('title') or '', url):
            stats['rejected_url_or_foreign_hint'] += 1
            continue
        chname = str(channels[cid].get('name') or '')
        if is_cross_channel_mismatch(chname, url):
            stats['rejected_channel_url_mismatch'] += 1
            continue
        tier = classify_tier(chname)
        if tier == 'PAID':
            if PREMIUM_DISCOVERY or (SPORTS_DISCOVERY and is_sports_channel(chname, ' '.join(channels[cid].get('categories') or []))):
                candidates.append(Candidate(cid, url, 'IPTV-org sports diagnostic', 'PAID', 95, False,
                                            str(st.get('user_agent') or ''), str(st.get('referrer') or ''),
                                            feed_id, str(st.get('quality') or ''), False,
                                            INDIAN_LANG_CODES.get(next(iter((known_feed or {}).get('languages') or []), ''), '')))
                stats['public_paid_sports_candidates'] += 1
            else:
                stats['community_paid_metadata_only'] += 1
            continue
        if not ALLOW_COMMUNITY_FTA:
            stats['community_fta_permission_required'] += 1
            continue
        candidates.append(Candidate(cid, url, 'IPTV-org API', tier, 95, False,
                                    str(st.get('user_agent') or ''), str(st.get('referrer') or ''),
                                    feed_id, str(st.get('quality') or ''), True,
                                    INDIAN_LANG_CODES.get(next(iter((known_feed or {}).get('languages') or []), ''), '')))

    # Country/language M3U collection: strict metadata IDs (avoid Pakistan feed pollution).
    if ALLOW_COMMUNITY_FTA or SPORTS_DISCOVERY or PREMIUM_DISCOVERY:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(fetch, uri, timeout=12, max_bytes=3_000_000): (label, uri)
                    for label, uri in M3U_SOURCES}
            for fut in concurrent.futures.as_completed(futs):
                label, _ = futs[fut]
                try:
                    body, _, _ = fut.result()
                    entries = parse_m3u(body.decode('utf-8', errors='replace'))
                except Exception as exc:
                    print(f'[M3U] {label}: {type(exc).__name__}')
                    continue
                for entry in entries:
                    cid, fid = parse_channel_id(entry.get('tvg-id', ''))
                    # Language list never infers India by language; exact ID required.
                    if not cid and label == 'IPTV-org India':
                        possible = names.get(canonical_channel_key(entry.get('name', '')), set())
                        cid = next(iter(possible)) if len(possible) == 1 else ''
                    if cid not in channels:
                        stats['rejected_foreign_or_unknown_m3u_id'] += 1
                        continue
                    if fid and by_ch[cid] and (cid, fid) not in feeds:
                        stats['rejected_unknown_feed'] += 1
                        continue
                    if not feed_is_indian(feeds.get((cid, fid))):
                        stats['rejected_non_india_feed'] += 1
                        continue
                    url = entry.get('url', '')
                    if not safe_https(url) or contains_foreign_hint(entry.get('name', ''), entry.get('group-title',''), entry.get('tvg-country',''), url):
                        stats['rejected_url_or_foreign_hint'] += 1
                        continue
                    if entry.get('tvg-country','').upper() not in ('', 'IN'):
                        stats['rejected_non_india_country_tag'] += 1
                        continue
                    if is_cross_channel_mismatch(channels[cid].get('name') or '', url):
                        stats['rejected_channel_url_mismatch'] += 1
                        continue
                    tier = classify_tier(channels[cid].get('name') or '')
                    if tier == 'PAID':
                        if PREMIUM_DISCOVERY or (SPORTS_DISCOVERY and is_sports_channel(channels[cid].get('name') or '',
                                                                   ' '.join(channels[cid].get('categories') or []))):
                            candidates.append(Candidate(cid, url, label + ' (sports diagnostic)', 'PAID',
                                                        90 if entry.get('tvg-id') else 70,
                                                        False, entry.get('user_agent',''), entry.get('referrer',''), fid,
                                                        entry.get('quality',''), False,
                                                        INDIAN_LANG_CODES.get(entry.get('tvg-language','').lower(),
                                                                              entry.get('tvg-language',''))))
                            stats['public_paid_sports_candidates'] += 1
                        else:
                            stats['community_paid_metadata_only'] += 1
                        continue
                    if not ALLOW_COMMUNITY_FTA:
                        continue
                    candidates.append(Candidate(cid, url, label, 'FTA', 90 if entry.get('tvg-id') else 70,
                                                False, entry.get('user_agent',''), entry.get('referrer',''), fid,
                                                entry.get('quality',''), True,
                                                INDIAN_LANG_CODES.get(entry.get('tvg-language','').lower(), entry.get('tvg-language',''))))
    # Paid sources: ONLY explicitly licensed and approved public URLs.
    for obj in _load_authorized_sources():
        if not isinstance(obj, dict):
            continue
        cid = str(obj.get('channel_id') or '')
        if not cid:
            continue
        # Supplement metadata for legally licensed channels not yet listed by IPTV-org.
        if cid not in channels:
            name = str(obj.get('name') or '').strip()
            if not name or (obj.get('country') or '').upper() != 'IN':
                stats['invalid_licensed_identity'] += 1
                continue
            channels[cid] = {'id': cid, 'name': name, 'country': 'IN', 'network': obj.get('network') or '',
                             'categories': [obj.get('category') or 'general'], 'website': obj.get('website') or ''}
        allowed = obj.get('rights_confirmed') is True and obj.get('redistribution_scope') == 'public' and obj.get('publish_url') is True
        if not allowed:
            stats['licensed_permission_or_publication_missing'] += 1
            continue
        source_urls = obj.get('urls') or []
        for u in source_urls:
            url = str(u.get('url') or '') if isinstance(u, dict) else str(u)
            if not safe_https(url):
                stats['licensed_url_invalid'] += 1
                continue
            headers = u if isinstance(u, dict) else {}
            candidates.append(Candidate(cid, url, 'licensed:' + str(obj.get('provider') or 'partner'),
                                        classify_tier(channels[cid].get('name', '')), 100, True,
                                        str(headers.get('user_agent') or ''), str(headers.get('referrer') or ''),
                                        str(obj.get('feed') or ''), str(obj.get('quality') or ''), True,
                                        str(obj.get('language') or '')))
            stats['licensed_candidates'] += 1
    for cid,ch in channels.items():
        ch['logo_url'] = logos.get(cid, '')
    return channels, candidates, stats


def _rank(c: Candidate, result: Result, previous_url: str) -> tuple[int, int]:
    # Eligibility first; prefer identity and licensed origin, but do not switch
    # a known good URL for tiny latency differences on every scan.
    score = c.identity_score + (40 if c.rights_confirmed else 0)
    if c.url == previous_url:
        score += 18
    score += 5 if c.url.startswith('https://') else 0
    return (-score, result.latency_ms)


def _m3u_quote(value: str) -> str:
    return (value or '').replace('"', "'").replace('\r',' ').replace('\n',' ')


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    os.replace(tmp, path)


def sports_diagnostics(meta: dict[str, dict[str, Any]], candidates: list[Candidate],
                       health: dict[tuple[str, str, str], Result]) -> dict[str, Any]:
    """Detailed India sports testing. Never expose unlicensed streaming links in public reports."""
    targets = load_sports_targets()
    records = []
    all_sports = [(cid, ch) for cid, ch in meta.items()
                  if is_sports_channel(ch.get('name') or '', ' '.join(ch.get('categories') or []))]
    for target in targets:
        target_candidates = [c for c in candidates
                             if c.channel_id in meta
                             and sports_matches(meta[c.channel_id].get('name') or '', target, c.feed_id)]
        ids = {c.channel_id for c in target_candidates}
        matched = [(cid, ch) for cid, ch in all_sports
                   if cid in ids or sports_matches(ch.get('name') or '', target)]
        probes = [health.get((c.url, c.user_agent, c.referrer), Result(False, 'not_tested'))
                  for c in target_candidates]
        reasons = dict(Counter(r.reason for r in probes))
        records.append({
            'name': target['name'], 'network': target.get('network', ''),
            'tier': target.get('tier', 'PAID'), 'quality': target.get('quality', 'unspecified'),
            'matched_indian_channels': [ch.get('name') for _, ch in matched],
            'candidate_count': len(target_candidates),
            'responding_candidates': sum(r.ok for r in probes),
            'drm_indicated': sum(r.has_drm for r in probes),
            'probe_results': reasons,
            'status': ('CANDIDATE_RESPONDED_NOT_AUTHORIZED_FOR_REBROADCAST' if any(r.ok for r in probes)
                       else 'NO_PLAYABLE_CANDIDATE_CONFIRMED'),
        })
    return {
        'generated_at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'mode': 'public_sports_diagnostics_not_rebroadcast',
        'warning': 'Responding HLS segment does not prove channel identity, India geo playback, or rights.',
        'target_count': len(records),
        'targets_with_candidates': sum(x['candidate_count'] > 0 for x in records),
        'targets_with_responses': sum(x['responding_candidates'] > 0 for x in records),
        'targets': records,
    }


def build_catalogue() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    meta, candidates, stats = catalogue_sources()
    previous = load_previous()
    distinct: dict[tuple[str,str],Candidate] = {}
    url_owners: dict[str,set[str]] = defaultdict(set)
    for c in candidates:
        url_owners[c.url].add(c.channel_id)
    for c in candidates:
        # Prevent a single placeholder from being assigned to different channels.
        if len(url_owners[c.url]) >= 2:
            stats['rejected_shared_channel_url'] += 1
            continue
        key = (c.channel_id,c.url)
        if key not in distinct or c.identity_score > distinct[key].identity_score:
            distinct[key] = c
    candidates = list(distinct.values())
    if SPORTS_DISCOVERY or PREMIUM_DISCOVERY:
        # Bound scan cost even when public playlists contain thousands of entries.
        premium = sorted((c for c in candidates if c.tier == 'PAID' and not c.publish_url),
                         key=lambda c: (0 if is_sports_channel(c.channel_id, ' '.join((meta.get(c.channel_id) or {}).get('categories') or [])) else 1,
                                        -c.identity_score, c.channel_id, c.url))
        allowed_paid_urls = {(c.channel_id, c.url) for c in premium[:SPORTS_MAX_CANDIDATES]}
        stats['sports_candidates_deferred_by_budget'] = max(0, len(premium) - SPORTS_MAX_CANDIDATES)
        candidates = [c for c in candidates if c.publish_url or c.tier != 'PAID'
                      or (c.channel_id, c.url) in allowed_paid_urls]
    stats['unique_candidates'] = len(candidates)
    urls: dict[tuple[str,str,str], list[Candidate]] = defaultdict(list)
    for c in candidates:
        urls[(c.url, c.user_agent, c.referrer)].append(c)
    health: dict[tuple[str,str,str], Result] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_probe, url, agent, referrer): (url,agent,referrer)
                   for (url,agent,referrer) in urls}
        for fut in concurrent.futures.as_completed(futures):
            key = futures[fut]
            try:
                health[key] = fut.result()
            except Exception as exc:
                health[key] = Result(False, 'worker_' + type(exc).__name__)
            stats['probe_' + health[key].reason] += 1
    groups: dict[str, list[tuple[Candidate,Result]]] = defaultdict(list)
    for c in candidates:
        r = health[(c.url,c.user_agent,c.referrer)]
        if r.ok and c.publish_url:
            groups[c.channel_id].append((c,r))
    live: list[dict[str, Any]] = []
    offline: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for cid,ch in sorted(meta.items(), key=lambda v: v[1].get('name','').casefold()):
        name = ch.get('name') or cid
        tier = classify_tier(name)
        category = classify_category(' '.join(ch.get('categories') or []), name)
        values = groups.get(cid, [])
        if not values:
            reasons = [health[(c.url,c.user_agent,c.referrer)].reason for c in candidates if c.channel_id == cid]
            offline.append({'id': cid, 'name': name, 'tier': tier, 'category': category,
                            'logo_url': ch.get('logo_url',''), 'status': 'OFFLINE',
                            'reason': Counter(reasons).most_common(1)[0][0] if reasons else
                            ('licensed_source_required' if tier=='PAID' else 'no_authorized_source')})
            continue
        prev = previous.get(cid, {})
        values.sort(key=lambda cr: _rank(cr[0],cr[1],str(prev.get('url') or '')))
        selected, res = values[0]
        language = selected.language or next((lg for lg in LANGUAGE_CODES if lg.lower() in name.lower()), 'Hindi')
        zone, region, is_regional = classify_zone_and_region(language, name)
        alternates = list(dict.fromkeys(c.url for c,_ in values[1:] if c.url != selected.url))[:6]
        cid_out = str(prev.get('id') or cid)
        # Avoid keeping a stale @feed variant from the previous scan.
        if selected.feed_id:
            cid_out = cid + '@' + selected.feed_id
        live.append({
            'id': cid_out, 'name': name, 'network': ch.get('network') or category,
            'category': category, 'language': language, 'lang_code': LANGUAGE_CODES.get(language, 'und'),
            'zone': zone, 'region': region, 'tier': tier,
            'logo_url': ch.get('logo_url',''), 'url': selected.url,
            'fallback_urls': alternates, 'website': ch.get('website') or '',
            'is_regional': is_regional or category=='Regional',
            'quality': selected.quality or 'unknown',
            'source': selected.source, 'country': 'IN', 'status': 'ONLINE',
            'last_checked': now,
            # Player needs these headers when the distributor specifically uses them.
            **({'user_agent': selected.user_agent} if selected.user_agent else {}),
            **({'referrer': selected.referrer} if selected.referrer else {}),
        })
    # Stable numbering; preserve existing channel numbers wherever possible.
    numbers = {x.get('ch_no') for x in previous.values() if isinstance(x.get('ch_no'), int) and x.get('ch_no') > 0}
    next_num = max(numbers or {0}) + 1
    live.sort(key=lambda c: (0 if c['id'].split('@')[0] in previous else 1,
                             previous.get(c['id'].split('@')[0], {}).get('ch_no', 10**9),
                             c['name'].lower()))
    for ch in live:
        old = previous.get(ch['id'].split('@')[0], {}).get('ch_no')
        ch['ch_no'] = old if isinstance(old, int) and old > 0 else next_num
        if ch['ch_no'] == next_num:
            next_num += 1
    stats['live_channels'] = len(live)
    stats['offline_indian_channels'] = len(offline)
    stats['live_fta_channels'] = sum(c['tier']=='FTA' for c in live)
    stats['live_paid_licensed_channels'] = sum(c['tier']=='PAID' for c in live)
    report = {'updated_at': now, 'engine': 'Bharat TV SmartBot v3.1',
              'policy': 'India identities only; public premium sports discovery diagnostic-only',
              'settings': {'allow_community_fta': ALLOW_COMMUNITY_FTA,
                           'sports_discovery': SPORTS_DISCOVERY,
                           'premium_discovery': PREMIUM_DISCOVERY,
                           'sports_max_candidates': SPORTS_MAX_CANDIDATES,
                           'scan_workers': WORKERS},
              'counts': dict(sorted(stats.items())),
              'sports': sports_diagnostics(meta, candidates, health)}
    return live, offline, report


def export(live: list[dict[str, Any]], offline: list[dict[str, Any]], report: dict[str, Any]) -> None:
    # Write public-safe sports probe summary with no extracted premium stream URLs.
    atomic_json(SPORTS_REPORT_JSON, report.get('sports', {}))
    if not live:
        # Never destroy an existing working playlist when API or sources go down.
        print('[Warning] 0 verified channels. Existing published playlist unchanged.', file=sys.stderr)
        atomic_json(REPORT_JSON, report)
        atomic_json(OFFLINE_JSON, {'updated_at': report['updated_at'], 'channels': offline})
        return
    lines = ['#EXTM3U url-tvg="https://iptv-org.github.io/epg/guides/in.xml"']
    for ch in live:
        lines.append(f'#EXTINF:-1 tvg-id="{_m3u_quote(ch["id"])}" tvg-chno="{ch["ch_no"]}" '
                     f'tvg-language="{_m3u_quote(ch["language"])}" tvg-tier="{ch["tier"]}" '
                     f'tvg-logo="{_m3u_quote(ch["logo_url"])}" '
                     f'group-title="{_m3u_quote(ch["category"])}",{ch["name"]}')
        if ch.get('user_agent'):
            lines.append('#EXTVLCOPT:http-user-agent=' + ch['user_agent'])
        if ch.get('referrer'):
            lines.append('#EXTVLCOPT:http-referrer=' + ch['referrer'])
        lines.append(ch['url'])
    payload = {
        'updated_at': report['updated_at'], 'generator': 'BharatTV SmartBot v3.1',
        'total_channels': len(live), 'fta_channels': sum(c['tier']=='FTA' for c in live),
        'paid_channels': sum(c['tier']=='PAID' for c in live), 'channels': live,
    }
    atomic_json(OUTPUT_JSON, payload)
    tmp = OUTPUT_M3U.with_name(OUTPUT_M3U.name + '.tmp')
    tmp.write_text('\n'.join(lines)+'\n', 'utf-8')
    os.replace(tmp, OUTPUT_M3U)
    atomic_json(OFFLINE_JSON, {'updated_at': report['updated_at'], 'total_channels': len(offline), 'channels': offline})
    atomic_json(REPORT_JSON, report)
    print(f'[Done] {len(live)} online channels, {len(offline)} offline Indian channels; '
          f'{payload["fta_channels"]} FTA / {payload["paid_channels"]} licensed PAID')


def main() -> None:
    live, offline, report = build_catalogue()
    export(live, offline, report)


if __name__ == '__main__':
    main()
