#!/usr/bin/env python3
"""고양시장 선거 뉴스 수집, 분석 및 대시보드 데이터 갱신 스크립트"""

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

ELECTION_DATE = datetime(2026, 6, 3)

# 감성분석용 키워드 사전
POSITIVE_WORDS = [
    "성과", "확대", "지원", "개선", "혁신", "추진", "발전", "강화", "협력", "합의",
    "기대", "호평", "성공", "약속", "비전", "공약", "계획", "도약", "상승", "선두",
    "지지", "환영", "긍정", "돌파", "활성화", "투자", "유치", "개통", "착공", "완공"
]
NEGATIVE_WORDS = [
    "논란", "비판", "실패", "갈등", "반발", "의혹", "문제", "위기", "우려", "지적",
    "반대", "거부", "파문", "사퇴", "고발", "기소", "수사", "부정", "비리", "하락",
    "폭로", "규탄", "항의", "불만", "좌절", "지연", "무산", "철회", "중단", "파행"
]

# 이슈 카테고리 매핑
ISSUE_CATEGORIES = {
    "교통/경기패스": ["경기패스", "교통", "BRT", "트램", "고양패스", "버스", "지하철"],
    "신청사 이전": ["신청사", "청사", "원당", "백석"],
    "경제자유구역": ["경제자유구역", "경자구", "킨텍스", "MICE"],
    "1기 신도시 재건축": ["재건축", "재개발", "노후화", "일산", "신도시"],
    "교육 인프라": ["교육", "학교", "학원", "입시"],
    "환경/기후": ["환경", "기후", "탄소", "녹색", "생태"],
    "복지/돌봄": ["복지", "돌봄", "보육", "어린이", "노인", "장애"],
    "일자리/경제": ["일자리", "경제", "창업", "고용", "기업"]
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
DATA_DIR = os.path.join(PROJECT_DIR, "data")


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


def analyze_sentiment(text):
    """키워드 기반 감성분석 — 긍정/부정/중립 점수 반환"""
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
    total = pos_count + neg_count
    if total == 0:
        return {"positive": 0, "negative": 0, "neutral": 1}
    return {
        "positive": pos_count / total,
        "negative": neg_count / total,
        "neutral": 0
    }


def analyze_articles(articles):
    """기사 분석: 후보 언급, 키워드, 감성, 이슈, 일별 기사 수"""
    candidate_counter = Counter()
    keyword_counter = Counter()
    daily_counter = Counter()

    # 후보별 감성 점수
    candidate_sentiment = {name: {"pos": 0, "neg": 0, "total": 0} for name in CANDIDATE_NAMES}

    # 이슈별 기사 수
    issue_counter = {cat: 0 for cat in ISSUE_CATEGORIES}

    for article in articles:
        text = article["title"] + " " + article["description"]

        # 후보 언급 카운팅
        for name in article["candidates_mentioned"]:
            candidate_counter[name] += 1
            # 감성분석
            sent = analyze_sentiment(text)
            candidate_sentiment[name]["pos"] += sent["positive"]
            candidate_sentiment[name]["neg"] += sent["negative"]
            candidate_sentiment[name]["total"] += 1

        # 키워드 카운팅
        for kw in ["경기패스", "신청사", "GTX", "교통", "일산", "킨텍스",
                    "재개발", "경제자유구역", "BRT", "고양패스", "민주당",
                    "국민의힘", "경선", "여론조사"]:
            if kw in text:
                keyword_counter[kw] += 1

        # 이슈 카테고리 매칭
        for category, keywords in ISSUE_CATEGORIES.items():
            if any(kw in text for kw in keywords):
                issue_counter[category] += 1

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
        "candidate_sentiment": candidate_sentiment,
        "issue_counter": issue_counter,
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
        "summary": {
            "candidate_mentions": analysis["candidate_mentions"],
            "top_keywords": analysis["top_keywords"],
            "article_count_by_day": analysis["article_count_by_day"],
        },
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


def update_dashboard_data(analysis, date_str):
    """data/dashboard-data.json 갱신 — 뉴스 분석 결과 반영 (기존 키 보존)"""
    data_path = os.path.join(DATA_DIR, "dashboard-data.json")
    os.makedirs(DATA_DIR, exist_ok=True)

    # 기존 데이터 로드 (새 키들 보존을 위해 전체 로드)
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            dashboard = json.load(f)
    else:
        dashboard = {}

    # 보존할 키 목록 (이 함수가 관리하지 않는 키들)
    # candidates, polls, comparison_table, collection_status, social_media 등은 건드리지 않음

    # D-day 계산
    today = datetime.strptime(date_str, "%Y-%m-%d")
    d_day = (ELECTION_DATE - today).days

    # 헤더 업데이트
    dashboard["last_updated"] = date_str
    dashboard["election_date"] = "2026-06-03"
    dashboard["header"] = {
        "update_date": date_str.replace("-", "."),
        "d_day": d_day,
        "voters": "~89만 명"
    }

    # 감성분석 결과 업데이트
    sentiment = {}
    for name in CANDIDATE_NAMES:
        s = analysis["candidate_sentiment"][name]
        if s["total"] > 0:
            pos_pct = round(s["pos"] / s["total"] * 100)
            neg_pct = round(s["neg"] / s["total"] * 100)
            neu_pct = 100 - pos_pct - neg_pct
            score = pos_pct - neg_pct
            sentiment[name] = {
                "positive": pos_pct,
                "neutral": max(0, neu_pct),
                "negative": neg_pct,
                "score": score
            }
    if sentiment:
        dashboard["sentiment"] = sentiment

    # 이슈 관심도 업데이트 (기사 빈도 → 100점 만점 스케일)
    issue_data = analysis["issue_counter"]
    max_count = max(issue_data.values()) if issue_data and max(issue_data.values()) > 0 else 1
    dashboard["issue_interest"] = {
        "labels": list(issue_data.keys()),
        "data": [round(count / max_count * 100) for count in issue_data.values()]
    }

    # 언론 노출도 업데이트 (후보별 기사 수 → 100점 만점)
    mention_counts = {name: 0 for name in CANDIDATE_NAMES}
    for m in analysis["candidate_mentions"]:
        mention_counts[m["name"]] = m["count"]
    max_mentions = max(mention_counts.values()) if mention_counts and max(mention_counts.values()) > 0 else 1
    dashboard["media_exposure"] = {
        name: round(count / max_mentions * 100)
        for name, count in mention_counts.items()
        if count > 0
    }

    # 소셜미디어 레이더 — 언론노출 값만 갱신 (나머지는 유지)
    # 순서: [YouTube(0), Facebook(1), Instagram(2), TikTok(3), X(4), 블로그(5), 언론노출(6)]
    if "social_radar" not in dashboard:
        dashboard["social_radar"] = {
            "이경혜": [5, 5, 5, 5, 5, 10, 45],
            "경쟁후보_평균": [35, 40, 30, 15, 20, 45, 50]
        }
    # 기존 6개 배열 → 7개로 확장
    lkh_radar = dashboard["social_radar"]["이경혜"]
    if len(lkh_radar) < 7:
        if len(lkh_radar) == 6:
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

    lkh_exposure = dashboard["media_exposure"].get("이경혜", 45)
    dashboard["social_radar"]["이경혜"][6] = lkh_exposure  # 인덱스 6 = 언론 노출

    # 경쟁력 레이더 — 언론노출 값만 갱신
    if "competitiveness_radar" not in dashboard:
        dashboard["competitiveness_radar"] = {
            "이경혜": [80, 20, 35, 10, 45, 75, 70, 40],
            "명재성": [65, 60, 55, 30, 50, 50, 45, 85],
            "이재준": [70, 65, 60, 40, 60, 55, 55, 90]
        }
    dashboard["competitiveness_radar"]["이경혜"][4] = lkh_exposure

    # collection_status 업데이트
    if "collection_status" not in dashboard:
        dashboard["collection_status"] = {}
    dashboard["collection_status"]["news_last_success"] = datetime.now().isoformat()
    dashboard["collection_status"]["news_articles_collected"] = sum(
        m["count"] for m in analysis["candidate_mentions"]
    )

    # sentiment_details 업데이트 (가중치 감성 상세)
    if "sentiment_details" not in dashboard:
        dashboard["sentiment_details"] = {}
    for name in CANDIDATE_NAMES:
        s = analysis["candidate_sentiment"][name]
        if s["total"] > 0:
            pos_pct = round(s["pos"] / s["total"] * 100)
            neg_pct = round(s["neg"] / s["total"] * 100)
            details = dashboard["sentiment_details"].get(name, {})
            details.update({
                "positive": pos_pct,
                "neutral": max(0, 100 - pos_pct - neg_pct),
                "negative": neg_pct,
                "score": pos_pct - neg_pct,
                "article_count": s["total"],
                "weighted_score": pos_pct - neg_pct
            })
            # sample_positive/negative는 기존 값 유지 (수동 관리)
            if "sample_positive" not in details:
                details["sample_positive"] = []
            if "sample_negative" not in details:
                details["sample_negative"] = []
            dashboard["sentiment_details"][name] = details

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    print(f"[완료] dashboard-data.json 갱신: D-{d_day}, 감성분석 {len(sentiment)}명, 이슈 {len(issue_data)}개")


def main():
    parser = argparse.ArgumentParser(description="고양시장 선거 뉴스 수집")
    parser.add_argument("--type", choices=["hourly", "weekly", "monthly"], required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("오류: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 환경변수를 설정하세요.", file=sys.stderr)
        sys.exit(1)

    report_date = datetime.strptime(args.date, "%Y-%m-%d")

    if args.type == "hourly":
        # hourly: 최근 24시간 기사로 대시보드 데이터만 갱신 (보고서 파일 생성 안함)
        period_start = report_date - timedelta(days=1)
        period_end = report_date.replace(hour=23, minute=59, second=59)
    elif args.type == "weekly":
        period_start = report_date - timedelta(days=7)
        period_end = report_date.replace(hour=23, minute=59, second=59)
    else:
        period_start = report_date.replace(day=1) - timedelta(days=1)
        period_start = period_start.replace(day=1)
        period_end = report_date.replace(hour=23, minute=59, second=59)

    period_start = period_start.astimezone() if period_start.tzinfo else period_start
    period_end = period_end.astimezone() if period_end.tzinfo else period_end

    print(f"[정보] {args.type} {'데이터 갱신' if args.type == 'hourly' else '보고서 생성'}: {period_start.date()} ~ {period_end.date()}")
    print(f"[정보] 키워드 {len(ALL_KEYWORDS)}개로 검색 시작...")

    articles = collect_articles(client_id, client_secret, ALL_KEYWORDS, period_start, period_end)
    print(f"[정보] 수집 기사: {len(articles)}건")

    analysis = analyze_articles(articles)

    # 대시보드 데이터 갱신 (매시간)
    update_dashboard_data(analysis, args.date)

    # hourly는 대시보드 데이터만 갱신하고 종료
    if args.type == "hourly":
        print(f"[완료] hourly 대시보드 갱신 완료 ({len(articles)}건 분석)")
        return

    # weekly/monthly는 보고서 파일도 생성
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
