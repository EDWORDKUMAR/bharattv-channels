#!/usr/bin/env python3
"""
Bharat TV - Automated Channel Discovery, Verification & JSON Generator
Runs hourly via GitHub Actions or locally to discover maximum live Indian & Sports/Movies
IPTV channels, verify real HLS playback health (including AES-128 & fMP4), and publish
validated channels.json / channels.m3u catalogues.
"""

import os
import re
import ssl
import json
import time
import urllib.request
import urllib.error
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

SSL_CONTEXT = ssl.create_default_context()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

# Indian curated & regional language playlists (all channels kept, PK spoofs excluded)
INDIAN_PLAYLIST_SOURCES = [
    ("https://iptv-org.github.io/iptv/countries/in.m3u", "Hindi"),
    ("https://raw.githubusercontent.com/iptv-org/iptv/master/streams/in.m3u", "Hindi"),
    ("https://iptv-org.github.io/iptv/languages/hin.m3u", "Hindi"),
    ("https://iptv-org.github.io/iptv/languages/pan.m3u", "Punjabi"),
    ("https://iptv-org.github.io/iptv/languages/mar.m3u", "Marathi"),
    ("https://iptv-org.github.io/iptv/languages/guj.m3u", "Gujarati"),
    ("https://iptv-org.github.io/iptv/languages/ben.m3u", "Bengali"),
    ("https://iptv-org.github.io/iptv/languages/tam.m3u", "Tamil"),
    ("https://iptv-org.github.io/iptv/languages/tel.m3u", "Telugu"),
    ("https://iptv-org.github.io/iptv/languages/kan.m3u", "Kannada"),
    ("https://iptv-org.github.io/iptv/languages/mal.m3u", "Malayalam"),
    ("https://iptv-org.github.io/iptv/languages/ori.m3u", "Odia"),
    ("https://iptv-org.github.io/iptv/languages/asm.m3u", "Assamese"),
    ("https://iptv-org.github.io/iptv/languages/bho.m3u", "Bhojpuri"),
    ("https://iptv-org.github.io/iptv/languages/urd.m3u", "Urdu"),
    ("https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_india.m3u8", "Hindi"),
    ("https://raw.githubusercontent.com/amazeyourself/m3u/main/tangotv.m3u", "Hindi"),
    ("https://raw.githubusercontent.com/deep2772/Hindi_Punjabi-iptv-playlist/refs/heads/main/Hindi_Punjabi_Merged.m3u", "Hindi"),
    ("https://raw.githubusercontent.com/project9793/hindi-tv/main/sports.m3u", "Hindi"),
    ("https://raw.githubusercontent.com/project9793/hindi-tv/main/movies.m3u", "Hindi"),
    ("https://raw.githubusercontent.com/karanjaiswalp-cell/hindi-4k-iptv/main/Hindi-HD-Playable.m3u", "Hindi"),
]

# Global category playlists to maximize working Sports, Movies, Kids, Music & Doc channels
GLOBAL_CATEGORY_SOURCES = [
    ("https://iptv-org.github.io/iptv/categories/sports.m3u", "English"),
    ("https://iptv-org.github.io/iptv/categories/movies.m3u", "English"),
    ("https://iptv-org.github.io/iptv/categories/animation.m3u", "English"),
    ("https://iptv-org.github.io/iptv/categories/kids.m3u", "English"),
    ("https://iptv-org.github.io/iptv/categories/music.m3u", "English"),
    ("https://iptv-org.github.io/iptv/categories/documentary.m3u", "English"),
]

IPTV_ORG_API_CHANNELS = "https://iptv-org.github.io/api/channels.json"
IPTV_ORG_API_STREAMS = "https://iptv-org.github.io/api/streams.json"
IPTV_ORG_API_LOGOS = "https://iptv-org.github.io/api/logos.json"
IPTV_ORG_API_FEEDS = "https://iptv-org.github.io/api/feeds.json"

BAD_DOMAINS = [
    'd1g8wgjurz8via.cloudfront.net',
    '103.151.60.162',
    '103.167.255.18',
    '103.178.78.151',
    '103.175.73.12:8080',
    '103.135.253.32',
    'gpcdn.net/live/sub_hd_abr',
    'ml-pull-dvc-myco.io',
    'dinesh29.com.np'
]

# Verified curated seeds prioritized first when alive
CORE_SEEDS = [
    {
        "name": "Goldmines",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_GOLDMINES/images/LOGO_HD/image.png",
        "urls": [
            "https://mumt04.tangotv.in/m18aqlK4GOLDMINES/index.m3u8",
            "https://streams.tangotv.in/GOLDMINES/ORIGIN/index.m3u8"
        ]
    },
    {
        "name": "Goldmines 2",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://dtil.tmsimg.com/assets/s143087_ld_h15_aa.png?lock=720x540",
        "urls": [
            "https://mumt03.tangotv.in/Dsly5z3HGOLDMINES2/index.m3u8",
            "https://streams.tangotv.in/GOLDMINES2/ORIGIN/index.m3u8"
        ]
    },
    {
        "name": "Goldmines Action",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://yt3.googleusercontent.com/_X6U6bMLF-pTu5wBMFwsSI6aubGrXk2B0kUKdGiLIMqFLyDIne4Ot4ro76BS1S8fX3pWcCwS=s900-c-k-c0x00ffffff-no-rj",
        "urls": [
            "https://mumt03.tangotv.in/Dsly5z3HGOLDMINESACTION/index.m3u8",
            "https://streams.tangotv.in/GOLDMINESACTION/ORIGIN/index.m3u8"
        ]
    },
    {
        "name": "Goldmines Bollywood",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://i.imgur.com/6mNQ9mM.png",
        "urls": [
            "https://mumt03.tangotv.in/Dsly5z3HGOLDMINESBOLLYWOOD/index.m3u8",
            "https://streams.tangotv.in/GOLDMINESBOLLYWOOD/ORIGIN/index.m3u8"
        ]
    },
    {
        "name": "Goldmines Movies",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://dvdh7g0f0hwck.cloudfront.net/assets/images/channel/GoldminesMovies_Transparent_9b7db248-999e-4200-a459-6cc594650f3d.png",
        "urls": [
            "https://mumt04.tangotv.in/m18aqlK4GOLDMINEMOVIES/index.m3u8",
            "https://streams.tangotv.in/GOLDMINEMOVIES/ORIGIN/index.m3u8"
        ]
    },
    {
        "name": "Sony SAB HD",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s159099_ld_h15_ab.png?lock=720x540",
        "urls": [
            "http://38.96.178.205/SONYHD/index.m3u8"
        ]
    },
    {
        "name": "Sony Entertainment Television HD",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_ENTERTAINMENT_TELEVISION/images/LOGO_HD/image.png",
        "urls": [
            "http://38.96.178.205/SONYHD/index.m3u8"
        ]
    },
    {
        "name": "Sony Max HD",
        "category": "Movies",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s157590_ld_h15_aa.png?lock=720x540",
        "urls": [
            "https://drk6xq0vhn.gpcdn.net/hls/set_max_m4fb8dz2wp6kr9s_720/index.m3u8"
        ]
    },
    {
        "name": "Sony Max 2",
        "category": "Movies",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s143801_ld_h15_aa.png?lock=720x540",
        "urls": [
            "http://107.167.16.138/sonymax2/index.m3u8?token=test"
        ]
    },
    {
        "name": "Sony Sports Ten 3 Hindi HD",
        "category": "Sports",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_TEN_3/images/LOGO_HD/image.png",
        "urls": [
            "https://r2.amml.in/sony-ten-3-hd/live.m3u8"
        ]
    },
    {
        "name": "DD Sports",
        "category": "Sports",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://dtil.tmsimg.com/assets/s158255_ld_h15_aa.png?lock=720x540",
        "urls": [
            "https://d3qs3d2rkhfqrt.cloudfront.net/out/v1/b17adfe543354fdd8d189b110617cddd/index.m3u8",
            "https://cdn.pishow.tv/ott/live/1161/master.m3u8",
            "https://mumbai-edge.smartplaytv.in/DDSportsHD/index.m3u8"
        ]
    },
    {
        "name": "Willow Sports",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "",
        "urls": [
            "https://d36r8jifhgsk5j.cloudfront.net/Willow_TV.m3u8"
        ]
    },
    {
        "name": "Sony KAL Hindi",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s157590_ld_h15_aa.png?lock=720x540",
        "urls": [
            "https://wurlsonypicturestv.global.transmit.live/hls/68deeb1c0238cda82df543dd/v1/spt_sonykal_1/lg_us/latest/main/hls/playlist.m3u8"
        ]
    },
    {
        "name": "Sony Wah",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_WAH/images/LOGO_HD/image.png",
        "urls": [
            "http://163.61.226.31:9981/stream/channelid/1743466790?profile=pass"
        ]
    },
    {
        "name": "Sony Pal",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_PAL/images/LOGO_HD/image.png",
        "urls": [
            "http://163.61.226.31:9981/stream/channelid/1571254341?profile=pass",
            "https://fta.ektv.in/live/53/53_0.m3u8"
        ]
    },
    {
        "name": "Star Bharat HD",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_BHARAT/images/LOGO_HD/image.png",
        "urls": [
            "https://d1taaads3ztvmu.cloudfront.net/120723/smil:lifeokuk.smil/playlist.m3u8?hdnts=st=1735898689~exp=1835898688~acl=*~hmac=f5fe24724fe05481e3841f9eb5ab8efdee0a3dd83645ae9dcf45703f525bab7b",
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/gb/YuppTV/UtsavBharat.m3u8"
        ]
    },
    {
        "name": "Star Plus HD",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_PLUS/images/LOGO_HD/image.png",
        "urls": [
            "https://d1rc86nwwc9fag.cloudfront.net/260723/starplusuk_2500/chunks.m3u8",
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/gb/YuppTV/UtsavPlus.m3u8"
        ]
    },
    {
        "name": "Star Gold",
        "category": "Movies",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_GOLD/images/LOGO_HD/image.png",
        "urls": [
            "https://fta.ektv.in/live/52/52_0.m3u8"
        ]
    },
    {
        "name": "Star Maa HD",
        "category": "Entertainment",
        "language": "Telugu",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_MAA/images/LOGO_HD/image.png",
        "urls": [
            "https://da86m1sqpm3o0.cloudfront.net/28072023/smil:starmaa1.smil/chunklist_b2628000.m3u8"
        ]
    },
    {
        "name": "Star Maa Movies HD",
        "category": "Movies",
        "language": "Telugu",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_MAA_MOVIES/images/LOGO_HD/image.png",
        "urls": [
            "https://da86m1sqpm3o0.cloudfront.net/28072023/smil:maamovies.smil/chunklist_b2628000.m3u8"
        ]
    },
    {
        "name": "Star Pravah HD",
        "category": "Entertainment",
        "language": "Marathi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_PRAVAH/images/LOGO_HD/image.png",
        "urls": [
            "https://da86m1sqpm3o0.cloudfront.net/28072023/smil:starpravah.smil/chunklist_b1928000.m3u8"
        ]
    },
    {
        "name": "Star Utsav",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_UTSAV/images/LOGO_HD/image.png",
        "urls": [
            "http://163.61.226.31:9981/stream/channelid/894286890?profile=pass"
        ]
    },
    {
        "name": "Star Utsav Movies",
        "category": "Movies",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_UTSAV_MOVIES/images/LOGO_HD/image.png",
        "urls": [
            "http://163.61.226.31:9981/stream/channelid/1225596390?profile=pass"
        ]
    },
    {
        "name": "Starnet",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://i.imgur.com/J3jB7Kr.png",
        "urls": [
            "https://5a1178b42cc03.streamlock.net/8220/8220/playlist.m3u8"
        ]
    },
    {
        "name": "Utsav Bharat",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://i.imgur.com/IQ2n0WY.png",
        "urls": [
            "https://d1taaads3ztvmu.cloudfront.net/120723/smil:lifeokuk.smil/playlist.m3u8?hdnts=st=1735898689~exp=1835898688~acl=*~hmac=f5fe24724fe05481e3841f9eb5ab8efdee0a3dd83645ae9dcf45703f525bab7b"
        ]
    },
    {
        "name": "Utsav Plus",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://i.imgur.com/TERVtWT.png",
        "urls": [
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/gb/YuppTV/UtsavPlus.m3u8"
        ]
    }
]

TOP_PRIORITY_BRANDS = [
    # Movies
    "goldmines", "zee cinema", "sony max", "star gold", "colors cineplex",
    "b4u movies", "shemaroo movies", "bhojpuri cinema", "b4u kadak", "manoranjan movies",
    "manoranjan grand", "sony pix", "star gold 2", "sony max 2", "zee action", "zee classic",
    "zee bollywood", "zee anmol cinema", "shemaroo classic", "dhinchaak", "cinema tv",
    "maha movie", "movie plus", "enterr10 movies", "bflix", "pitaara", "shubh cinema",
    # Sports
    "sony sports ten 3", "sony sports ten 1", "sony sports ten 2", "sony sports ten 5",
    "sony sports ten 4", "sony sports", "dd sports", "star sports", "sports18",
    "willow sports", "eurosport", "cricket gold", "kabaddi 24x7",
    # Entertainment
    "sony sab", "colors hd", "colors", "star plus", "zee tv",
    "sony entertainment television", "set india", "sony tv", "&tv", "and tv",
    "star bharat", "dangal 2", "dangal", "star utsav", "colors rishtey",
    "zee anmol", "sony pal", "shemaroo tv", "shemaroo umang", "big magic",
    "bindass", "sony wah", "sony kal", "enterr10", "manoranjan tv",
    # News
    "aaj tak", "abp news", "india tv", "zee news", "republic bharat", "news18 india",
    "ndtv india", "times now navbharat", "tv9 bharatvarsh", "dd news", "dd india",
    "zee bharat", "zee hindustan", "news nation", "news 24", "good news today",
    "bharat 24", "sansad tv", "times now", "ndtv 24x7", "republic tv", "cnn news 18",
    "india today", "wion", "cnbc awaaz", "zee business", "et now swadesh",
    # Music
    "9xm", "mastiii", "mtv", "b4u music", "9x jalwa", "9x tashan", "zoom", "zing",
    "music india", "balle balle",
    # Kids
    "cartoon network", "pogo", "hungama", "nickelodeon", "nick", "sonic",
    "disney", "sony yay", "discovery kids", "gubbare", "etv bal bharat",
    # Devotional & DD
    "aastha", "sanskar", "sadhna", "bhakti sagar", "arihant", "jinvaani",
    "paras", "divya tv", "ishwar tv", "disha tv", "shubh tv", "lord buddha",
    "subhavaartha", "svbc", "dd national", "dd kisan", "dd bharati", "dd retro"
]

FOREIGN_KEYWORDS = [
    'romania', 'russia', 'russian', 'uk', 'usa', 'america', 'american',
    'canada', 'australia', 'france', 'french', 'germany', 'german', 'spain',
    'spanish', 'italy', 'italian', 'albania', 'dubai', 'qatar', 'kuwait',
    'saudi', 'turkey', 'turkish', 'china', 'chinese', 'japan', 'japanese',
    'korea', 'korean', 'vietnam', 'thailand', 'malaysia', 'indonesia',
    'philippines', 'brazil', 'mexico', 'argentina', 'colombia', 'nigeria',
    'kenya', 'south africa', 'egypt', 'iran', 'iraq', 'pakistan', 'afghanistan',
    'bangladesh', 'nepal', 'sri lanka', 'rexdale', 'calgary', 'toronto',
    'london', 'europe', 'european', 'apac', 'mena', 'americas', 'latam',
    'fifa', 'fifa+', 'sports first', 'goal tv', 'tennis channel', 'sportsgrid',
    '5plus', '5stars', 'a spor', 'fight network', 'red bull tv', 'motorvision',
    'mavtv', 'canal+', 'bein', 'sky sports', 'espn', 'fox sports'
]

REGIONAL_LANGS = [
    'tamil', 'telugu', 'kannada', 'malayalam', 'bhojpuri', 'bengali',
    'bangla', 'gujarati', 'odia', 'oriya', 'punjabi', 'marathi', 'assamese', 'urdu'
]

FOREIGN_COUNTRY_ID_RE = re.compile(
    r'\.(us|ru|ua|tr|il|fr|es|de|ro|it|pl|nl|br|mx|ar|co|cl|pe|cn|jp|kr|vn|th|id|ph|eg|sa|ae|qa|kw|ir|pk|bd|lk|np|af)@',
    re.I
)


def norm_key(name):
    if not name:
        return ""
    raw = name.lower()
    raw = re.sub(r'\bset\s*max\b', 'sonymax', raw)
    raw = re.sub(r'\bset\s*india\b', 'sonyentertainmenttelevision', raw)
    raw = re.sub(r'\bsony\s*set\b', 'sonyentertainmenttelevision', raw)
    raw = re.sub(r'\b(sub|sab)\s*tv\b', 'sonysab', raw)
    raw = re.sub(r'\(\s*(hd|sd|fhd|4k|uhd)\s*\)|\[\s*(hd|sd|fhd|4k|uhd)\s*\]', ' ', raw)
    clean = re.sub(r'\(.*?\)|\[.*?\]', ' ', raw)
    clean = re.sub(r'\b(hd|sd|fhd|4k|uhd|official|live|stream)\b', ' ', clean)
    return re.sub(r'[^a-z0-9]', '', clean)


def canonical_channel_key(name: str, tvg_id: str = "") -> str:
    """Produces an identity-safe key that preserves channel identity and numbers."""
    raw = (name or "").strip().lower()
    if not raw and tvg_id:
        raw = tvg_id.split("@")[0].replace(".in", "").lower()
    raw = re.sub(r'\bset\s*max\b', 'sonymax', raw)
    raw = re.sub(r'\bset\s*india\b', 'sonyentertainmenttelevision', raw)
    raw = re.sub(r'\b(sub|sab)\s*tv\b', 'sonysab', raw)
    cleaned = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", raw)
    cleaned = re.sub(r"\b(hd|sd|fhd|4k|uhd|official|live|stream)\b", " ", cleaned)
    return re.sub(r"[^a-z0-9]+", "", cleaned)


def known_channel_mismatch(name, url):
    """Reject confirmed dead hosts or cross-channel/Pakistan spoof feeds."""
    if not url or not (url.startswith('http://') or url.startswith('https://')):
        return True
    u = url.strip().lower()
    if any(bad in u for bad in BAD_DOMAINS):
        return True

    n = norm_key(name)
    if 'pakistan' in n or re.search(r'(\.pk\b|/pakistan/|/pk/)', u):
        return True
    if ('sonymax' in n or 'setmax' in n) and any(x in u for x in ('zeecinema', '/live/53/', 'colorscineplex', 'dangal', 'shemaroo', 'b4u')):
        return True
    if 'stargold' in n and any(x in u for x in ('colorscineplex', '/live/52/', '/live/47/')):
        return True
    if 'starsports' in n and any(x in u for x in (
        'b17adfe543354fdd8d189b110617cddd', '/live/1161/',
        'nellaiiptv.com/sdmedia', 'sportsgrid', 'cricketgold', 'tennis2'
    )):
        return True
    if ('tensports' in n or 'sonyten' in n or 'eurosport' in n) and any(x in u for x in (
        'b17adfe543354fdd8d189b110617cddd', '/live/1161/', 'nellaiiptv.com/sdmedia', 'cricketgold'
    )):
        return True
    if 'sonysab' in n and any(x in u for x in ('colors', 'colorsapac', 'zeetv', 'dangal', 'shemaroo')):
        return True
    return False


PAID_BRAND_PATTERNS = (
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
    "asianet", "mazhavil", "etv", "raj tv", "jaya tv", "polimer", "willow"
)

FTA_BRAND_PATTERNS = (
    "dd", "doordarshan", "sansad", "lok sabha", "rajya sabha", "all india radio",
    "star utsav", "zee anmol", "sony pal", "sony wah", "colors rishtey",
    "dangal", "shemaroo", "goldmines", "b4u", "enterr10", "manoranjan", "dhamaal",
    "mastiii", "9xm", "9x jalwa", "9x tashan", "9x jhakaas", "zoom", "showbox",
    "aaj tak", "abp", "india tv", "republic", "tv9", "ndtv", "news18", "zee news",
    "zee bharat", "zee hindustan", "zee business", "good news today", "gnt", "news 24",
    "news nation", "india news", "sudarshan", "public tv", "otv", "kanak", "kalinga",
    "surya samachar", "ktv bangla", "etv bharat",
    "aastha", "sanskar", "sadhna", "ishwar", "paras", "peace of mind", "mh one",
    "ptc", "chardikla", "bhojpuri cinema", "fakt marathi", "faktananda"
)

_PAID_RE = re.compile(rf"(?<!\w)(?:{'|'.join(re.escape(p) for p in PAID_BRAND_PATTERNS)})(?!\w)", re.IGNORECASE)
_FTA_RE = re.compile(rf"(?<!\w)(?:{'|'.join(re.escape(p) for p in FTA_BRAND_PATTERNS)})(?!\w)", re.IGNORECASE)
_FTA_REGIONAL_NEWS_RE = re.compile(r"(?<!\w)(?:zee|asianet|polimer|etv|sun)\b.*\b(?:news|samachar|khabar|seithigal)(?!\w)", re.IGNORECASE)


def classify_tier(name: str) -> str:
    clean = (name or "").strip().lower()
    if not clean:
        return "FTA"
    if _FTA_RE.search(clean) or _FTA_REGIONAL_NEWS_RE.search(clean):
        return "FTA"
    if _PAID_RE.search(clean):
        return "PAID"
    return "FTA"


def map_category(raw_group, name):
    g = (raw_group or "").lower()
    n = (name or "").lower()
    combined = f"{g} {n}"

    if any(k in combined for k in ['sport', 'cricket', 'football', 'fifa', 'wwe', 'willow']):
        return "Sports"
    if any(k in combined for k in ['cinema', 'movie', 'film', 'goldmines', 'box office', 'cine', 'sony max']):
        return "Movies"
    if any(k in combined for k in ['kid', 'cartoon', 'pogo', 'disney', 'anime', 'hungama', 'nickelodeon', 'sonic', 'sony yay']):
        return "Kids"
    if any(k in combined for k in ['news', 'samachar', 'khabar', 'aaj tak', 'abp', 'ndtv', 'republic', 'zee news']):
        return "News"
    if any(k in combined for k in ['music', 'gaana', 'sangeet', 'song', '9xm', 'mtv', 'b4u music', 'zoom']):
        return "Music"
    if any(k in combined for k in ['bhakti', 'devotional', 'religio', 'aarti', 'mandir', 'dharma', 'aastha', 'sanskar', 'sadhna', 'ishwar']):
        return "Devotional"
    if any(k in combined for k in ['business', 'bazaar', 'market', 'money', 'et now', 'cnbc', 'sensex']):
        return "Business"
    if any(k in combined for k in ['discovery', 'history', 'nat geo', 'science', 'education', 'gyan', 'documentary']):
        return "Education"
    if any(k in combined for k in ['bhojpuri', 'punjabi', 'marathi', 'gujarati', 'bengali', 'tamil', 'telugu', 'kannada', 'malayalam', 'odia', 'assamese']):
        return "Regional"
    return "Entertainment"


def detect_language(name, raw_lang="Hindi"):
    n = (name or "").lower()
    rl = (raw_lang or "").strip()
    if any(k in n for k in ['punjabi', 'ptc', 'apna punjab', 'pitaara']):
        return "Punjabi"
    if any(k in n for k in ['bhojpuri', 'b4u bhojpuri', 'dabangg', 'ananya']):
        return "Bhojpuri"
    if any(k in n for k in ['gujarat', 'gujarati', 'colors gujarati']):
        return "Gujarati"
    if any(k in n for k in ['marathi', 'zee 24 taas', 'colors marathi', 'pravah']):
        return "Marathi"
    if any(k in n for k in ['bangla', 'bengali', 'zee 24 ghanta', 'jalsha', 'sony aath']):
        return "Bengali"
    if any(k in n for k in ['tamil', 'sun tv', 'jaya', 'polimer', 'star vijay']):
        return "Tamil"
    if any(k in n for k in ['telugu', 'etv', 'gemini', 'star maa']):
        return "Telugu"
    if any(k in n for k in ['kannada', 'udaya', 'colors kannada', 'suvarna']):
        return "Kannada"
    if any(k in n for k in ['malayalam', 'asianet', 'surya', 'mazhavil']):
        return "Malayalam"
    if any(k in n for k in ['odia', 'oriya', 'sarthak', 'otv', 'kalinga', 'kanak']):
        return "Odia"
    if any(k in n for k in ['assam', 'dy 365', 'prag', 'rang', 'rengoni']):
        return "Assamese"
    if any(k in n for k in ['urdu', 'ete', 'kashir', 'gulistan']):
        return "Urdu"
    if any(k in n for k in ['english', 'times now', 'cnn', 'bbc', 'wion', 'sony pix', 'willow']):
        return "English"
    return rl or "Hindi"


def is_channel_foreign(ch):
    name = (ch.get('name') if isinstance(ch, dict) else str(ch or '')).lower()
    for fw in FOREIGN_KEYWORDS:
        if not fw.isalnum():
            if fw in name:
                return True
        else:
            if re.search(r'\b' + re.escape(fw) + r'\b', name):
                if fw == 'uk' and ('uttarakhand' in name or 'up & uk' in name or 'up uk' in name):
                    continue
                return True
    return False


def get_channel_priority_score(ch):
    if isinstance(ch, dict):
        name = (ch.get('name') or '').lower()
        cat = ch.get('category', '')
        lang = (ch.get('language') or '').lower()
    else:
        name = (str(ch) or '').lower()
        cat = ''
        lang = ''

    if is_channel_foreign(name):
        return -1000
    for idx, brand in enumerate(TOP_PRIORITY_BRANDS):
        if brand in name:
            return 3000 - (idx * 10)
    if cat == 'Regional' or any(rl == lang for rl in REGIONAL_LANGS):
        return 500
    return 1000


def _fetch_text(url, timeout=6):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
        data = response.read(131072)
        return data.decode('utf-8', errors='ignore'), response.geturl()


def _fetch_bytes(url, timeout=5, byte_range='bytes=0-2048'):
    headers = dict(HEADERS)
    if byte_range:
        headers['Range'] = byte_range
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
            return response.read(2048), response.geturl()
    except urllib.error.HTTPError as e:
        if e.code == 416 and byte_range:
            req2 = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req2, timeout=timeout, context=SSL_CONTEXT) as response2:
                return response2.read(2048), response2.geturl()
        raise


def _check_media_playlist(child_text, child_final_url, timeout=5):
    if '#EXTM3U' not in child_text[:128].upper():
        return False

    # Reject hardware-DRM gated playlists (Widevine / FairPlay / PlayReady / SAMPLE-AES)
    upper_text = child_text.upper()
    if 'SAMPLE-AES' in upper_text or 'WIDEVINE' in upper_text or 'PLAYREADY' in upper_text or 'COM.APPLE.FPS' in upper_text:
        return False

    is_aes128 = 'METHOD=AES-128' in upper_text
    if is_aes128:
        key_match = re.search(r'#EXT-X-KEY:[^\r\n]*URI="([^"]+)"', child_text, re.I)
        if key_match:
            key_url = urljoin(child_final_url, key_match.group(1).strip())
            if key_url.startswith(('http://', 'https://')):
                try:
                    kbytes, _ = _fetch_bytes(key_url, timeout=timeout, byte_range=None)
                    if len(kbytes) < 16 or kbytes.lstrip().startswith((b'<', b'{')):
                        return False
                except Exception:
                    return False

    # Check fMP4 init segment if present, otherwise first media segment
    map_match = re.search(r'#EXT-X-MAP:[^\r\n]*URI="([^"]+)"', child_text, re.I)
    segment = next((line.strip() for line in child_text.splitlines()
                    if line.strip() and not line.startswith('#')), None)
    probe_rel = map_match.group(1).strip() if map_match else segment
    if not probe_rel:
        return '#EXTINF:' in child_text and '#EXT-X-TARGETDURATION:' in child_text

    media_url = urljoin(child_final_url, probe_rel)
    sample, _ = _fetch_bytes(media_url, timeout=timeout, byte_range='bytes=0-2048')
    if not sample or len(sample) < 8:
        return False
    lead = sample.lstrip().lower()
    if lead.startswith((b'<html', b'<!doc', b'<?xml', b'{')):
        return False

    if is_aes128:
        return len(sample) >= 188
    if map_match or sample[4:8] in (b'ftyp', b'styp', b'moof', b'sidx', b'mdat'):
        return True
    if len(sample) >= 188 and sample[0] == 0x47:
        return True
    # ADTS AAC or ID3 audio-only streams
    if len(sample) >= 4 and ((sample[0] == 0xFF and (sample[1] & 0xF0) == 0xF0) or sample[:3] == b'ID3'):
        return True
    return len(sample) >= 512 and b'\x47' in sample[:200]


def test_stream_health(url, timeout=4.5):
    """Verify reachable HLS playlist, rejecting DRM/HTML pages while supporting AES-128 & fMP4."""
    try:
        text, final_url = _fetch_text(url, timeout=timeout)
        if '#EXTM3U' not in text[:128].upper():
            return False

        if '#EXT-X-STREAM-INF' in text:
            variants = [line.strip() for line in text.splitlines()
                        if line.strip() and not line.startswith('#')]
            for variant in variants[:2]:
                try:
                    child_url = urljoin(final_url, variant)
                    child_text, child_final_url = _fetch_text(child_url, timeout=timeout)
                    if _check_media_playlist(child_text, child_final_url, timeout=timeout):
                        return True
                except Exception:
                    continue
            return False

        return _check_media_playlist(text, final_url, timeout=timeout)
    except Exception:
        return False


def fetch_url_text(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[!] Error fetching {url}: {e}")
        return ""


COUNTRY_CLEAN_RE = re.compile(
    r'\s*[\(\[]\s*(?:India|Pakistan|United\s+Kingdom|UK|United\s+States|USA|US|U\.S\.A\.|U\.K\.|UAE|U\.A\.E\.|United\s+Arab\s+Emirates|Bangladesh|Nepal|Sri\s+Lanka|Canada|Australia|Netherlands|Germany|France|Italy|Spain|Russia|China|Japan|Singapore|Malaysia|Saudi\s+Arabia|Afghanistan|Qatar|Kuwait|Oman|Bahrain|Turkey|Indonesia|Philippines|Thailand|Vietnam|New\s+Zealand|South\s+Africa|Ireland|Brazil|Mexico|International|Global|Worldwide|APAC|MENA|Americas|Europe|IN|PK|GB|CA|AU|AE|BD|NP|LK|US)\s*[\)\]]',
    re.I
)
END_COUNTRY_RE = re.compile(
    r'\s*[-|/:]\s*(?:India|Pakistan|United\s+Kingdom|United\s+States|Canada|Australia|Bangladesh|Nepal|Sri\s+Lanka|UAE|Saudi\s+Arabia|Afghanistan|UK|USA|Global)\s*$',
    re.I
)
TAG_CLEAN_RE = re.compile(
    r'\s*[\(\[]\s*(?:\d{3,4}[pi]|not\s*24\/7|geo[-\s]*blocked|backup|mirror)\s*[\)\]]',
    re.I
)


def clean_channel_name(name):
    if not name:
        return ''
    cleaned = TAG_CLEAN_RE.sub('', name)
    cleaned = COUNTRY_CLEAN_RE.sub('', cleaned)
    cleaned = END_COUNTRY_RE.sub('', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def parse_m3u(m3u_text, default_lang="Hindi", is_global_category=False):
    channels = []
    lines = m3u_text.splitlines()
    cur_id, cur_name, cur_logo, cur_group, cur_lang = '', '', '', '', default_lang

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            id_match = re.search(r'tvg-id="([^"]+)"', line, re.I)
            logo_match = re.search(r'tvg-logo="([^"]+)"', line, re.I)
            group_match = re.search(r'group-title="([^"]+)"', line, re.I)
            lang_match = re.search(r'tvg-language="([^"]+)"', line, re.I)

            cur_id = id_match.group(1).strip() if id_match else ''
            cur_logo = logo_match.group(1).strip() if logo_match else ''
            cur_group = group_match.group(1).strip() if group_match else ''
            cur_lang = lang_match.group(1).strip() if lang_match else default_lang

            comma_idx = line.rfind(',')
            raw_n = line[comma_idx + 1:].strip() if comma_idx != -1 else ''
            cur_name = clean_channel_name(raw_n)
        elif line.startswith('http://') or line.startswith('https://'):
            stream_url = line.split('|')[0].strip()
            if cur_name and stream_url:
                if cur_id and '.pk@' in cur_id.lower():
                    cur_id, cur_name, cur_logo, cur_group, cur_lang = '', '', '', '', default_lang
                    continue
                if is_global_category and cur_id and FOREIGN_COUNTRY_ID_RE.search(cur_id):
                    if not any(b in cur_name.lower() for b in TOP_PRIORITY_BRANDS):
                        cur_id, cur_name, cur_logo, cur_group, cur_lang = '', '', '', '', default_lang
                        continue
                if not any(bad in stream_url.lower() for bad in BAD_DOMAINS):
                    channels.append({
                        "raw_id": cur_id,
                        "name": cur_name,
                        "logo": cur_logo,
                        "group": cur_group,
                        "lang": cur_lang,
                        "url": stream_url
                    })
            cur_id, cur_name, cur_logo, cur_group, cur_lang = '', '', '', '', default_lang

    return channels


def fetch_iptv_org_api_items():
    """Fetch official iptv-org Indian channels, feeds, streams, and logos in parallel."""
    api_urls = {
        "channels": IPTV_ORG_API_CHANNELS,
        "streams": IPTV_ORG_API_STREAMS,
        "logos": IPTV_ORG_API_LOGOS,
        "feeds": IPTV_ORG_API_FEEDS,
    }
    raw_texts = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_url_text, url, 15): k for k, url in api_urls.items()}
        for f in as_completed(futs):
            raw_texts[futs[f]] = f.result()

    try:
        ch_list = json.loads(raw_texts.get("channels") or "[]")
        st_list = json.loads(raw_texts.get("streams") or "[]")
        lg_list = json.loads(raw_texts.get("logos") or "[]")
        fd_list = json.loads(raw_texts.get("feeds") or "[]")
    except Exception as e:
        print(f"[!] Warning parsing iptv-org API JSON: {e}")
        return [], {}

    logo_by_cid = {}
    for lg in lg_list:
        if isinstance(lg, dict) and lg.get("channel") and lg.get("url", "").startswith("http"):
            logo_by_cid.setdefault(lg["channel"], lg["url"])

    feed_area_by_key = {}
    for fd in fd_list:
        if isinstance(fd, dict) and fd.get("channel") and fd.get("id"):
            feed_area_by_key[(fd["channel"], fd["id"])] = fd.get("broadcast_area") or []

    indian_ch = {}
    for c in ch_list:
        if not isinstance(c, dict) or c.get("is_nsfw") or not c.get("id"):
            continue
        cid = c["id"]
        if c.get("country") == "IN" or cid.lower().endswith(".in"):
            indian_ch[cid] = c

    items = []
    for st in st_list:
        if not isinstance(st, dict):
            continue
        cid = st.get("channel") or ""
        surl = (st.get("url") or "").strip()
        if cid not in indian_ch or not surl:
            continue
        feed_id = st.get("feed") or ""
        area = feed_area_by_key.get((cid, feed_id), [])
        if any("c/PK" in str(a) for a in area) or "pakistan" in feed_id.lower():
            continue
        meta = indian_ch[cid]
        raw_name = meta.get("name") or st.get("title") or cid.split(".")[0]
        cleaned = clean_channel_name(raw_name)
        if not cleaned:
            continue
        cats = meta.get("categories") or []
        raw_group = cats[0] if cats else ""
        items.append({
            "raw_id": f"{cid}@{feed_id}" if feed_id else cid,
            "name": cleaned,
            "logo": logo_by_cid.get(cid, ""),
            "group": raw_group,
            "lang": "Hindi",
            "url": surl,
        })

    print(f"[*] Extracted {len(items)} Indian items from official iptv-org API.")
    return items, logo_by_cid


def build_bharat_tv_channels(verify_streams=True, max_workers=40):
    all_raw_items = []

    # Fetch M3U playlists and iptv-org JSON API in parallel for maximum channel yield & speed
    fetch_jobs = [(u, lang, False) for (u, lang) in INDIAN_PLAYLIST_SOURCES] + [
        (u, lang, True) for (u, lang) in GLOBAL_CATEGORY_SOURCES
    ]

    api_items, logo_by_cid = [], {}
    m3u_results = []

    with ThreadPoolExecutor(max_workers=12) as ex:
        api_future = ex.submit(fetch_iptv_org_api_items)
        m3u_futures = {
            ex.submit(fetch_url_text, url, 12): (url, lang, is_global)
            for (url, lang, is_global) in fetch_jobs
        }
        api_items, logo_by_cid = api_future.result()
        all_raw_items.extend(api_items)
        for fut in as_completed(m3u_futures):
            url, lang, is_global = m3u_futures[fut]
            txt = fut.result()
            if txt:
                parsed = parse_m3u(txt, default_lang=lang, is_global_category=is_global)
                print(f"    -> {len(parsed):4d} streams from {url}")
                m3u_results.extend(parsed)

    all_raw_items.extend(m3u_results)
    print(f"\n[*] Total raw candidate records: {len(all_raw_items)}")

    grouped = {}
    for item in all_raw_items:
        if known_channel_mismatch(item['name'], item['url']):
            continue
        key = norm_key(item['name'])
        if not key:
            continue
        base_cid = (item.get('raw_id') or '').split('@')[0]
        best_logo = item['logo'] or (logo_by_cid.get(base_cid, '') if base_cid else '')
        if key not in grouped:
            category = map_category(item['group'], item['name'])
            lang = detect_language(item['name'], item['lang'])
            grouped[key] = {
                "id": item.get('raw_id') or f"ch_{key}",
                "name": item['name'],
                "category": category,
                "language": lang,
                "tier": classify_tier(item['name']),
                "logo_url": best_logo,
                "urls": [item['url']]
            }
        else:
            if item['url'] not in grouped[key]["urls"] and len(grouped[key]["urls"]) < 6:
                grouped[key]["urls"].append(item['url'])
            if best_logo and not grouped[key]["logo_url"]:
                grouped[key]["logo_url"] = best_logo

    print(f"[*] Grouped into {len(grouped)} unique channels.")

    # Inject curated priority seeds
    for seed in CORE_SEEDS:
        sk = norm_key(seed["name"])
        tier = seed.get("tier") or classify_tier(seed["name"])
        if sk in grouped:
            for u in reversed(seed["urls"]):
                if u not in grouped[sk]["urls"]:
                    grouped[sk]["urls"].insert(0, u)
            grouped[sk]["urls"] = grouped[sk]["urls"][:6]
            if seed.get("logo_url"):
                grouped[sk]["logo_url"] = seed["logo_url"]
            grouped[sk]["tier"] = tier
            grouped[sk]["category"] = seed["category"]
            grouped[sk]["language"] = seed["language"]
        else:
            grouped[sk] = {
                "id": f"ch_{sk}",
                "name": seed["name"],
                "category": seed["category"],
                "language": seed["language"],
                "tier": tier,
                "logo_url": seed["logo_url"],
                "urls": list(seed["urls"])
            }

    # Prune generic placeholder URLs claimed by 3+ distinct channels BEFORE probing
    url_to_keys = {}
    for ch in grouped.values():
        ck = canonical_channel_key(ch['name'], ch.get('id', ''))
        for u in ch['urls']:
            url_to_keys.setdefault(u, set()).add(ck)

    overused_pre = {u for u, keys in url_to_keys.items() if len(keys) >= 3}
    if overused_pre:
        print(f"[!] Pruning {len(overused_pre)} generic stream URLs claimed by 3+ channels before ping:")
        for ou in overused_pre:
            print(f"    - {ou} (owners: {sorted(url_to_keys[ou])[:5]})")
        for ch in grouped.values():
            ch['urls'] = [u for u in ch['urls'] if u not in overused_pre and not known_channel_mismatch(ch['name'], u)]

    unique_channels = [ch for ch in grouped.values() if ch['urls']]
    unique_channels.sort(
        key=lambda ch: (
            -get_channel_priority_score(ch),
            ch.get('category') == 'Regional',
            ch['name'].lower()
        )
    )

    verified_channels = []
    if verify_streams:
        unique_urls = list(dict.fromkeys(u for ch in unique_channels for u in ch['urls']))
        print(f"\n[*] Probing {len(unique_urls)} unique candidate URLs across {len(unique_channels)} channels ({max_workers} threads)...")

        alive_set = set()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(test_stream_health, u): u for u in unique_urls}
            done_count = 0
            for future in as_completed(future_to_url):
                u = future_to_url[future]
                done_count += 1
                try:
                    if future.result():
                        alive_set.add(u)
                except Exception:
                    pass
                if done_count % 200 == 0 or done_count == len(unique_urls):
                    print(f"    Verified {done_count}/{len(unique_urls)} URLs (Active: {len(alive_set)})")

        # Enforce 3+ sharing check after probe as well
        alive_url_to_channels = {}
        for ch in unique_channels:
            ck = canonical_channel_key(ch['name'], ch.get('id', ''))
            for u in ch['urls']:
                if u in alive_set and not known_channel_mismatch(ch['name'], u):
                    alive_url_to_channels.setdefault(u, set()).add(ck)

        shared_3plus = {u for u, keys in alive_url_to_channels.items() if len(keys) >= 3}
        if shared_3plus:
            print(f"[!] Pruning {len(shared_3plus)} active stream URLs claimed by 3+ channels.")

        ch_num = 1
        for ch in unique_channels:
            active_urls = [
                u for u in ch['urls']
                if u in alive_set and u not in shared_3plus and not known_channel_mismatch(ch['name'], u)
            ]
            if active_urls:
                primary = active_urls[0]
                fallbacks = []
                seen_fb = {primary}
                for u in active_urls[1:]:
                    if u not in seen_fb:
                        fallbacks.append(u)
                        seen_fb.add(u)
                    if len(fallbacks) >= 4:
                        break

                tier = ch.get("tier")
                if tier not in ("FTA", "PAID"):
                    tier = classify_tier(ch["name"])
                if tier not in ("FTA", "PAID"):
                    tier = "FTA"

                verified_channels.append({
                    "ch_no": ch_num,
                    "id": ch['id'],
                    "name": ch['name'],
                    "category": ch['category'],
                    "language": ch['language'],
                    "tier": tier,
                    "logo_url": ch['logo_url'],
                    "url": primary,
                    "fallback_urls": fallbacks,
                    "streams": [{"name": f"Server {i+1}", "url": u} for i, u in enumerate([primary] + fallbacks)],
                    "quality": "1080p FHD"
                })
                ch_num += 1
    else:
        ch_num = 1
        for ch in unique_channels:
            valid_urls = [u for u in ch['urls'] if not known_channel_mismatch(ch['name'], u)]
            if valid_urls:
                primary = valid_urls[0]
                fallbacks = [u for u in dict.fromkeys(valid_urls[1:]) if u != primary][:4]
                tier = ch.get("tier") if ch.get("tier") in ("FTA", "PAID") else classify_tier(ch["name"])
                verified_channels.append({
                    "ch_no": ch_num,
                    "id": ch['id'],
                    "name": ch['name'],
                    "category": ch['category'],
                    "language": ch['language'],
                    "tier": tier,
                    "logo_url": ch['logo_url'],
                    "url": primary,
                    "fallback_urls": fallbacks,
                    "streams": [{"name": f"Server {i+1}", "url": u} for i, u in enumerate([primary] + fallbacks)],
                    "quality": "1080p FHD"
                })
                ch_num += 1

    if verify_streams and len(verified_channels) < 100:
        raise RuntimeError(
            f"Only {len(verified_channels)} channels passed verification (<100 safety threshold); preserving existing catalogue."
        )

    output_data = {
        "app": "Bharat TV",
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_channels": len(verified_channels),
        "fta_channels": sum(1 for c in verified_channels if c.get("tier") == "FTA"),
        "paid_channels": sum(1 for c in verified_channels if c.get("tier") == "PAID"),
        "channels": verified_channels
    }

    out_json = "channels.json"
    tmp_json = out_json + ".tmp"
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_json, out_json)
    print(f"\n[+] Generated {out_json} successfully with {len(verified_channels)} verified channels (FTA: {output_data['fta_channels']}, PAID: {output_data['paid_channels']})!")

    out_m3u = "channels.m3u"
    tmp_m3u = out_m3u + ".tmp"
    with open(tmp_m3u, "w", encoding="utf-8") as f:
        f.write('#EXTM3U url-tvg="https://iptv-org.github.io/epg/guides/in.xml"\n')
        for ch in verified_channels:
            f.write(
                f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-chno="{ch["ch_no"]}" tvg-language="{ch["language"]}" '
                f'tvg-tier="{ch["tier"]}" tvg-logo="{ch["logo_url"]}" group-title="{ch["category"]}",{ch["name"]}\n'
            )
            f.write(f'{ch["url"]}\n')
    os.replace(tmp_m3u, out_m3u)
    print(f"[+] Generated {out_m3u} successfully!")

    return output_data


if __name__ == "__main__":
    start_time = time.time()
    build_bharat_tv_channels(verify_streams=True, max_workers=40)
    print(f"[*] Completed in {time.time() - start_time:.2f} seconds.")
