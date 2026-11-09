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

# Bypass SSL errors for stream testing
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': '*/*'
}

# Public Curated IPTV Endpoints
PLAYLIST_SOURCES = [
    "https://iptv-org.github.io/iptv/countries/in.m3u",
    "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "https://raw.githubusercontent.com/amazeyourself/m3u/main/tangotv.m3u",
    "https://raw.githubusercontent.com/deep2772/Hindi_Punjabi-iptv-playlist/refs/heads/main/Hindi_Punjabi_Merged.m3u"
]

BAD_DOMAINS = [
    'd1g8wgjurz8via.cloudfront.net',
    '103.151.60.162',
    '103.178.78.151',
    'dinesh29.com.np'
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

def test_stream_health(url, timeout=3.5):
    """Checks if stream URL responds with 200/302 and is active."""
    try:
        req = urllib.request.Request(url, headers=HEADERS, method='HEAD')
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
            code = response.getcode()
            if code in [200, 301, 302, 307]:
                return True
    except Exception:
        # Fallback to GET for servers that block HEAD
        try:
            req = urllib.request.Request(url, headers=HEADERS, method='GET')
            req.headers['Range'] = 'bytes=0-1024'
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
                return response.getcode() in [200, 206, 301, 302]
        except Exception:
            return False
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
            cur_name = line[comma_idx + 1:].strip() if comma_idx != -1 else ''
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
                    "tier": "FTA",
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
                "tier": "FTA",
                "logo_url": ch['logo_url'],
                "url": ch['urls'][0],
                "fallback_urls": ch['urls'][1:],
                "streams": [{"name": f"Server {i+1}", "url": u} for i, u in enumerate(ch['urls'])],
                "quality": "1080p FHD"
            })

    output_data = {
        "app": "Bharat TV",
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_channels": len(verified_channels),
        "channels": verified_channels
    }

    # Write output JSON
    out_json = "channels.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Generated {out_json} successfully with {len(verified_channels)} verified channels!")

    # Write output M3U
    out_m3u = "channels.m3u"
    with open(out_m3u, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ch in verified_channels:
            f.write(f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-name="{ch["name"]}" tvg-logo="{ch["logo_url"]}" group-title="{ch["category"]}" tvg-language="{ch["language"]}",{ch["name"]}\n')
            f.write(f'{ch["url"]}\n')
    print(f"[+] Generated {out_m3u} successfully!")

    return output_data

if __name__ == "__main__":
    start_time = time.time()
    build_bharat_tv_channels(verify_streams=True, max_workers=25)
    print(f"[*] Completed in {time.time() - start_time:.2f} seconds.")
