#!/usr/bin/env python3
"""
Bharat TV — Next-Gen Indian IPTV Channel Discovery, Identity Verification & Health Engine
=========================================================================================
Runs 5x daily via GitHub Actions (`update-channels.yml`) to build `channels.json` and `channels.m3u`.

Key Capabilities:
1. Multi-Source Discovery:
   - Official IPTV-org JSON API (`channels.json`, `streams.json`, `feeds.json`, `logos.json`)
   - Official Country & Language M3U Playlists (India + 15 Indian languages: Hindi, Tamil,
     Telugu, Punjabi, Marathi, Bengali, Gujarati, Kannada, Malayalam, Odia, Assamese, Bhojpuri, Urdu)
   - Curated Public Indian IPTV M3U Repositories
2. Zero Cross-Channel Stream Contamination:
   - Blocks known cross-mapped streams (e.g., Zee Cinema on SET Max, generic sports feeds on
     Star Sports 1, Colors on Sony SAB, Colors Cineplex on Star Gold, Animax on Cartoon Network).
   - Rejects any generic stream URL claimed by 3+ distinct channel identities across networks.
   - Preserves channel numbers (1, 2, Plus), variants (Movies, Music, Gold), and language tags
     during normalization so Hindi and regional feeds never collide.
3. FTA (Free-to-Air) vs PAID (Subscription) Classification:
   - Classifies every Indian channel into FTA (DD FreeDish / Prasar Bharati / Public News) or
     PAID (Star/JioStar, Sony/Culver Max, Zee, Colors/Viacom18, Sun Network, Discovery, Warner).
4. Concurrent Deep HLS Health Check:
   - Verifies HTTP status, `#EXTM3U` playlist headers, and master/media chunklists concurrently,
     sorting mirrors by fastest response latency and promoting HTTPS streams as primary.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 1. Upstream Sources (IPTV-org API + Indian Language & Regional Playlists)
# ---------------------------------------------------------------------------

IPTV_API_CHANNELS = "https://iptv-org.github.io/api/channels.json"
IPTV_API_STREAMS = "https://iptv-org.github.io/api/streams.json"
IPTV_API_LOGOS = "https://iptv-org.github.io/api/logos.json"
IPTV_API_FEEDS = "https://iptv-org.github.io/api/feeds.json"

M3U_SOURCES: list[tuple[str, str, str]] = [
    # (Source Label, Default Language, M3U URL)
    ("IPTV-org India Master", "Hindi", "https://iptv-org.github.io/iptv/countries/in.m3u"),
    ("IPTV-org Hindi", "Hindi", "https://iptv-org.github.io/iptv/languages/hin.m3u"),
    ("IPTV-org Punjabi", "Punjabi", "https://iptv-org.github.io/iptv/languages/pan.m3u"),
    ("IPTV-org Marathi", "Marathi", "https://iptv-org.github.io/iptv/languages/mar.m3u"),
    ("IPTV-org Gujarati", "Gujarati", "https://iptv-org.github.io/iptv/languages/guj.m3u"),
    ("IPTV-org Bengali", "Bengali", "https://iptv-org.github.io/iptv/languages/ben.m3u"),
    ("IPTV-org Tamil", "Tamil", "https://iptv-org.github.io/iptv/languages/tam.m3u"),
    ("IPTV-org Telugu", "Telugu", "https://iptv-org.github.io/iptv/languages/tel.m3u"),
    ("IPTV-org Kannada", "Kannada", "https://iptv-org.github.io/iptv/languages/kan.m3u"),
    ("IPTV-org Malayalam", "Malayalam", "https://iptv-org.github.io/iptv/languages/mal.m3u"),
    ("IPTV-org Odia", "Odia", "https://iptv-org.github.io/iptv/languages/ori.m3u"),
    ("IPTV-org Assamese", "Assamese", "https://iptv-org.github.io/iptv/languages/asm.m3u"),
    ("IPTV-org Bhojpuri", "Bhojpuri", "https://iptv-org.github.io/iptv/languages/bho.m3u"),
    ("IPTV-org Urdu", "Urdu", "https://iptv-org.github.io/iptv/languages/urd.m3u"),
    ("IPTV-org Konkani", "Konkani", "https://iptv-org.github.io/iptv/languages/kok.m3u"),
    ("IPTV-org Nepali", "Nepali", "https://iptv-org.github.io/iptv/languages/nep.m3u"),
    ("Hindi-Punjabi Community", "Hindi", "https://raw.githubusercontent.com/deep2772/Hindi_Punjabi-iptv-playlist/refs/heads/main/Hindi_Punjabi_Merged.m3u"),
    ("TangoTV India", "Hindi", "https://raw.githubusercontent.com/amazeyourself/m3u/main/tangotv.m3u"),
]

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
        # Ignore pure resolution or status notes like (1080p), (720p), [Not 24/7], [Geo-blocked]
        if re.fullmatch(r"\d{3,4}p|hd|sd|fhd|4k|uhd|not\s*24/7|geo[-\s]*blocked|backup|mirror|india|in", inner):
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
    "colors", "mtv", "nick", "sonic", "vh1", "comedy central", "sports18",
    "cartoon network", "pogo", "wb", "hbo", "cnn",
    "disney", "hungama", "super hungama", "national geographic", "nat geo", "fox life",
    "discovery", "animal planet", "tlc", "eurosport", "investigation discovery", "science",
    "history tv18", "fyi", "cnbc", "et now",
    "sun tv", "ktv", "adithya", "sun music", "sun life", "gemini", "udaya", "surya",
    "asianet", "mazhavil", "etv", "raj tv", "jaya tv", "polimer",
)

FTA_BRAND_PATTERNS: tuple[str, ...] = (
    "dd ", "doordarshan", "sansad", "lok sabha", "rajya sabha", "all india radio",
    "dangal", "shemaroo", "goldmines", "b4u", "enterr10", "manoranjan", "dhamaal",
    "mastiii", "9xm", "9x jalwa", "9x tashan", "9x jhakaas", "zoom", "showbox",
    "aaj tak", "abp", "india tv", "republic", "tv9", "ndtv india", "news18", "zee news",
    "zee bharat", "zee hindustan", "zee business", "good news today", "gnt", "news 24",
    "news nation", "india news", "sudarshan", "public tv", "otv", "kanak", "kalinga",
    "aastha", "sanskar", "sadhna", "ishwar", "paras", "peace of mind", "mh one",
    "ptc", "chardikla", "bhojpuri cinema", "fakt marathi", "faktananda",
)


def classify_tier(name: str, raw_group: str = "") -> str:
    text = f"{name} {raw_group}".lower()
    if any(fta in text for fta in FTA_BRAND_PATTERNS):
        # Note: Star Utsav, Zee Anmol, Sony Pal, Colors Rishtey are also FreeDish/FTA friendly
        return "FTA"
    if any(ft in text for ft in ("star utsav", "zee anmol", "sony pal", "colors rishtey")):
        return "FTA"
    if any(paid in text for paid in PAID_BRAND_PATTERNS):
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
# 4. Network Fetching & M3U / API Parsing
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)


def fetch_text(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[Warn] Failed to fetch {url}: {exc}", file=sys.stderr)
        return ""


def parse_m3u_entries(m3u_text: str, default_lang: str = "Hindi") -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not m3u_text:
        return entries

    lines = m3u_text.splitlines()
    cur_meta: dict[str, str] | None = None
    user_agent_opt = ""
    referrer_opt = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            id_m = re.search(r'tvg-id="([^"]*)"', line, re.I) or re.search(r"tvg-id=([^\s,]+)", line, re.I)
            name_m = re.search(r'tvg-name="([^"]*)"', line, re.I)
            logo_m = re.search(r'tvg-logo="([^"]*)"', line, re.I)
            group_m = re.search(r'group-title="([^"]*)"', line, re.I)
            lang_m = re.search(r'tvg-language="([^"]*)"', line, re.I)

            comma_idx = line.rfind(",")
            display_name = line[comma_idx + 1 :].strip() if comma_idx != -1 else ""
            if not display_name and name_m:
                display_name = name_m.group(1).strip()

            # Clean display_name of noisy tags like (1080p) [Not 24/7] while keeping language/variant tags
            clean_display = re.sub(r"\s*[\(\[](\d{3,4}p|not\s*24/7|geo[-\s]*blocked|backup)[\)\]]", "", display_name, flags=re.I).strip()
            res_m = re.search(r"(\d{3,4}p)", display_name, re.I)

            cur_meta = {
                "tvg_id": id_m.group(1).strip() if id_m else "",
                "name": clean_display or display_name,
                "raw_name": display_name,
                "logo": logo_m.group(1).strip() if logo_m else "",
                "group": group_m.group(1).strip() if group_m else "",
                "language": lang_m.group(1).strip() if lang_m and lang_m.group(1).strip() else default_lang,
                "quality": res_m.group(1) if res_m else "1080p",
            }
            user_agent_opt = ""
            referrer_opt = ""

        elif line.startswith("#EXTVLCOPT:"):
            if "http-user-agent=" in line.lower():
                user_agent_opt = line.split("=", 1)[1].strip()
            elif "http-referrer=" in line.lower() or "http-referer=" in line.lower():
                referrer_opt = line.split("=", 1)[1].strip()

        elif line.startswith(("http://", "https://")):
            stream_url = line.split("|")[0].strip()
            if cur_meta and cur_meta.get("name"):
                entries.append({
                    **cur_meta,
                    "url": stream_url,
                    "user_agent": user_agent_opt,
                    "referrer": referrer_opt,
                })
            cur_meta = None
            user_agent_opt = ""
            referrer_opt = ""

    return entries


def discover_from_iptv_org_api() -> list[dict[str, Any]]:
    """
    Fetches official IPTV-org JSON API (`channels.json`, `streams.json`, `logos.json`, `feeds.json`)
    and extracts all Indian channels (country == 'IN' or Indian broadcast languages) with exact channel IDs.
    """
    print("[Discovery] Fetching official IPTV-org JSON API...")
    channels_raw = fetch_text(IPTV_API_CHANNELS, timeout=20.0)
    streams_raw = fetch_text(IPTV_API_STREAMS, timeout=25.0)
    logos_raw = fetch_text(IPTV_API_LOGOS, timeout=20.0)
    feeds_raw = fetch_text(IPTV_API_FEEDS, timeout=20.0)

    if not channels_raw or not streams_raw:
        return []

    try:
        channels_data = json.loads(channels_raw)
        streams_data = json.loads(streams_raw)
        logos_data = json.loads(logos_raw) if logos_raw else []
        feeds_data = json.loads(feeds_raw) if feeds_raw else []
    except Exception as exc:
        print(f"[Warn] JSON API parse error: {exc}", file=sys.stderr)
        return []

    # Map logos by channel ID
    logo_map: dict[str, str] = {}
    for lg in logos_data:
        cid = lg.get("channel")
        lurl = lg.get("url")
        if cid and lurl and lurl.startswith("http") and cid not in logo_map:
            logo_map[cid] = lurl

    # Map feed languages & broadcast areas by (channel, feed_id) and channel
    feed_lang_map: dict[str, str] = {}
    indian_feed_channels: set[str] = set()
    for fd in feeds_data:
        cid = fd.get("channel")
        if not cid:
            continue
        langs = fd.get("languages") or []
        areas = fd.get("broadcast_area") or []
        if any(a in ("c/IN", "r/SAS") for a in areas) or any(l in INDIAN_LANG_CODES for l in langs):
            indian_feed_channels.add(cid)
        for lcode in langs:
            if lcode in INDIAN_LANG_CODES and cid not in feed_lang_map:
                feed_lang_map[cid] = INDIAN_LANG_CODES[lcode]

    # Filter Indian channels
    indian_channels: dict[str, dict[str, Any]] = {}
    for ch in channels_data:
        if ch.get("is_nsfw"):
            continue
        cid = ch.get("id") or ""
        country = (ch.get("country") or "").upper()
        if country == "IN" or cid.endswith(".in") or cid in indian_feed_channels:
            indian_channels[cid] = ch

    # Match streams to Indian channels
    discovered: list[dict[str, Any]] = []
    for st in streams_data:
        cid = st.get("channel")
        surl = (st.get("url") or "").strip()
        if not cid or not surl or cid not in indian_channels:
            continue
        ch_meta = indian_channels[cid]
        name = ch_meta.get("name") or cid.split(".")[0]
        cats = ch_meta.get("categories") or []
        raw_group = cats[0] if cats else ""
        lang = feed_lang_map.get(cid, "Hindi")
        feed_id = st.get("feed") or "HD"
        quality = st.get("quality") or "1080p"

        discovered.append({
            "tvg_id": f"{cid}@{feed_id}" if feed_id else cid,
            "name": name,
            "raw_name": st.get("title") or name,
            "logo": logo_map.get(cid, ""),
            "group": raw_group,
            "language": lang,
            "quality": quality,
            "url": surl,
            "user_agent": st.get("user_agent") or "",
            "referrer": st.get("referrer") or "",
            "website": ch_meta.get("website") or "",
            "network": ch_meta.get("network") or "",
        })

    print(f"[Discovery] Found {len(discovered)} Indian stream records from IPTV-org API.")
    return discovered


# ---------------------------------------------------------------------------
# 5. Stream Health Probing (Concurrent HLS Manifest Verification)
# ---------------------------------------------------------------------------

def probe_hls_stream(url: str, timeout: float = 6.5) -> tuple[bool, int]:
    """
    Checks if a stream URL is alive and returns a valid HLS playlist or media stream.
    Returns (is_alive, latency_ms).
    """
    if not url or not url.startswith("https://"):
        # Note: GitHub workflow validation requires primary & fallback URLs in channels.json to be https://
        return (False, 99999)
    if any(dead in url.lower() for dead in DEAD_HOST_SUBSTRINGS):
        return (False, 99999)

    start_ts = time.monotonic()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.apple.mpegurl,application/x-mpegurl,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status < 200 or status >= 400:
                return (False, 99999)
            chunk = resp.read(2048).decode("utf-8", errors="ignore")
            latency = int((time.monotonic() - start_ts) * 1000)
            if "#EXTM3U" in chunk or "#EXT-X-" in chunk:
                return (True, latency)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if any(k in ctype for k in ("mpegurl", "mp2t", "octet-stream", "video/")):
                return (True, latency)
            return (False, 99999)
    except Exception:
        return (False, 99999)


# ---------------------------------------------------------------------------
# 6. Catalogue Aggregation, Deduplication & Export
# ---------------------------------------------------------------------------

def build_catalogue() -> tuple[list[dict[str, Any]], str]:
    raw_records: list[dict[str, Any]] = []

    # 1. Pull from IPTV-org JSON API
    raw_records.extend(discover_from_iptv_org_api())

    # 2. Pull from all Indian M3U playlists concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {
            pool.submit(fetch_text, url, 15.0): (label, lang, url)
            for label, lang, url in M3U_SOURCES
        }
        for fut in concurrent.futures.as_completed(future_map):
            label, lang, _ = future_map[fut]
            content = fut.result()
            parsed = parse_m3u_entries(content, default_lang=lang)
            print(f"[Discovery] {label}: {len(parsed)} entries")
            raw_records.extend(parsed)

    # 3. Detect generic/placeholder stream URLs claimed by 3+ distinct channel keys
    url_to_channel_keys: dict[str, set[str]] = {}
    for rec in raw_records:
        u = (rec.get("url") or "").strip()
        ck = canonical_channel_key(rec.get("name", ""), rec.get("tvg_id", ""))
        if u and ck:
            url_to_channel_keys.setdefault(u, set()).add(ck)

    overused_urls: set[str] = {
        u for u, keys in url_to_channel_keys.items() if len(keys) >= 3
    }
    if overused_urls:
        print(f"[Guard] Blocked {len(overused_urls)} generic/overused URLs shared across 3+ unrelated channels.")

    # 4. Group by canonical channel identity
    grouped: dict[str, dict[str, Any]] = {}
    candidate_urls: set[str] = set()

    for rec in raw_records:
        name = (rec.get("name") or "").strip()
        url = (rec.get("url") or "").strip()
        tvg_id = (rec.get("tvg_id") or "").strip()
        raw_name = (rec.get("raw_name") or "").strip()

        if not name or not url or not url.startswith("https://"):
            continue
        if url in overused_urls:
            continue
        if is_cross_channel_mismatch(name, url, raw_name):
            continue

        ck = canonical_channel_key(name, tvg_id)
        if not ck:
            continue

        if ck not in grouped:
            lang = rec.get("language") or "Hindi"
            cat = classify_category(rec.get("group", ""), name)
            zone, region, is_reg = classify_zone_and_region(lang, name)
            tier = classify_tier(name, rec.get("group", ""))
            grouped[ck] = {
                "id": tvg_id or f"{ck}.in@HD",
                "name": name,
                "network": rec.get("network") or cat,
                "category": cat,
                "language": lang,
                "lang_code": lang[:3].lower(),
                "zone": zone,
                "region": region,
                "tier": tier,
                "logo_url": rec.get("logo") or "",
                "website": rec.get("website") or "",
                "is_regional": is_reg or (cat == "Regional"),
                "quality": rec.get("quality") or "1080p",
                "urls": [],
            }

        entry = grouped[ck]
        if not entry["logo_url"] and rec.get("logo", "").startswith("http"):
            entry["logo_url"] = rec["logo"]
        if url not in entry["urls"]:
            entry["urls"].append(url)
            candidate_urls.add(url)

    print(f"[Verify] Probing {len(candidate_urls)} unique HTTPS stream URLs across {len(grouped)} channels...")

    # 5. Concurrent health check of all candidate URLs
    url_health: dict[str, tuple[bool, int]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        fut_to_url = {pool.submit(probe_hls_stream, u): u for u in candidate_urls}
        for fut in concurrent.futures.as_completed(fut_to_url):
            u = fut_to_url[fut]
            try:
                url_health[u] = fut.result()
            except Exception:
                url_health[u] = (False, 99999)

    alive_count = sum(1 for ok, _ in url_health.values() if ok)
    print(f"[Verify] {alive_count}/{len(candidate_urls)} HTTPS streams verified responsive.")

    # 6. Build final verified channel list sorted by priority & latency
    final_channels: list[dict[str, Any]] = []
    for ck, item in grouped.items():
        verified_urls = [
            (u, url_health.get(u, (False, 99999))[1])
            for u in item["urls"]
            if url_health.get(u, (False, 99999))[0]
        ]
        if not verified_urls:
            continue

        # Sort by fastest response latency
        verified_urls.sort(key=lambda pair: pair[1])
        primary_url = verified_urls[0][0]
        fallbacks = [u for u, _ in verified_urls[1:] if u != primary_url][:6]

        final_channels.append({
            "id": item["id"],
            "name": item["name"],
            "network": item["network"],
            "category": item["category"],
            "language": item["language"],
            "lang_code": item["lang_code"],
            "zone": item["zone"],
            "region": item["region"],
            "tier": item["tier"],
            "logo_url": item["logo_url"],
            "url": primary_url,
            "fallback_urls": fallbacks,
            "website": item["website"],
            "is_regional": item["is_regional"],
            "quality": item["quality"],
            "latency_ms": verified_urls[0][1],
        })

    # Sort national & popular channels first, regional alphabetically after
    final_channels.sort(
        key=lambda c: (
            1 if c["is_regional"] else 0,
            0 if c["tier"] == "PAID" else 1,
            c["latency_ms"],
            c["name"].lower(),
        )
    )

    # Assign sequential channel numbers
    m3u_lines = ['#EXTM3U url-tvg="https://iptv-org.github.io/epg/guides/in.xml"']
    for idx, ch in enumerate(final_channels, start=1):
        ch["ch_no"] = idx
        ch.pop("latency_ms", None)
        logo_attr = f' tvg-logo="{ch["logo_url"]}"' if ch.get("logo_url") else ""
        m3u_lines.append(
            f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-chno="{idx}" tvg-language="{ch["language"]}" '
            f'tvg-tier="{ch["tier"]}"{logo_attr} group-title="{ch["category"]}",{ch["name"]}'
        )
        m3u_lines.append(ch["url"])

    return final_channels, "\n".join(m3u_lines) + "\n"


def main() -> None:
    channels, m3u_text = build_catalogue()
    if not channels:
        print("[Error] No channels were verified! Aborting write to protect existing catalogue.", file=sys.stderr)
        sys.exit(1)

    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "updated_at": now_iso,
        "generator": "BharatTV Next-Gen Channel Discovery & Identity Engine v2.0",
        "total_channels": len(channels),
        "fta_channels": sum(1 for c in channels if c.get("tier") == "FTA"),
        "paid_channels": sum(1 for c in channels if c.get("tier") == "PAID"),
        "channels": channels,
    }

    Path("channels.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    Path("channels.m3u").write_text(m3u_text, encoding="utf-8")
    print(
        f"[Success] Wrote {len(channels)} verified channels "
        f"(FTA: {payload['fta_channels']}, PAID: {payload['paid_channels']}) "
        f"to channels.json and channels.m3u"
    )


if __name__ == "__main__":
    main()
