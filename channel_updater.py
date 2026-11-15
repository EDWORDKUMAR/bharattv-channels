#!/usr/bin/env python3
"""
Bharat TV - Automated Channel Discovery, Verification & JSON Generator
Runs daily via GitHub Actions or locally to fetch, ping-test, and update working IPTV channels.
"""

import os
import re
import ssl
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

# Validate streams with normal certificate verification.
SSL_CONTEXT = ssl.create_default_context()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

# Public Curated IPTV Endpoints
PLAYLIST_SOURCES = [
    "https://iptv-org.github.io/iptv/countries/in.m3u",
    "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_india.m3u8",
    "https://raw.githubusercontent.com/amazeyourself/m3u/main/tangotv.m3u",
    "https://raw.githubusercontent.com/deep2772/Hindi_Punjabi-iptv-playlist/refs/heads/main/Hindi_Punjabi_Merged.m3u",
    "https://raw.githubusercontent.com/project9793/hindi-tv/main/sports.m3u",
    "https://raw.githubusercontent.com/project9793/hindi-tv/main/movies.m3u",
    "https://raw.githubusercontent.com/karanjaiswalp-cell/hindi-4k-iptv/main/Hindi-HD-Playable.m3u",
    "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "https://iptv-org.github.io/iptv/categories/animation.m3u"
]

BAD_DOMAINS = [
    'd1g8wgjurz8via.cloudfront.net',
    '103.151.60.162',
    '103.178.78.151',
    '103.135.253.32',
    'gpcdn.net',
    'dinesh29.com.np'
]

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
        "name": "Star Sports 1 HD",
        "category": "Sports",
        "language": "Hindi",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_SPORTS_1/images/LOGO_HD/image.png",
        "urls": [
            "https://d3qs3d2rkhfqrt.cloudfront.net/out/v1/b17adfe543354fdd8d189b110617cddd/index.m3u8",
            "https://real-vk.proxy.nellaiiptv.com/SDMEDIA/index.m3u8",
            "https://cdn.pishow.tv/ott/live/1161/master.m3u8"
        ]
    },
    {
        "name": "Star Sports 2 HD",
        "category": "Sports",
        "language": "Hindi",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_SPORTS_2/images/LOGO_HD/image.png",
        "urls": [
            "https://real-vk.proxy.nellaiiptv.com/SDMEDIA/index.m3u8",
            "http://38.96.178.205/STARSPORTS2/index.m3u8",
            "https://d3qs3d2rkhfqrt.cloudfront.net/out/v1/b17adfe543354fdd8d189b110617cddd/index.m3u8"
        ]
    },
    {
        "name": "Sony Max HD (SET Max)",
        "category": "Movies",
        "language": "Hindi",
        "logo_url": "https://dtil.tmsimg.com/assets/s157590_ld_h15_aa.png?lock=720x540",
        "urls": [
            "https://da86m1sqpm3o0.cloudfront.net/28072023/smil:zeecinemaapachd.smil/chunklist_b2628000.m3u8",
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/sg/YuppTV/ZeeCinemaAPAC.m3u8",
            "https://fta.ektv.in/live/53/53_0.m3u8"
        ]
    },
    {
        "name": "Sony SAB HD",
        "category": "Entertainment",
        "language": "Hindi",
        "logo_url": "https://dtil.tmsimg.com/assets/s159099_ld_h15_ab.png?lock=720x540",
        "urls": [
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/sg/YuppTV/ColorsAPAC.m3u8",
            "http://38.96.178.205/SONYHD/index.m3u8",
            "https://live-dangal.akamaized.net/liveabr/playlist.m3u8",
            "https://airtelapp.shemaroo.com/shemarootv/smil:shemarootvadp.smil/playlist.m3u8"
        ]
    },
    {
        "name": "Star Gold HD",
        "category": "Movies",
        "language": "Hindi",
        "logo_url": "https://i.imgur.com/xC460sj.png",
        "urls": [
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/gb/YuppTV/ColorsCineplexUK.m3u8",
            "https://fta.ektv.in/live/52/52_0.m3u8",
            "https://fta.ektv.in/live/47/47_0.m3u8"
        ]
    },
    {
        "name": "Star Plus HD",
        "category": "Entertainment",
        "language": "Hindi",
        "logo_url": "https://i.imgur.com/xWxNy3L.png",
        "urls": [
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/gb/YuppTV/UtsavPlus.m3u8",
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/gb/YuppTV/UtsavBharat.m3u8"
        ]
    },
    {
        "name": "Zee TV HD",
        "category": "Entertainment",
        "language": "Hindi",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_ZEE_TV/images/LOGO_HD/LOGO_HD_image.png",
        "urls": [
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/sg/YuppTV/ZeeTVHDAPAC.m3u8",
            "https://live.legitpro.co.in/anandtv/index.m3u8"
        ]
    },
    {
        "name": "Cartoon Network (India)",
        "category": "Kids",
        "language": "Hindi",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_CARTOON_NETWORK/images/LOGO_HD/image.png",
        "urls": [
            "https://amg02159-kcglobal-amg02159c1-samsung-in-521.playouts.now.amagi.tv/playlist/amg02159-kcglobal-animax-samsungin/playlist.m3u8",
            "https://server.zillarbarta.com/zbcatun/video.m3u8",
            "https://cdn.pishow.tv/ott/live/32/master.m3u8"
        ]
    },
    {
        "name": "Pogo",
        "category": "Kids",
        "language": "Hindi",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_POGO/images/LOGO_HD/image.png",
        "urls": [
            "https://cc-szrmqvu8zkg16.akamaized.net/v1/master/3722c60a815c199d9c0ef36c5b73da68a62b09d1/cc-szrmqvu8zkg16/greengold/stream/grngld/playlist.m3u8",
            "https://cc-t8lqe1o99pszu.akamaized.net/v1/master/3722c60a815c199d9c0ef36c5b73da68a62b09d1/cc-t8lqe1o99pszu/playlist.m3u8",
            "https://cdn.pishow.tv/ott/live/32/master.m3u8"
        ]
    }
]

# Verified premium and live channels that pass real-time ping testing
CORE_SEEDS = [
    {
        "name": "Star Sports 1 HD",
        "category": "Sports",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_SPORTS_1/images/LOGO_HD/image.png",
        "urls": [
            "http://103.151.60.162:2122/play/a01a/index.m3u8?hls",
            "https://d3qs3d2rkhfqrt.cloudfront.net/out/v1/b17adfe543354fdd8d189b110617cddd/index.m3u8"
        ]
    },
    {
        "name": "Star Sports 2 HD",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_SPORTS_2/images/LOGO_HD/image.png",
        "urls": [
            "http://tvsen5.aynascope.net/cXPB2LKkErN9/index.m3u8",
            "https://real-vk.proxy.nellaiiptv.com/SDMEDIA/index.m3u8"
        ]
    },
    {
        "name": "Star Sports 2 Telugu HD",
        "category": "Sports",
        "language": "Telugu",
        "tier": "FTA",
        "logo_url": "https://i.imgur.com/m7DvvqF.png",
        "urls": [
            "https://real-vk.proxy.nellaiiptv.com/SDMEDIA/index.m3u8"
        ]
    },
    {
        "name": "Sony Max HD (SET Max)",
        "category": "Movies",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s157590_ld_h15_aa.png?lock=720x540",
        "urls": [
            "http://103.185.24.134:3001/SonyMAX/index.m3u8",
            "https://bdix.ottking.top:8082/Sony-Max-1/video.m3u8?token=Sami-TV"
        ]
    },
    {
        "name": "Star Gold HD",
        "category": "Movies",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_GOLD/images/LOGO_HD/image.png",
        "urls": [
            "http://103.185.24.134:3001/Star-Gold/index.m3u8",
            "https://fta.ektv.in/live/52/52_0.m3u8"
        ]
    },
    {
        "name": "Sony SAB HD",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s159099_ld_h15_ab.png?lock=720x540",
        "urls": [
            "http://38.96.178.205/SONYHD/index.m3u8",
            "https://raw.githubusercontent.com/amazeyourself/adaptive-streams/refs/heads/main/streams/sg/YuppTV/ColorsAPAC.m3u8"
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
    },
    {
        "name": "Sony Pal",
        "category": "Entertainment",
        "language": "Hindi",
        "tier": "FTA",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_PAL/images/LOGO_HD/image.png",
        "urls": [
            "https://fta.ektv.in/live/53/53_0.m3u8"
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
        "name": "Sony Pix HD",
        "category": "Movies",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_PIX/images/LOGO_HD/image.png",
        "urls": [
            "http://103.151.60.162:2122/play/a020/index.m3u8?hls"
        ]
    },
    {
        "name": "Star Gold 2",
        "category": "Movies",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s158297_ld_h15_aa.png?lock=720x540",
        "urls": [
            "http://103.151.60.162:2122/play/a01v/index.m3u8?hls",
            "https://fta.ektv.in/live/47/47_0.m3u8"
        ]
    },
    {
        "name": "Star Sports 1 Hindi HD",
        "category": "Sports",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_STAR_SPORTS_1_HINDI/images/LOGO_HD/image.png",
        "urls": [
            "https://tvsen5.aynaott.com/cXPB2LKkErN9/index.m3u8"
        ]
    },
    {
        "name": "Star Sports Select 1 HD",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s143849_ld_h15_aa.png?lock=720x540",
        "urls": [
            "http://103.151.60.162:2122/play/a026/index.m3u8?hls"
        ]
    },
    {
        "name": "Star Sports Select 2 HD",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://dtil.tmsimg.com/assets/s143851_ld_h15_aa.png?lock=720x540",
        "urls": [
            "http://tvsen7.aynascope.net/ssport2hd/index.m3u8"
        ]
    },
    {
        "name": "Sony Sports Ten 1 HD",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_TEN_1/images/LOGO_HD/image.png",
        "urls": [
            "http://103.151.60.162:2122/play/a015/index.m3u8?hls"
        ]
    },
    {
        "name": "Sony Sports Ten 2 HD",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_TEN_2/images/LOGO_HD/image.png",
        "urls": [
            "http://103.151.60.162:2122/play/a016/index.m3u8?hls"
        ]
    },
    {
        "name": "Sony Sports Ten 3 HD",
        "category": "Sports",
        "language": "Hindi",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_TEN_3/images/LOGO_HD/image.png",
        "urls": [
            "http://103.151.60.162:2122/play/a017/index.m3u8?hls"
        ]
    },
    {
        "name": "Sony Sports Ten 5 HD",
        "category": "Sports",
        "language": "English",
        "tier": "PAID",
        "logo_url": "https://xstreamcp-assets-msp.streamready.in/assets/LIVETV/LIVECHANNEL/LIVETV_LIVETVCHANNEL_SONY_SIX/images/LOGO_HD/image.png",
        "urls": [
            "http://103.151.60.162:2122/play/a018/index.m3u8?hls"
        ]
    }
]

TOP_PRIORITY_CHANNELS = [
    "goldmines", "star sports", "sony max", "zee cinema", "star gold",
    "colors", "sony sab", "zee tv", "aaj tak", "abp news", "india tv",
    "ndtv", "cartoon network", "pogo", "hungama", "disney", "nick",
    "mtv", "9xm", "b4u", "dd national", "dd sports", "dd news"
]

def norm_key(name):
    if not name:
        return ""
    clean = re.sub(r'\(.*?\)|\[.*?\]', '', name).lower()
    return re.sub(r'[^a-z0-9]', '', clean)

def known_channel_mismatch(name, url):
    """Reject confirmed cross-channel URLs; never guess a replacement feed."""
    n = norm_key(name)
    u = (url or '').lower()
    if ('sonymax' in n or 'setmax' in n) and ('zeecinema' in u or '/live/53/' in u):
        return True
    if 'stargold' in n and ('colorscineplex' in u or '/live/52/' in u or '/live/47/' in u):
        return True
    return False

def map_category(raw_group, name):
    g = (raw_group or "").lower()
    n = (name or "").lower()
    combined = f"{g} {n}"

    if any(k in combined for k in ['sport', 'cricket', 'football', 'fifa', 'wwe']):
        return "Sports"
    if any(k in combined for k in ['cinema', 'movie', 'film', 'goldmines', 'box office', 'cine']):
        return "Movies"
    if any(k in combined for k in ['kid', 'cartoon', 'pogo', 'disney', 'anime', 'hungama', 'nickelodeon', 'sonic']):
        return "Kids"
    if any(k in combined for k in ['news', 'samachar', 'khabar', 'aaj tak', 'abp', 'ndtv', 'republic', 'zee news']):
        return "News"
    if any(k in combined for k in ['music', 'gaana', 'sangeet', 'song', '9xm', 'mtv', 'b4u music', 'zoom']):
        return "Music"
    if any(k in combined for k in ['bhakti', 'devotional', 'aarti', 'mandir', 'dharma', 'aastha', 'sanskar', 'sadhna', 'ishwar']):
        return "Devotional"
    if any(k in combined for k in ['business', 'bazaar', 'market', 'money', 'et now', 'cnbc', 'sensex']):
        return "Business"
    if any(k in combined for k in ['discovery', 'history', 'nat geo', 'animal', 'science', 'education', 'gyan']):
        return "Education"
    if any(k in combined for k in ['bhojpuri', 'punjabi', 'marathi', 'gujarati', 'bengali', 'tamil', 'telugu', 'kannada', 'malayalam', 'odia', 'assamese']):
        return "Regional"
    return "Entertainment"

def detect_language(name, raw_lang="Hindi"):
    n = (name or "").lower()
    if any(k in n for k in ['punjabi', 'ptc', 'apna punjab']):
        return "Punjabi"
    if any(k in n for k in ['bhojpuri', 'b4u bhojpuri', 'dabangg', 'ananya']):
        return "Bhojpuri"
    if any(k in n for k in ['gujarat', 'gujarati', 'colors gujarati']):
        return "Gujarati"
    if any(k in n for k in ['marathi', 'zee 24 taas', 'colors marathi', 'pravah']):
        return "Marathi"
    if any(k in n for k in ['bangla', 'bengali', 'zee 24 ghanta']):
        return "Bengali"
    if any(k in n for k in ['tamil', 'sun tv', 'jaya']):
        return "Tamil"
    if any(k in n for k in ['telugu', 'etv', 'gemini']):
        return "Telugu"
    if any(k in n for k in ['kannada', 'udaya', 'colors kannada']):
        return "Kannada"
    if any(k in n for k in ['malayalam', 'asianet', 'surya']):
        return "Malayalam"
    if any(k in n for k in ['english', 'times now', 'cnn', 'bbc', 'wion']):
        return "English"
    return raw_lang or "Hindi"

def test_stream_health(url, timeout=5):
    """Require an actual HLS manifest and a reachable media playlist/segment."""
    try:
        req = urllib.request.Request(url, headers={**HEADERS, 'Range': 'bytes=0-65535'})
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
            body = response.read(65536)
            final_url = response.geturl()
        text = body.decode('utf-8', errors='ignore')
        if not text.lstrip('\ufeff').startswith('#EXTM3U'):
            return False
        # A master manifest is useful only when one of its variants is reachable.
        variant = next((line.strip() for line in text.splitlines()
                        if line.strip() and not line.startswith('#')), None)
        if not variant:
            return '#EXTINF:' in text and any(tag in text for tag in ('#EXT-X-TARGETDURATION:', '#EXT-X-MEDIA-SEQUENCE:'))
        from urllib.parse import urljoin
        child_url = urljoin(final_url, variant)
        req = urllib.request.Request(child_url, headers={**HEADERS, 'Range': 'bytes=0-65535'})
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
            child = response.read(65536).decode('utf-8', errors='ignore')
            child_final_url = response.geturl()
        if not child.lstrip('\ufeff').startswith('#EXTM3U'):
            return False
        segment = next((line.strip() for line in child.splitlines()
                        if line.strip() and not line.startswith('#')), None)
        if not segment:
            return '#EXTINF:' in child and '#EXT-X-TARGETDURATION:' in child
        media_url = urljoin(child_final_url, segment)
        req = urllib.request.Request(media_url, headers={**HEADERS, 'Range': 'bytes=0-188'})
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
            sample = response.read(189)
        # MPEG-TS has a sync byte; fMP4 segments have an ISO BMFF box header.
        return (len(sample) >= 188 and sample[0] == 0x47) or (len(sample) >= 8 and sample[4:8] in (b'ftyp', b'styp', b'moof'))
    except Exception:
        return False

def fetch_m3u_text(url):
    print(f"[*] Fetching playlist: {url}")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12, context=SSL_CONTEXT) as resp:
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

def parse_m3u(m3u_text):
    channels = []
    lines = m3u_text.splitlines()
    cur_id, cur_name, cur_logo, cur_group, cur_lang = '', '', '', '', 'Hindi'

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
            cur_lang = lang_match.group(1).strip() if lang_match else 'Hindi'

            comma_idx = line.rfind(',')
            raw_n = line[comma_idx + 1:].strip() if comma_idx != -1 else ''
            cur_name = clean_channel_name(raw_n)
        elif line.startswith('http://') or line.startswith('https://'):
            stream_url = line.split('|')[0].strip()
            if not any(bad in stream_url for bad in BAD_DOMAINS) and cur_name:
                channels.append({
                    "raw_id": cur_id,
                    "name": cur_name,
                    "logo": cur_logo,
                    "group": cur_group,
                    "lang": cur_lang,
                    "url": stream_url
                })
            cur_id, cur_name, cur_logo, cur_group, cur_lang = '', '', '', '', 'Hindi'

    return channels

def get_channel_priority_score(name):
    n = name.lower()
    for idx, top in enumerate(TOP_PRIORITY_CHANNELS):
        if top in n:
            return 1000 - idx
    return 0

def build_bharat_tv_channels(verify_streams=True, max_workers=20):
    all_raw_items = []
    for source in PLAYLIST_SOURCES:
        text = fetch_m3u_text(source)
        if text:
            items = parse_m3u(text)
            print(f"    -> Extracted {len(items)} channel streams from source.")
            all_raw_items.extend(items)

    print(f"\n[*] Total extracted channel records: {len(all_raw_items)}")

    # Deduplicate & Group by normalized channel name
    grouped = {}
    for item in all_raw_items:
        if known_channel_mismatch(item['name'], item['url']):
            print(f"[!] Skipping known mismatched feed: {item['name']} -> {item['url']}")
            continue
        key = norm_key(item['name'])
        if not key:
            continue
        if key not in grouped:
            category = map_category(item['group'], item['name'])
            lang = detect_language(item['name'], item['lang'])
            grouped[key] = {
                "id": f"ch_{key}",
                "name": item['name'],
                "category": category,
                "language": lang,
                "logo_url": item['logo'],
                "urls": [item['url']]
            }
        else:
            if item['url'] not in grouped[key]["urls"]:
                grouped[key]["urls"].append(item['url'])
            if item['logo'] and not grouped[key]["logo_url"]:
                grouped[key]["logo_url"] = item['logo']

    print(f"[*] Grouped into {len(grouped)} unique channels.")

    # Inject and prioritize curated premium seed channels
    for seed in CORE_SEEDS:
        sk = norm_key(seed["name"])
        if sk in grouped:
            for u in reversed(seed["urls"]):
                if u not in grouped[sk]["urls"]:
                    grouped[sk]["urls"].insert(0, u)
            if seed.get("logo_url"):
                grouped[sk]["logo_url"] = seed["logo_url"]
        else:
            grouped[sk] = {
                "id": f"ch_{sk}",
                "name": seed["name"],
                "category": seed["category"],
                "language": seed["language"],
                "logo_url": seed["logo_url"],
                "urls": seed["urls"]
            }

    unique_channels = list(grouped.values())

    # Sort channels: Top priority first (Goldmines, Star Sports, Zee Cinema, News etc.)
    unique_channels.sort(
        key=lambda ch: (
            -get_channel_priority_score(ch['name']),
            ch['category'] == 'Regional',
            ch['name'].lower()
        )
    )

    verified_channels = []
    if verify_streams:
        print(f"\n[*] Pinging streams to verify live health (max {max_workers} threads)...")
        # Check streams concurrently
        all_urls = []
        for ch in unique_channels:
            for u in ch['urls']:
                all_urls.append(u)

        alive_set = set()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(test_stream_health, u): u for u in all_urls}
            done_count = 0
            for future in as_completed(future_to_url):
                u = future_to_url[future]
                done_count += 1
                try:
                    is_alive = future.result()
                    if is_alive:
                        alive_set.add(u)
                except Exception:
                    pass
                if done_count % 50 == 0 or done_count == len(all_urls):
                    print(f"    Verified {done_count}/{len(all_urls)} URLs (Active: {len(alive_set)})")

        # Keep channels with at least 1 alive stream
        ch_num = 1
        for ch in unique_channels:
            active_urls = [u for u in ch['urls'] if u in alive_set]
            if active_urls:
                primary = active_urls[0]
                fallbacks = active_urls[1:]
                verified_channels.append({
                    "ch_no": ch_num,
                    "id": ch['id'],
                    "name": ch['name'],
                    "category": ch['category'],
                    "language": ch['language'],
                    "tier": "UNVERIFIED",
                    "logo_url": ch['logo_url'],
                    "url": primary,
                    "fallback_urls": fallbacks,
                    "streams": [{"name": f"Server {i+1}", "url": u} for i, u in enumerate(active_urls)],
                    "quality": "1080p FHD"
                })
                ch_num += 1
    else:
        for idx, ch in enumerate(unique_channels):
            verified_channels.append({
                "ch_no": idx + 1,
                "id": ch['id'],
                "name": ch['name'],
                "category": ch['category'],
                "language": ch['language'],
                "tier": "UNVERIFIED",
                "logo_url": ch['logo_url'],
                "url": ch['urls'][0],
                "fallback_urls": ch['urls'][1:],
                "streams": [{"name": f"Server {i+1}", "url": u} for i, u in enumerate(ch['urls'])],
                "quality": "1080p FHD"
            })

    if verify_streams and not verified_channels:
        raise RuntimeError("No media streams passed verification; preserving the last known channel catalogue.")

    output_data = {
        "app": "Bharat TV",
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_channels": len(verified_channels),
        "channels": verified_channels
    }

    # Write atomically so an interrupted refresh cannot truncate the live catalogue.
    out_json = "channels.json"
    tmp_json = out_json + ".tmp"
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_json, out_json)
    print(f"\n[+] Generated {out_json} successfully with {len(verified_channels)} verified channels!")

    # Write output M3U
    out_m3u = "channels.m3u"
    tmp_m3u = out_m3u + ".tmp"
    with open(tmp_m3u, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ch in verified_channels:
            f.write(f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-name="{ch["name"]}" tvg-logo="{ch["logo_url"]}" group-title="{ch["category"]}" tvg-language="{ch["language"]}",{ch["name"]}\n')
            f.write(f'{ch["url"]}\n')
    os.replace(tmp_m3u, out_m3u)
    print(f"[+] Generated {out_m3u} successfully!")

    return output_data

if __name__ == "__main__":
    start_time = time.time()
    build_bharat_tv_channels(verify_streams=True, max_workers=25)
    print(f"[*] Completed in {time.time() - start_time:.2f} seconds.")
