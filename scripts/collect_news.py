#!/usr/bin/env python3
"""고양시장 선거 뉴스 수집 및 보고서 생성 스크립트"""

import os
import sys
import json
import argparse
import time
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from collections import Counter
from urllib.parse import quote

import requests

NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"

PRIMARY_KEYWORDS = [
    "고양시장 선거", "고양시장 후보", "고양특례시장", "2026 고양시장"
]
CANDIDATE_KEYWORDS = [
    "이경혜 고양", "명재성 고양", "정병춘 고양", "이재준 고양",
    "이동환 고양", "민경선 고양", "장제환 고양"
]
ISSUE_KEYWORDS = [
    "고양 경기패스", "고양 신청사", "고양 GTX"
]
ALL_KEYWORDS = PRIMARY_KEYWORDS + CANDIDATE_KEYWORDS + ISSUE_KEYWORDS

CANDIDATE_NAMES = [
    "이경혜", "명재성", "정병춘", "이재준", "이동환",
    "민경선", "장제환", "이영아", "최승원"
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")


def strip_html(text):
    """HTML 태그 및 엔티티 제거"""
    text = re.sub(r"<[^>]*>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&apos;", "'")
    return text.strip()


def search_naver_news(client_id, client_secret, query, display=100, start=1):
    """네이버 뉴스 검색 API 호출"""
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {
        "query": query,
        "display": display,
        "start": start,
        "sort": "date",
    }
    resp = requests.get(NAVER_API_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def parse_pub_date(pub_date_str):
    """네이버 API pubDate (RFC 2822) 파싱"""
    try:
        return parsedate_to_datetime(pub_date_str)
    except Exception:
        return None


def collect_articles(client_id, client_secret, keywords, period_start, period_end):
    """키워드별 기사 수집 및 기간 필터링"""
    seen = set()
    articles = []

    for keyword in keywords:
        try:
            data = search_naver_news(client_id, client_secret, keyword)
        except Exception as e:
            print(f"[경고] '{keyword}' 검색 실패: {e}", file=sys.stderr)
            time.sleep(0.1)
            continue

        for item in data.get("items", []):
            link = item.get("originallink") or item.get("link", "")
            if link in seen:
                continue
            seen.add(link)

            pub_dt = parse_pub_date(item.get("pubDate", ""))
            if pub_dt is None:
                continue
            if pub_dt < period_start or pub_dt > period_end:
                continue

            title_clean = strip_html(item.get("title", ""))
            desc_clean = strip_html(item.get("description", ""))
            text = title_clean + " " + desc_clean

            mentioned = [name for name in CANDIDATE_NAMES if name in text]

            articles.append({
                "title": title_clean,
                "link": item.get("link", ""),
                "originallink": link,
                "description": desc_clean[:200],
                "pubDate": pub_dt.isoformat(),
                "candidates_mentioned": mentioned,
                "keywords_matched": [keyword],
            })

        time.sleep(0.1)

    articles.sort(key=lambda a: a["pubDate"], reverse=True)
    return articles


def analyze_articles(articles):
    """기사 분석: 후보 언급, 키워드, 일별 기사 수"""
    candidate_counter = Counter()
    keyword_counter = Counter()
    daily_counter = Counter()

    for article in articles:
        for name in article["candidates_mentioned"]:
            candidate_counter[name] += 1

        text = article["title"] + " " + article["description"]
        for kw in ["경기패스", "신청사", "GTX", "교통", "일산", "킨텍스",
                    "재개발", "경제자유구역", "BRT", "고양패스", "민주당",
                    "국민의힘", "경선", "여론조사"]:
            if kw in text:
                keyword_counter[kw] += 1

        day = article["pubDate"][:10]
        daily_counter[day] += 1

    candidate_mentions = [
        {"name": name, "count": candidate_counter.get(name, 0)}
        for name in CANDIDATE_NAMES
        if candidate_counter.get(name, 0) > 0
    ]
    candidate_mentions.sort(key=lambda x: x["count"], reverse=True)

    top_keywords = [
        {"keyword": kw, "count": cnt}
        for kw, cnt in keyword_counter.most_common(10)
    ]

    article_count_by_day = dict(sorted(daily_counter.items()))

    return {
        "candidate_mentions": candidate_mentions,
        "top_keywords": top_keywords,
        "article_count_by_day": article_count_by_day,
    }


def build_report(report_type, date_str, period_start, period_end, articles, analysis):
    """보고서 JSON 구성"""
    return {
        "meta": {
            "type": report_type,
            "date": date_str,
            "period_start": period_start.strftime("%Y-%m-%d"),
            "period_end": period_end.strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
            "total_articles_found": len(articles),
            "keywords_used": ALL_KEYWORDS,
        },
        "summary": analysis,
        "articles": articles,
    }


def update_manifest(report_type, date_str, filename, article_count):
    """reports/index.json 매니페스트 업데이트"""
    manifest_path = os.path.join(REPORTS_DIR, "index.json")

    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"last_updated": None, "reports": []}

    manifest["reports"] = [
        r for r in manifest["reports"]
        if not (r["type"] == report_type and r["date"] == date_str)
    ]

    manifest["reports"].append({
        "type": report_type,
        "date": date_str,
        "file": filename,
        "article_count": article_count,
    })

    manifest["reports"].sort(key=lambda r: r["date"], reverse=True)
    manifest["last_updated"] = datetime.now().isoformat()

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="고양시장 선거 뉴스 수집")
    parser.add_argument("--type", choices=["weekly", "monthly"], required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("오류: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 환경변수를 설정하세요.", file=sys.stderr)
        sys.exit(1)

    report_date = datetime.strptime(args.date, "%Y-%m-%d")

    if args.type == "weekly":
        period_start = report_date - timedelta(days=7)
        period_end = report_date.replace(hour=23, minute=59, second=59)
    else:
        period_start = report_date.replace(day=1) - timedelta(days=1)
        period_start = period_start.replace(day=1)
        period_end = report_date.replace(hour=23, minute=59, second=59)

    period_start = period_start.astimezone() if period_start.tzinfo else period_start
    period_end = period_end.astimezone() if period_end.tzinfo else period_end

    print(f"[정보] {args.type} 보고서 생성: {period_start.date()} ~ {period_end.date()}")
    print(f"[정보] 키워드 {len(ALL_KEYWORDS)}개로 검색 시작...")

    articles = collect_articles(client_id, client_secret, ALL_KEYWORDS, period_start, period_end)
    print(f"[정보] 수집 기사: {len(articles)}건")

    analysis = analyze_articles(articles)
    report = build_report(args.type, args.date, period_start, period_end, articles, analysis)

    type_dir = os.path.join(REPORTS_DIR, args.type)
    os.makedirs(type_dir, exist_ok=True)

    filename = f"{args.type}/{args.date}.json"
    filepath = os.path.join(REPORTS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    update_manifest(args.type, args.date, filename, len(articles))

    print(f"[완료] 보고서 저장: {filepath}")
    print(f"[완료] 매니페스트 업데이트 완료")


if __name__ == "__main__":
    main()
