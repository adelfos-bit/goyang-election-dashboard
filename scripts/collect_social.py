#!/usr/bin/env python3
"""소셜미디어 데이터 수집 스크립트 - API 기반 (fallback: 스크래핑)"""

import os
import sys
import json
import argparse
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")

# .env 파일에서 환경변수 자동 로드
_env_path = os.path.join(PROJECT_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# 소셜미디어 계정 정보
ACCOUNTS = {
    "youtube": {
        "handle": "@이경혜-x4l",
        "url": "https://www.youtube.com/@%EC%9D%B4%EA%B2%BD%ED%98%9C-x4l",
    },
    "facebook": {
        "id": "eva09815",
        "url": "https://www.facebook.com/eva09815",
    },
    "instagram": {
        "id": "gyeonghye86",
        "url": "https://www.instagram.com/gyeonghye86",
    },
    "blog": {
        "id": "lee1065",
        "url": "https://blog.naver.com/lee1065",
        "rss": "https://rss.blog.naver.com/lee1065",
    },
    "tiktok": {
        "id": "eva800518",
        "url": "https://www.tiktok.com/@eva800518",
    },
    "twitter": {
        "id": "igyeonghye76014",
        "url": "https://x.com/igyeonghye76014",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


# ──────────────────────────────────────────────
# YouTube Data API v3
# ──────────────────────────────────────────────
def fetch_youtube_api():
    """YouTube Data API v3으로 채널 데이터 수집"""
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("[YouTube] API 키 없음 ->스크래핑 fallback")
        return None

    result = {"status": "개설완료", "subscribers": 0, "videos": 0,
              "last_upload": None, "recent_videos": [], "score": 0}

    try:
        # 1) 핸들로 채널 정보 조회
        handle = ACCOUNTS["youtube"]["handle"]
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "statistics,snippet,contentDetails",
            "forHandle": handle.lstrip("@"),
            "key": api_key,
        }
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if "error" in data:
            print(f"[YouTube API] 오류: {data['error']['message']}")
            return None

        if not data.get("items"):
            # forHandle이 안 되면 forUsername 시도
            params.pop("forHandle")
            params["forUsername"] = handle.lstrip("@")
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()

        if not data.get("items"):
            print(f"[YouTube API] 채널을 찾을 수 없음: {handle}")
            return None

        channel = data["items"][0]
        stats = channel.get("statistics", {})
        result["subscribers"] = int(stats.get("subscriberCount", 0))
        result["videos"] = int(stats.get("videoCount", 0))
        result["total_views"] = int(stats.get("viewCount", 0))
        channel_id = channel["id"]

        # 2) 최근 영상 조회
        search_url = "https://www.googleapis.com/youtube/v3/search"
        search_params = {
            "part": "snippet",
            "channelId": channel_id,
            "order": "date",
            "maxResults": 5,
            "type": "video",
            "key": api_key,
        }
        search_resp = requests.get(search_url, params=search_params, timeout=15)
        search_data = search_resp.json()

        video_ids = []
        for item in search_data.get("items", []):
            vid_id = item["id"].get("videoId", "")
            snippet = item.get("snippet", {})
            video_ids.append(vid_id)
            result["recent_videos"].append({
                "title": snippet.get("title", ""),
                "date": snippet.get("publishedAt", "")[:10],
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "views": 0,  # 아래에서 채움
            })

        # 3) 영상별 조회수 조회
        if video_ids:
            vid_url = "https://www.googleapis.com/youtube/v3/videos"
            vid_params = {
                "part": "statistics",
                "id": ",".join(video_ids),
                "key": api_key,
            }
            vid_resp = requests.get(vid_url, params=vid_params, timeout=15)
            vid_data = vid_resp.json()
            for i, vid_item in enumerate(vid_data.get("items", [])):
                if i < len(result["recent_videos"]):
                    views = int(vid_item.get("statistics", {}).get("viewCount", 0))
                    result["recent_videos"][i]["views"] = views

        if result["recent_videos"]:
            result["last_upload"] = result["recent_videos"][0]["date"]

        # 상태 판단
        if result["videos"] > 0:
            result["status"] = "활성"
        else:
            result["status"] = "개설완료"

        # 점수 계산
        score = 0
        score += min(result["subscribers"] / 10, 30)   # 구독자
        score += min(result["videos"] * 5, 30)          # 영상 수
        if result["last_upload"]:
            try:
                last_dt = datetime.strptime(result["last_upload"], "%Y-%m-%d")
                days = (datetime.now() - last_dt).days
                if days <= 3:
                    score += 40
                elif days <= 7:
                    score += 30
                elif days <= 30:
                    score += 15
            except ValueError:
                pass
        result["score"] = min(int(score), 100)

        print(f"[YouTube API] 성공 -구독자 {result['subscribers']}, 영상 {result['videos']}개")
        return result

    except Exception as e:
        print(f"[YouTube API] 실패: {e}")
        return None


def fetch_youtube_scrape():
    """유튜브 채널 데이터 수집 (스크래핑 fallback)"""
    result = {"status": "개설완료", "subscribers": 0, "videos": 0,
              "last_upload": None, "recent_videos": [], "score": 0}
    try:
        url = ACCOUNTS["youtube"]["url"]
        resp = requests.get(url, headers=HEADERS, timeout=15)
        html = resp.text

        sub_match = re.search(r'"subscriberCountText":\{"simpleText":"([^"]+)"', html)
        if sub_match:
            result["subscribers"] = _parse_korean_number(sub_match.group(1))

        cid_match = re.search(r'"channelId":"(UC[^"]+)"', html)
        if cid_match:
            channel_id = cid_match.group(1)
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            rss_resp = requests.get(rss_url, headers=HEADERS, timeout=10)
            if rss_resp.status_code == 200:
                root = ET.fromstring(rss_resp.content)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entries = root.findall("atom:entry", ns)
                result["videos"] = len(entries)
                for entry in entries[:5]:
                    title = entry.find("atom:title", ns)
                    published = entry.find("atom:published", ns)
                    link = entry.find("atom:link", ns)
                    result["recent_videos"].append({
                        "title": title.text if title is not None else "",
                        "date": published.text[:10] if published is not None else "",
                        "url": link.get("href", "") if link is not None else "",
                    })
                if entries:
                    pub = entries[0].find("atom:published", ns)
                    if pub is not None:
                        result["last_upload"] = pub.text[:10]

        if result["videos"] > 0:
            result["status"] = "활성"
            score = min(result["videos"] * 10, 70)
            if result["last_upload"]:
                try:
                    last_dt = datetime.strptime(result["last_upload"], "%Y-%m-%d")
                    if (datetime.now() - last_dt).days <= 7:
                        score += 30
                except ValueError:
                    pass
            result["score"] = min(score, 100)
        else:
            result["score"] = 5

    except Exception as e:
        print(f"[YouTube 스크래핑] 실패: {e}")

    return result


def fetch_youtube_data():
    """YouTube 수집 (API 우선, fallback 스크래핑)"""
    result = fetch_youtube_api()
    if result is not None:
        result["source"] = "api"
        return result
    result = fetch_youtube_scrape()
    result["source"] = "scrape"
    return result


# ──────────────────────────────────────────────
# Facebook Graph API
# ──────────────────────────────────────────────
def fetch_facebook_api():
    """Facebook Graph API로 페이지 데이터 수집"""
    # eva09815(이경혜)는 개인 프로필이라 API 불가 → 스크래핑 fallback
    print("[Facebook] 개인 프로필(eva09815) → API 미사용, 스크래핑 fallback")
    return None
    token = os.environ.get("FACEBOOK_PAGE_TOKEN")
    if not token:
        print("[Facebook] 페이지 토큰 없음 ->스크래핑 fallback")
        return None

    page_id = os.environ.get("FACEBOOK_PAGE_ID", ACCOUNTS["facebook"]["id"])
    result = {"status": "활성", "followers": 0, "likes": 0,
              "recent_posts": [], "score": 0}

    try:
        # 1) 페이지 기본 정보
        base_url = f"https://graph.facebook.com/v19.0/{page_id}"
        params = {
            "fields": "followers_count,fan_count,name",
            "access_token": token,
        }
        resp = requests.get(base_url, params=params, timeout=15)
        data = resp.json()

        if "error" in data:
            print(f"[Facebook API] 오류: {data['error'].get('message', '')}")
            return None

        result["followers"] = data.get("followers_count", 0)
        result["likes"] = data.get("fan_count", 0)

        # 2) 최근 게시물 (최대 10개)
        posts_url = f"https://graph.facebook.com/v19.0/{page_id}/posts"
        posts_params = {
            "fields": "message,created_time,likes.summary(true),comments.summary(true),shares",
            "limit": 10,
            "access_token": token,
        }
        posts_resp = requests.get(posts_url, params=posts_params, timeout=15)
        posts_data = posts_resp.json()

        for post in posts_data.get("data", []):
            likes_count = post.get("likes", {}).get("summary", {}).get("total_count", 0)
            comments_count = post.get("comments", {}).get("summary", {}).get("total_count", 0)
            shares_count = post.get("shares", {}).get("count", 0) if post.get("shares") else 0
            result["recent_posts"].append({
                "message": (post.get("message", "") or "")[:100],
                "date": post.get("created_time", "")[:10],
                "likes": likes_count,
                "comments": comments_count,
                "shares": shares_count,
            })

        # 점수 계산
        score = 0
        score += min(result["followers"] / 200, 40)  # 팔로워
        if result["recent_posts"]:
            latest_date = result["recent_posts"][0].get("date", "")
            if latest_date:
                try:
                    days = (datetime.now() - datetime.strptime(latest_date, "%Y-%m-%d")).days
                    if days <= 3:
                        score += 30
                    elif days <= 7:
                        score += 20
                    elif days <= 30:
                        score += 10
                except ValueError:
                    pass
            avg_engagement = sum(
                p.get("likes", 0) + p.get("comments", 0) + p.get("shares", 0)
                for p in result["recent_posts"][:5]
            ) / min(len(result["recent_posts"]), 5)
            score += min(avg_engagement / 5, 30)
        result["score"] = min(int(score), 100)

        print(f"[Facebook API] 성공 -팔로워 {result['followers']}, 게시물 {len(result['recent_posts'])}개")
        return result

    except Exception as e:
        print(f"[Facebook API] 실패: {e}")
        return None


def fetch_facebook_scrape():
    """페이스북 공개 프로필 데이터 수집 (다중 방식 시도)"""
    result = {"status": "활성", "followers": 0, "likes": 0, "talking_about": 0,
              "recent_posts": [], "score": 0}
    fb_id = ACCOUNTS["facebook"]["id"]
    methods_tried = []

    # 브라우저 유사 헤더 (sec-ch-ua 포함)
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "sec-ch-ua": '"Chromium";v="122"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    # 방식 1: 세션 + 브라우저 헤더로 메타 태그 파싱
    try:
        session = requests.Session()
        session.get("https://www.facebook.com/", headers=browser_headers, timeout=10)
        resp = session.get(f"https://www.facebook.com/{fb_id}",
                          headers=browser_headers, timeout=15, allow_redirects=True)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # og:description 또는 description 메타 태그에서 추출
            for meta_attr in [{"property": "og:description"}, {"name": "description"},
                              {"name": "twitter:description"}]:
                meta = soup.find("meta", attrs=meta_attr)
                if meta:
                    desc = meta.get("content", "")

                    # "좋아하는 사람 6,106명" 패턴 (페이스북 페이지/프로필)
                    like_match = re.search(
                        r'좋아하는 사람\s+([\d,\.]+(?:천|만)?)\s*명', desc)
                    if like_match:
                        result["likes"] = _parse_korean_number(like_match.group(1))
                        result["followers"] = result["likes"]  # 좋아요 ≈ 팔로워

                    # "이야기하고 있는 사람들 595명" 패턴
                    talk_match = re.search(
                        r'이야기하고 있는 사람들\s+([\d,\.]+(?:천|만)?)\s*명', desc)
                    if talk_match:
                        result["talking_about"] = _parse_korean_number(talk_match.group(1))

                    # "팔로워 N명" 패턴 (공식 페이지)
                    if result["followers"] == 0:
                        f_match = re.search(
                            r'팔로워\s+([\d,\.]+(?:천|만)?)\s*명', desc)
                        if f_match:
                            result["followers"] = _parse_korean_number(f_match.group(1))

                    # 영어: "N likes · N talking about this"
                    if result["followers"] == 0:
                        en_match = re.search(
                            r'([\d,]+)\s*likes', desc)
                        if en_match:
                            result["likes"] = int(en_match.group(1).replace(",", ""))
                            result["followers"] = result["likes"]

                    if result["followers"] > 0:
                        methods_tried.append("브라우저UA+메타태그")
                        break

    except Exception as e:
        methods_tried.append(f"브라우저UA 실패: {e}")

    # 방식 2: HTML 소스에서 JSON 패턴 매칭
    if result["followers"] == 0:
        try:
            html = resp.text if 'resp' in dir() else ""
            json_patterns = [
                r'"follower_count":(\d+)',
                r'"friends_count":(\d+)',
                r'"userInteractionCount":"(\d+)"',
            ]
            for pattern in json_patterns:
                match = re.search(pattern, html)
                if match:
                    result["followers"] = int(match.group(1))
                    methods_tried.append("JSON패턴매칭")
                    break
        except Exception:
            pass

    # 모든 방식 실패 시 이전 수집 데이터 복구
    if result["followers"] == 0:
        prev = _load_previous_value("facebook", "followers")
        if prev:
            result["followers"] = prev
            methods_tried.append(f"이전값 사용: {prev}")
            print(f"[Facebook 스크래핑] 이전 수집값 사용: 팔로워 {prev}")
        else:
            methods_tried.append("완전 실패")

    print(f"[Facebook 스크래핑] 시도: {', '.join(methods_tried)}")

    # 점수 계산 (팔로워 기반 + 활성도)
    score = min(result["followers"] / 200, 50)
    if result["talking_about"] > 0:
        score += min(result["talking_about"] / 20, 30)  # 활성 사용자 보너스
    score += 10 if result["followers"] > 1000 else 0  # 1천명 이상 보너스
    result["score"] = min(int(score), 100)
    return result


def fetch_facebook_data():
    """Facebook 수집 (API 우선, fallback 스크래핑)"""
    result = fetch_facebook_api()
    if result is not None:
        result["source"] = "api"
        return result
    result = fetch_facebook_scrape()
    result["source"] = "scrape"
    return result


# ──────────────────────────────────────────────
# Instagram Graph API (via Meta/Facebook)
# ──────────────────────────────────────────────
def fetch_instagram_api():
    """Instagram Graph API로 비즈니스 계정 데이터 수집"""
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("INSTAGRAM_BUSINESS_ID")

    if not token or not ig_user_id:
        print("[Instagram] API 토큰/ID 없음 ->스크래핑 fallback")
        return None

    result = {"status": "활성", "followers": 0, "posts": 0,
              "recent_posts": [], "score": 0}

    try:
        # 1) 계정 기본 정보
        base_url = f"https://graph.facebook.com/v19.0/{ig_user_id}"
        params = {
            "fields": "followers_count,media_count,username,biography",
            "access_token": token,
        }
        resp = requests.get(base_url, params=params, timeout=15)
        data = resp.json()

        if "error" in data:
            print(f"[Instagram API] 오류: {data['error'].get('message', '')}")
            return None

        result["followers"] = data.get("followers_count", 0)
        result["posts"] = data.get("media_count", 0)

        # 2) 최근 미디어
        media_url = f"https://graph.facebook.com/v19.0/{ig_user_id}/media"
        media_params = {
            "fields": "caption,timestamp,like_count,comments_count,media_type,permalink",
            "limit": 10,
            "access_token": token,
        }
        media_resp = requests.get(media_url, params=media_params, timeout=15)
        media_data = media_resp.json()

        for media in media_data.get("data", []):
            result["recent_posts"].append({
                "caption": (media.get("caption", "") or "")[:100],
                "date": media.get("timestamp", "")[:10],
                "likes": media.get("like_count", 0),
                "comments": media.get("comments_count", 0),
                "type": media.get("media_type", ""),
                "url": media.get("permalink", ""),
            })

        # 점수 계산
        score = 0
        score += min(result["followers"] / 100, 30)  # 팔로워
        score += min(result["posts"] * 0.3, 20)       # 게시물 수
        if result["recent_posts"]:
            latest_date = result["recent_posts"][0].get("date", "")
            if latest_date:
                try:
                    days = (datetime.now() - datetime.strptime(latest_date, "%Y-%m-%d")).days
                    if days <= 3:
                        score += 30
                    elif days <= 7:
                        score += 20
                    elif days <= 30:
                        score += 10
                except ValueError:
                    pass
            avg_engagement = sum(
                p.get("likes", 0) + p.get("comments", 0)
                for p in result["recent_posts"][:5]
            ) / min(len(result["recent_posts"]), 5)
            score += min(avg_engagement / 3, 20)
        result["score"] = min(int(score), 100)

        print(f"[Instagram API] 성공 -팔로워 {result['followers']}, 게시물 {result['posts']}개")
        return result

    except Exception as e:
        print(f"[Instagram API] 실패: {e}")
        return None


def fetch_instagram_scrape():
    """인스타그램 공개 프로필 데이터 수집 (다중 방식 시도)"""
    result = {"status": "활성", "followers": 0, "posts": 0, "following": 0, "score": 0}
    ig_id = ACCOUNTS["instagram"]["id"]

    # 방식 1: Instagram Android 앱 User-Agent (가장 높은 성공률)
    mobile_headers = {
        "User-Agent": "Instagram 317.0.0.0.64 Android (33/13; 420dpi; 1080x2400; "
                      "samsung; SM-G991B; o1s; exynos2100)",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    methods_tried = []

    # 방식 1: 세션 + 모바일 UA로 메타 태그 파싱
    try:
        session = requests.Session()
        # 먼저 메인 페이지 방문하여 쿠키 획득
        session.get("https://www.instagram.com/", headers=mobile_headers, timeout=10)
        # 그 다음 프로필 페이지 요청
        resp = session.get(f"https://www.instagram.com/{ig_id}/",
                          headers=mobile_headers, timeout=15)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # meta description에서 추출
        for meta_attr in [{"name": "description"}, {"property": "og:description"}]:
            meta = soup.find("meta", attrs=meta_attr)
            if meta:
                desc = meta.get("content", "")
                # 한국어: "팔로워 314명, 팔로잉 27명, 게시물 79개"
                f_match = re.search(r'팔로워\s+([\d,\.]+(?:천|만)?)\s*명', desc)
                if f_match:
                    result["followers"] = _parse_korean_number(f_match.group(1))
                fg_match = re.search(r'팔로잉\s+([\d,\.]+)\s*명', desc)
                if fg_match:
                    result["following"] = int(fg_match.group(1).replace(",", ""))
                p_match = re.search(r'게시물\s+([\d,]+)\s*개', desc)
                if p_match:
                    result["posts"] = int(p_match.group(1).replace(",", ""))
                # 영어: "314 Followers, 27 Following, 79 Posts"
                if result["followers"] == 0:
                    ef_match = re.search(r'([\d,\.]+(?:K|k|M|m)?)\s*[Ff]ollowers', desc)
                    if ef_match:
                        result["followers"] = _parse_korean_number(ef_match.group(1))
                    ep_match = re.search(r'([\d,]+)\s*[Pp]osts', desc)
                    if ep_match:
                        result["posts"] = int(ep_match.group(1).replace(",", ""))

                if result["followers"] > 0:
                    methods_tried.append("모바일UA+메타태그")
                    break

    except Exception as e:
        methods_tried.append(f"모바일UA 실패: {e}")

    # 방식 2: 데스크탑 UA로 재시도
    if result["followers"] == 0:
        try:
            resp = requests.get(f"https://www.instagram.com/{ig_id}/",
                              headers=HEADERS, timeout=15)
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            for meta_attr in [{"name": "description"}, {"property": "og:description"}]:
                meta = soup.find("meta", attrs=meta_attr)
                if meta:
                    desc = meta.get("content", "")
                    f_match = re.search(r'팔로워\s+([\d,\.]+(?:천|만)?)\s*명', desc)
                    if f_match:
                        result["followers"] = _parse_korean_number(f_match.group(1))
                    p_match = re.search(r'게시물\s+([\d,]+)\s*개', desc)
                    if p_match:
                        result["posts"] = int(p_match.group(1).replace(",", ""))
                    if result["followers"] > 0:
                        methods_tried.append("데스크탑UA+메타태그")
                        break
        except Exception as e:
            methods_tried.append(f"데스크탑UA 실패: {e}")

    # 방식 3: JSON-LD 구조화 데이터에서 추출 시도
    if result["followers"] == 0:
        try:
            # 페이지 소스에서 JSON 데이터 추출
            json_patterns = [
                r'"edge_followed_by":\{"count":(\d+)\}',
                r'"follower_count":(\d+)',
                r'"userInteractionCount":"(\d+)"',
            ]
            for pattern in json_patterns:
                match = re.search(pattern, html)
                if match:
                    result["followers"] = int(match.group(1))
                    methods_tried.append("JSON패턴매칭")
                    break
        except Exception:
            pass

    # 모든 방식 실패 시 이전 수집 데이터 복구
    if result["followers"] == 0:
        prev_followers = _load_previous_value("instagram", "followers")
        prev_posts = _load_previous_value("instagram", "posts")
        prev_following = _load_previous_value("instagram", "following")
        if prev_followers:
            result["followers"] = prev_followers
            result["posts"] = prev_posts or result["posts"]
            result["following"] = prev_following or 0
            methods_tried.append(f"이전값 사용: {prev_followers}")
            print(f"[Instagram 스크래핑] 이전 수집값 사용: 팔로워 {prev_followers}")
        else:
            methods_tried.append("완전 실패")

    print(f"[Instagram 스크래핑] 시도: {', '.join(methods_tried)}")

    score = min(result["followers"] / 100, 60) + min(result["posts"] * 0.3, 40)
    result["score"] = min(int(score), 100)
    return result


def fetch_instagram_data():
    """Instagram 수집 (API 우선, fallback 스크래핑)"""
    result = fetch_instagram_api()
    if result is not None:
        result["source"] = "api"
        return result
    result = fetch_instagram_scrape()
    result["source"] = "scrape"
    return result


# ──────────────────────────────────────────────
# 네이버 블로그 (RSS -이미 잘 작동)
# ──────────────────────────────────────────────
def fetch_blog_data():
    """네이버 블로그 RSS 데이터 수집 (개선: 더 많은 메타데이터)"""
    result = {"status": "활성", "posts": 0, "last_post": None,
              "recent_posts": [], "score": 0, "source": "rss"}
    try:
        rss_url = ACCOUNTS["blog"]["rss"]
        resp = requests.get(rss_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is not None:
                items = channel.findall("item")
                result["posts"] = len(items)
                for item in items[:10]:  # 최근 10개 (기존 5개에서 확대)
                    title = item.find("title")
                    pub_date = item.find("pubDate")
                    link = item.find("link")
                    desc = item.find("description")
                    result["recent_posts"].append({
                        "title": title.text if title is not None else "",
                        "date": _parse_rss_date(pub_date.text) if pub_date is not None else "",
                        "url": link.text if link is not None else "",
                        "summary": _clean_html(desc.text)[:100] if desc is not None and desc.text else "",
                    })
                if items:
                    pub = items[0].find("pubDate")
                    if pub is not None:
                        result["last_post"] = _parse_rss_date(pub.text)

    except Exception as e:
        print(f"[블로그 RSS] 수집 실패: {e}")

    # 점수 계산 (개선: 최근 활동 가중치)
    score = min(result["posts"] * 2, 40)
    if result["last_post"]:
        try:
            last_dt = datetime.strptime(result["last_post"], "%Y-%m-%d")
            days = (datetime.now() - last_dt).days
            if days <= 1:
                score += 40  # 어제/오늘 글
            elif days <= 3:
                score += 35
            elif days <= 7:
                score += 25
            elif days <= 30:
                score += 15
        except ValueError:
            pass
    # 최근 일주일 게시 빈도 보너스
    recent_count = sum(
        1 for p in result["recent_posts"]
        if p.get("date") and _days_ago(p["date"]) <= 7
    )
    score += min(recent_count * 5, 20)
    result["score"] = min(score, 100)
    return result


# ──────────────────────────────────────────────
# TikTok 데이터 수집
# ──────────────────────────────────────────────
def fetch_tiktok_data():
    """TikTok 프로필 데이터 수집 (스크래핑)"""
    result = {"status": "개설완료", "followers": 0, "following": 0,
              "likes": 0, "videos": 0, "score": 0, "source": "scrape"}
    tiktok_id = ACCOUNTS["tiktok"]["id"]

    if not tiktok_id:
        print("[TikTok] 계정 ID 미설정")
        result["source"] = "none"
        return result

    try:
        resp = requests.get(f"https://www.tiktok.com/@{tiktok_id}",
                          headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            html = resp.text
            # __UNIVERSAL_DATA_FOR_REHYDRATION__ 스크립트에서 추출
            follower_match = re.search(r'"followerCount":(\d+)', html)
            following_match = re.search(r'"followingCount":(\d+)', html)
            heart_match = re.search(r'"heartCount":(\d+)', html)
            video_match = re.search(r'"videoCount":(\d+)', html)

            if follower_match:
                result["followers"] = int(follower_match.group(1))
            if following_match:
                result["following"] = int(following_match.group(1))
            if heart_match:
                result["likes"] = int(heart_match.group(1))
            if video_match:
                result["videos"] = int(video_match.group(1))

            if result["videos"] > 0:
                result["status"] = "활성"
            elif follower_match is not None:
                result["status"] = "개설완료"

            print(f"[TikTok] 성공 - 팔로워 {result['followers']}, "
                  f"동영상 {result['videos']}개, 좋아요 {result['likes']}")
        else:
            print(f"[TikTok] HTTP {resp.status_code}")

    except Exception as e:
        print(f"[TikTok 스크래핑] 실패: {e}")

    # 이전값 복구
    if result["followers"] == 0 and result["videos"] == 0:
        prev_followers = _load_previous_value("tiktok", "followers")
        prev_videos = _load_previous_value("tiktok", "videos")
        if prev_followers:
            result["followers"] = prev_followers
        if prev_videos:
            result["videos"] = prev_videos

    # 점수 계산
    score = 0
    score += min(result["followers"] / 50, 30)    # 팔로워
    score += min(result["videos"] * 3, 30)         # 동영상 수
    score += min(result["likes"] / 10, 20)         # 좋아요
    if result["videos"] > 0:
        score += 10  # 활성 보너스
    result["score"] = min(int(score), 100)
    return result


# ──────────────────────────────────────────────
# Twitter(X) 데이터 수집
# ──────────────────────────────────────────────
def fetch_twitter_data():
    """Twitter(X) 프로필 데이터 수집 (스크래핑)"""
    result = {"status": "개설완료", "followers": 0, "following": 0,
              "tweets": 0, "score": 0, "source": "scrape"}
    twitter_id = ACCOUNTS["twitter"]["id"]

    if not twitter_id:
        print("[Twitter/X] 계정 ID 미설정")
        result["source"] = "none"
        return result

    methods_tried = []

    # 방식 1: Nitter 미러 사이트에서 데이터 수집 (X 직접 스크래핑 어려움)
    nitter_instances = [
        f"https://nitter.net/{twitter_id}",
        f"https://nitter.privacydev.net/{twitter_id}",
        f"https://nitter.poast.org/{twitter_id}",
    ]

    for nitter_url in nitter_instances:
        try:
            resp = requests.get(nitter_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Nitter 프로필 통계
                stats = soup.select(".profile-stat .profile-stat-num")
                if len(stats) >= 4:
                    result["tweets"] = _parse_nitter_number(stats[0].text)
                    result["following"] = _parse_nitter_number(stats[1].text)
                    result["followers"] = _parse_nitter_number(stats[2].text)
                    methods_tried.append(f"nitter 성공: {nitter_url.split('/')[2]}")
                    break
                # 대안: stat-value 클래스
                stat_values = soup.select(".stat-value")
                if stat_values:
                    for sv in stat_values:
                        parent_text = sv.parent.text.lower() if sv.parent else ""
                        if "follower" in parent_text or "팔로워" in parent_text:
                            result["followers"] = _parse_nitter_number(sv.text)
                        elif "following" in parent_text or "팔로잉" in parent_text:
                            result["following"] = _parse_nitter_number(sv.text)
                        elif "tweet" in parent_text or "post" in parent_text:
                            result["tweets"] = _parse_nitter_number(sv.text)
                    if result["followers"] > 0:
                        methods_tried.append(f"nitter alt: {nitter_url.split('/')[2]}")
                        break
        except Exception as e:
            methods_tried.append(f"nitter 실패({nitter_url.split('/')[2]}): {e}")

    # 방식 2: Twitter Syndication API (공개 프로필 정보)
    if result["followers"] == 0:
        try:
            syn_url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{twitter_id}"
            syn_headers = {
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
            resp = requests.get(syn_url, headers=syn_headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                # followers_count 패턴
                fc_match = re.search(r'"followers_count":(\d+)', html)
                if fc_match:
                    result["followers"] = int(fc_match.group(1))
                tc_match = re.search(r'"statuses_count":(\d+)', html)
                if tc_match:
                    result["tweets"] = int(tc_match.group(1))
                fgc_match = re.search(r'"friends_count":(\d+)', html)
                if fgc_match:
                    result["following"] = int(fgc_match.group(1))
                if result["followers"] > 0:
                    methods_tried.append("syndication API")
        except Exception as e:
            methods_tried.append(f"syndication 실패: {e}")

    # 방식 3: X/Twitter 직접 메타 태그 파싱
    if result["followers"] == 0:
        try:
            x_headers = {
                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
            resp = requests.get(f"https://x.com/{twitter_id}",
                              headers=x_headers, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
                # JSON-LD 또는 메타 태그에서 팔로워 추출
                follower_patterns = [
                    r'"followers_count":(\d+)',
                    r'"friendsCount":(\d+)',
                    r'followers_count&quot;:(\d+)',
                ]
                for pattern in follower_patterns:
                    match = re.search(pattern, html)
                    if match:
                        result["followers"] = int(match.group(1))
                        methods_tried.append("x.com JSON")
                        break

                # og:description에서 추출
                if result["followers"] == 0:
                    soup = BeautifulSoup(html, "html.parser")
                    meta = soup.find("meta", {"property": "og:description"})
                    if meta:
                        desc = meta.get("content", "")
                        f_match = re.search(r'([\d,\.]+(?:K|k|M|m)?)\s*[Ff]ollower', desc)
                        if f_match:
                            result["followers"] = _parse_korean_number(f_match.group(1))
                            methods_tried.append("x.com og:desc")
        except Exception as e:
            methods_tried.append(f"x.com 실패: {e}")

    # 이전값 복구
    if result["followers"] == 0 and result["tweets"] == 0:
        prev_followers = _load_previous_value("twitter", "followers")
        prev_tweets = _load_previous_value("twitter", "tweets")
        if prev_followers:
            result["followers"] = prev_followers
            methods_tried.append(f"이전값 사용: {prev_followers}")
        if prev_tweets:
            result["tweets"] = prev_tweets

    # 상태 판단
    if result["tweets"] > 0:
        result["status"] = "활성"
    elif result["followers"] > 0:
        result["status"] = "개설완료"

    print(f"[Twitter/X] 시도: {', '.join(methods_tried) if methods_tried else '없음'}")
    print(f"  → 팔로워 {result['followers']}, 트윗 {result['tweets']}개")

    # 점수 계산
    score = 0
    score += min(result["followers"] / 50, 30)   # 팔로워
    score += min(result["tweets"] * 2, 30)         # 트윗 수
    if result["tweets"] > 0:
        score += 20  # 활성 보너스
    if result["followers"] >= 100:
        score += 10  # 100명 이상 보너스
    result["score"] = min(int(score), 100)
    return result


def _parse_nitter_number(text):
    """Nitter 숫자 파싱 (1,234 / 12.3K / 1.5M 등)"""
    text = str(text).strip().replace(",", "")
    if "M" in text or "m" in text:
        return int(float(text.replace("M", "").replace("m", "")) * 1000000)
    if "K" in text or "k" in text:
        return int(float(text.replace("K", "").replace("k", "")) * 1000)
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return 0


# ──────────────────────────────────────────────
# 유틸리티 함수
# ──────────────────────────────────────────────
def _parse_korean_number(text):
    """한국식 숫자 표기 파싱 (6천, 1.2만, 6,000 등)"""
    text = str(text).strip().replace(",", "")
    if "만" in text:
        num = float(text.replace("만", "").replace("명", "").strip())
        return int(num * 10000)
    if "천" in text:
        num = float(text.replace("천", "").replace("명", "").strip())
        return int(num * 1000)
    if "K" in text or "k" in text:
        num = float(text.replace("K", "").replace("k", "").strip())
        return int(num * 1000)
    try:
        return int(float(text.replace("명", "").strip()))
    except (ValueError, TypeError):
        return 0


def _parse_rss_date(date_str):
    """RSS 날짜 문자열을 YYYY-MM-DD로 변환"""
    if not date_str:
        return ""
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z",
                "%a, %d %b %Y %H:%M:%S GMT"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str[:10] if len(date_str) >= 10 else ""


def _clean_html(text):
    """HTML 태그 제거"""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text).strip()


def _days_ago(date_str):
    """날짜 문자열이 며칠 전인지 계산"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (datetime.now() - dt).days
    except (ValueError, TypeError):
        return 9999


def _load_previous_value(platform, key):
    """이전 수집 데이터에서 값 복구 (fallback 하드코딩 제거용)"""
    data_path = os.path.join(DATA_DIR, "dashboard-data.json")
    try:
        if os.path.exists(data_path):
            with open(data_path, "r", encoding="utf-8") as f:
                dashboard = json.load(f)
            return dashboard.get("social_media", {}).get("platforms", {}).get(platform, {}).get(key)
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────
# 데이터 통합 및 저장
# ──────────────────────────────────────────────
def calculate_social_radar(platforms):
    """소셜미디어 레이더 차트용 점수 배열 생성 (7축: 차트 라벨 순서 일치)
    순서: YouTube, Facebook, Instagram, TikTok, X(Twitter), 네이버 블로그, 언론 노출(뉴스에서 갱신)
    """
    return [
        platforms["youtube"]["score"],      # 0: YouTube
        platforms["facebook"]["score"],     # 1: Facebook
        platforms["instagram"]["score"],    # 2: Instagram
        platforms["tiktok"]["score"],       # 3: TikTok
        platforms.get("twitter", {}).get("score", 0),  # 4: X (Twitter)
        platforms["blog"]["score"],         # 5: 네이버 블로그
        # 6: 언론 노출 — collect_news.py에서 별도 갱신, 여기선 기존값 유지
    ]


def build_recent_posts(youtube, facebook, instagram, blog, twitter=None):
    """최근 게시물 통합 목록 생성"""
    posts = []

    for v in youtube.get("recent_videos", [])[:3]:
        posts.append({
            "platform": "youtube",
            "title": v.get("title", ""),
            "date": v.get("date", ""),
            "url": v.get("url", ""),
            "metrics": {"views": v.get("views", 0)},
        })

    for p in facebook.get("recent_posts", [])[:3]:
        posts.append({
            "platform": "facebook",
            "title": p.get("message", "")[:80],
            "date": p.get("date", ""),
            "url": "",
            "metrics": {
                "likes": p.get("likes", 0),
                "comments": p.get("comments", 0),
                "shares": p.get("shares", 0),
            },
        })

    for p in instagram.get("recent_posts", [])[:3]:
        posts.append({
            "platform": "instagram",
            "title": p.get("caption", "")[:80],
            "date": p.get("date", ""),
            "url": p.get("url", ""),
            "metrics": {
                "likes": p.get("likes", 0),
                "comments": p.get("comments", 0),
            },
        })

    for p in blog.get("recent_posts", [])[:3]:
        posts.append({
            "platform": "blog",
            "title": p.get("title", ""),
            "date": p.get("date", ""),
            "url": p.get("url", ""),
            "metrics": {},
        })

    if twitter:
        for p in twitter.get("recent_tweets", [])[:3]:
            posts.append({
                "platform": "twitter",
                "title": p.get("text", "")[:80],
                "date": p.get("date", ""),
                "url": p.get("url", ""),
                "metrics": {
                    "likes": p.get("likes", 0),
                    "retweets": p.get("retweets", 0),
                },
            })

    posts.sort(key=lambda x: x.get("date", ""), reverse=True)
    return posts[:15]


def update_dashboard_data(social_data, date_str):
    """dashboard-data.json에 소셜미디어 데이터 반영 (기존 키 보존)
    social_radar 순서: [YouTube, Facebook, Instagram, TikTok, X(Twitter), 블로그, 언론노출]
    """
    data_path = os.path.join(DATA_DIR, "dashboard-data.json")
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            dashboard = json.load(f)
    else:
        dashboard = {}

    # social_media 섹션만 갱신
    dashboard["social_media"] = social_data

    # social_radar 점수 갱신 (7축: YouTube, FB, IG, TikTok, X, 블로그, 언론노출)
    if "social_radar" not in dashboard:
        dashboard["social_radar"] = {
            "이경혜": [5, 5, 5, 5, 5, 10, 45],
            "경쟁후보_평균": [35, 40, 30, 15, 20, 45, 50]
        }

    # 기존 배열이 6개인 경우 7개로 확장 (언론노출 기본값 추가)
    lkh_radar = dashboard["social_radar"]["이경혜"]
    if len(lkh_radar) < 7:
        # 기존: [yt, fb, ig, tiktok, blog, 언론노출] → 새: [yt, fb, ig, tiktok, X, blog, 언론노출]
        if len(lkh_radar) == 6:
            # 기존 position 4(blog)를 5로, 5(언론)를 6으로 밀고, 4에 X 삽입
            old_blog = lkh_radar[4]
            old_news = lkh_radar[5]
            lkh_radar = lkh_radar[:4] + [0, old_blog, old_news]
        else:
            lkh_radar = lkh_radar + [0] * (7 - len(lkh_radar))
        dashboard["social_radar"]["이경혜"] = lkh_radar

    comp_radar = dashboard["social_radar"].get("경쟁후보_평균", [35, 40, 30, 15, 45, 50])
    if len(comp_radar) < 7:
        if len(comp_radar) == 6:
            old_blog = comp_radar[4]
            old_news = comp_radar[5]
            comp_radar = comp_radar[:4] + [20, old_blog, old_news]
        else:
            comp_radar = comp_radar + [0] * (7 - len(comp_radar))
        dashboard["social_radar"]["경쟁후보_평균"] = comp_radar

    # social_radar 점수는 수동 관리 (자동 수집으로 덮어쓰지 않음)
    # 타 후보 포함 전체 점수는 index.html 및 dashboard-data.json에서 직접 관리

    # 경쟁력 레이더 소셜미디어 축 갱신
    if "competitiveness_radar" not in dashboard:
        dashboard["competitiveness_radar"] = {
            "이경혜": [80, 20, 35, 10, 45, 75, 70, 40]
        }
    avg_social = sum(scores) // max(len(scores), 1)
    dashboard["competitiveness_radar"]["이경혜"][3] = avg_social

    # collection_status 업데이트
    if "collection_status" not in dashboard:
        dashboard["collection_status"] = {}
    dashboard["collection_status"]["social_last_success"] = datetime.now().isoformat()

    # 수집 소스 요약
    sources = {}
    for platform_name, platform_data in social_data["platforms"].items():
        sources[platform_name] = platform_data.get("source", "unknown")
    dashboard["collection_status"]["social_sources"] = sources

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    print(f"[완료] dashboard-data.json 소셜미디어 갱신 완료")


def main():
    parser = argparse.ArgumentParser(description="소셜미디어 데이터 수집")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    print(f"[정보] 소셜미디어 데이터 수집 시작: {args.date}")
    print("[정보] API 키 상태:")
    print(f"  YouTube API: {'[O] 설정됨' if os.environ.get('YOUTUBE_API_KEY') else '[X] 미설정 -> 스크래핑'}")
    print(f"  Facebook Token: {'[O] 설정됨' if os.environ.get('FACEBOOK_PAGE_TOKEN') else '[X] 미설정 -> 스크래핑'}")
    print(f"  Instagram Token: {'[O] 설정됨' if os.environ.get('INSTAGRAM_ACCESS_TOKEN') else '[X] 미설정 -> 스크래핑'}")
    print(f"  Twitter/X: 스크래핑 (nitter fallback)")

    # 각 플랫폼 데이터 수집
    print("\n[수집] YouTube...")
    youtube = fetch_youtube_data()
    print(f"  ->영상 {youtube['videos']}개, 구독자 {youtube['subscribers']}, "
          f"점수 {youtube['score']} [{youtube.get('source', '?')}]")

    print("[수집] Facebook...")
    facebook = fetch_facebook_data()
    print(f"  ->팔로워 {facebook['followers']}, 점수 {facebook['score']} "
          f"[{facebook.get('source', '?')}]")

    print("[수집] Instagram...")
    instagram = fetch_instagram_data()
    print(f"  ->게시물 {instagram.get('posts', 0)}개, 팔로워 {instagram['followers']}, "
          f"점수 {instagram['score']} [{instagram.get('source', '?')}]")

    print("[수집] 네이버 블로그...")
    blog = fetch_blog_data()
    print(f"  ->글 {blog['posts']}개, 최근 {blog.get('last_post', '?')}, "
          f"점수 {blog['score']} [{blog.get('source', '?')}]")

    print("[수집] TikTok...")
    tiktok = fetch_tiktok_data()
    print(f"  ->팔로워 {tiktok['followers']}, 동영상 {tiktok['videos']}개, "
          f"좋아요 {tiktok['likes']}, 점수 {tiktok['score']} [{tiktok.get('source', '?')}]")

    print("[수집] Twitter/X...")
    twitter = fetch_twitter_data()
    print(f"  ->팔로워 {twitter['followers']}, 트윗 {twitter['tweets']}개, "
          f"점수 {twitter['score']} [{twitter.get('source', '?')}]")

    # 통합 데이터 구성
    social_data = {
        "platforms": {
            "youtube": youtube,
            "facebook": facebook,
            "instagram": instagram,
            "tiktok": tiktok,
            "twitter": twitter,
            "blog": blog,
        },
        "recent_posts": build_recent_posts(youtube, facebook, instagram, blog, twitter),
        "sentiment": {
            "positive": 55,
            "neutral": 30,
            "negative": 15,
        },
        "collected_at": datetime.now().isoformat(),
    }

    # dashboard-data.json 갱신
    update_dashboard_data(social_data, args.date)

    print(f"\n[완료] 소셜미디어 수집 완료")
    print(f"  YouTube: {youtube['score']}, FB: {facebook['score']}, "
          f"IG: {instagram['score']}, TikTok: {tiktok['score']}, "
          f"X: {twitter['score']}, Blog: {blog['score']}")


if __name__ == "__main__":
    main()
