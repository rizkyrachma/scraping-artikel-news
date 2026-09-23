"""
youtube_search.py
Modul integrasi YouTube Data API v3 dan ekstraksi transkrip video untuk monitoring media Ditjen Industri Agro.
Fitur:
1. search_youtube_videos: Pencarian video YouTube per keyword (search.list, 100 unit kuota).
2. get_video_transcript: Ekstraksi transkrip otomatis via youtube-transcript-api (0 unit kuota).
3. get_kemenperin_channel_videos: Direct pull video dari channel resmi Kemenperin (playlistItems.list, 1 unit kuota).
4. Pelacakan kuota API harian.
"""

import os
import html
from datetime import date, timedelta
import requests
from concurrent.futures import ThreadPoolExecutor
from config import load_env_file, get_date_range

# Channel resmi Kemenperin & Ditjen Industri Agro
KEMENPERIN_CHANNEL_ID = "UCO5bOHu52UDNG1q8im7YM8w"      # @kemenperin_ri
KEMENPERIN_UPLOADS_PLAYLIST = "UUO5bOHu52UDNG1q8im7YM8w"

DITJEN_AGRO_CHANNEL_ID = "UCcooXg0H-Jbmpt8PdIICjfg"     # @ditjenia
DITJEN_AGRO_UPLOADS_PLAYLIST = "UUcooXg0H-Jbmpt8PdIICjfg"

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Pelacak penggunaan kuota sesi berjalan
_QUOTA_UNITS_USED = 0


def get_youtube_quota_used() -> int:
    """Mengembalikan total unit kuota YouTube Data API yang telah terpakai pada sesi ini."""
    return _QUOTA_UNITS_USED


def reset_youtube_quota_tracker():
    """Mereset counter pelacak kuota YouTube API."""
    global _QUOTA_UNITS_USED
    _QUOTA_UNITS_USED = 0


def get_video_transcript(video_id: str) -> str | None:
    """
    Mengambil teks transkrip/caption video YouTube menggunakan library youtube-transcript-api.
    Tidak mengonsumsi kuota YouTube Data API resmi (0 unit).
    Jika video tidak memiliki transkrip/caption, mengembalikan None dengan aman tanpa crash.
    """
    if not video_id:
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()

        # 1. Coba prioritaskan bahasa Indonesia ('id'), lalu bahasa Inggris ('en')
        try:
            transcript = api.fetch(video_id, languages=("id", "en"))
            snippets = getattr(transcript, "snippets", [])
            text = " ".join([s.text for s in snippets if s.text]).strip()
            if text:
                return text
        except Exception:
            pass

        # 2. Fallback: Coba ambil transkrip pertama yang tersedia di daftar transkrip
        try:
            t_list = api.list(video_id)
            for item_t in t_list:
                try:
                    tr = item_t.fetch()
                    snippets = getattr(tr, "snippets", [])
                    text = " ".join([s.text for s in snippets if s.text]).strip()
                    if text:
                        return text
                except Exception:
                    continue
        except Exception:
            pass

        return None
    except Exception:
        return None


def search_youtube_videos(
    keyword: str,
    api_key: str | None = None,
    target_date: date | None = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Mencari video YouTube terkait keyword untuk target_date (default: kemarin).
    Menggunakan endpoint search.list (100 unit kuota).
    HANYA dipanggil 1 kali per keyword per hari untuk menjaga kuota harian (maks 10.000 unit).
    Jika YOUTUBE_API_KEY tidak diset di environment / argumen, fungsi dinonaktifkan (skip tanpa error).
    """
    global _QUOTA_UNITS_USED

    if not api_key:
        load_env_file()
        api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()

    if not api_key:
        return []

    if target_date is None:
        target_date, _ = get_date_range()

    pub_after = f"{target_date.isoformat()}T00:00:00Z"
    pub_before = f"{(target_date + timedelta(days=1)).isoformat()}T00:00:00Z"

    url = f"{YOUTUBE_API_BASE}/search"
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "regionCode": "ID",
        "relevanceLanguage": "id",
        "publishedAfter": pub_after,
        "publishedBefore": pub_before,
        "maxResults": max_results,
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        _QUOTA_UNITS_USED += 100  # search.list berbiaya 100 unit kuota

        if resp.status_code != 200:
            err_data = resp.json().get("error", {})
            msg = err_data.get("message", f"HTTP {resp.status_code}")
            print(f"  [YouTube Search] Gagal memanggil API ({msg})")
            return []

        data = resp.json()
        items = data.get("items", [])

        def _process_item(it):
            vid = it.get("id", {}).get("videoId")
            if not vid:
                return None
            sn = it.get("snippet", {})
            title = html.unescape(sn.get("title", "")).strip()
            channel_title = html.unescape(sn.get("channelTitle", "YouTube")).strip()
            published_at = sn.get("publishedAt", "")
            transcript = get_video_transcript(vid)
            return {
                "title": title,
                "link": f"https://www.youtube.com/watch?v={vid}",
                "media_name": channel_title,
                "published": published_at,
                "text": transcript or "",
                "video_id": vid,
                "keyword": keyword,
                "sumber_data": "YouTube",
                "transcript_available": bool(transcript),
            }

        if items:
            with ThreadPoolExecutor(max_workers=min(5, len(items))) as pool:
                results = [r for r in pool.map(_process_item, items) if r is not None]
        else:
            results = []

        return results
    except Exception as e:
        print(f"  [YouTube Search] Peringatan koneksi: {e}")
        return []


def get_kemenperin_channel_videos(
    api_key: str | None = None,
    target_date: date | None = None,
    max_results: int = 20,
    include_ditjen_agro: bool = True,
) -> list[dict]:
    """
    Direct pull video terbaru dari channel YouTube resmi Kemenperin & Ditjen Industri Agro.
    Menggunakan endpoint playlistItems.list (HANYA 1 unit kuota per pemanggilan, sangat hemat).
    Menjamin video resmi Kemenperin tertangkap tanpa bergantung pada search keyword.
    """
    global _QUOTA_UNITS_USED

    if not api_key:
        load_env_file()
        api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()

    if not api_key:
        return []

    if target_date is None:
        target_date, _ = get_date_range()

    target_date_str = target_date.isoformat()

    playlists = [
        ("Kementerian Perindustrian RI", KEMENPERIN_UPLOADS_PLAYLIST),
    ]
    if include_ditjen_agro:
        playlists.append(("DITJEN Industri Agro", DITJEN_AGRO_UPLOADS_PLAYLIST))

    matched_videos = []
    url = f"{YOUTUBE_API_BASE}/playlistItems"

    for channel_label, playlist_id in playlists:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": max_results,
            "key": api_key,
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            _QUOTA_UNITS_USED += 1  # playlistItems.list berbiaya 1 unit kuota

            if resp.status_code != 200:
                continue

            data = resp.json()
            for it in data.get("items", []):
                sn = it.get("snippet", {})
                published_at = sn.get("publishedAt", "")

                # Filter apakah video diupload pada target_date
                if published_at.startswith(target_date_str):
                    vid = sn.get("resourceId", {}).get("videoId")
                    if not vid:
                        continue

                    title = html.unescape(sn.get("title", "")).strip()
                    channel_name = html.unescape(sn.get("channelTitle", channel_label)).strip()

                    transcript = get_video_transcript(vid)

                    matched_videos.append({
                        "title": title,
                        "link": f"https://www.youtube.com/watch?v={vid}",
                        "media_name": channel_name,
                        "published": published_at,
                        "text": transcript or "",
                        "video_id": vid,
                        "keyword": "kemenperin_institusi",
                        "sumber_data": "YouTube",
                        "transcript_available": bool(transcript),
                    })
        except Exception as e:
            print(f"  [YouTube Channel Direct Pull] Peringatan koneksi ({channel_label}): {e}")

    return matched_videos
