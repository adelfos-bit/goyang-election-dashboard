import http.server
import socketserver
import os
import sys
import subprocess
import threading
import time
from datetime import datetime, timedelta

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(line_buffering=True)

# .env 파일에서 환경변수 로드
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

PORT = 3000
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
PYTHON = sys.executable

# 수집 주기 (초)
NEWS_INTERVAL = 6 * 3600    # 6시간
SOCIAL_INTERVAL = 3 * 3600  # 3시간
REPORT_CHECK_INTERVAL = 3600  # 1시간마다 보고서 생성 여부 체크


def run_collector(script_name, extra_args=None):
    """수집 스크립트 실행"""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"[수집] 스크립트 없음: {script_name}")
        return False

    cmd = [PYTHON, script_path]
    if extra_args:
        cmd.extend(extra_args)

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[수집] {now} | {script_name} 실행 중...")
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        if result.returncode == 0:
            print(f"[수집] {script_name} 완료")
        else:
            print(f"[수집] {script_name} 오류 (코드 {result.returncode})")
            if result.stderr:
                for line in result.stderr.strip().split('\n')[:5]:
                    print(f"  > {line}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[수집] {script_name} 타임아웃 (120초)")
        return False
    except Exception as e:
        print(f"[수집] {script_name} 실행 실패: {e}")
        return False


def news_scheduler():
    """뉴스 수집 스케줄러 (6시간 간격)"""
    time.sleep(5)

    if not os.environ.get('NAVER_CLIENT_ID'):
        print("[수집] NAVER_CLIENT_ID 미설정 → 뉴스 자동 수집 비활성")
        return

    print(f"[수집] 뉴스 자동 수집 시작 (간격: {NEWS_INTERVAL // 3600}시간)")
    while True:
        today = datetime.now().strftime('%Y-%m-%d')
        run_collector('collect_news.py', ['--type', 'hourly', '--date', today])
        time.sleep(NEWS_INTERVAL)


def social_scheduler():
    """소셜미디어 수집 스케줄러 (3시간 간격)"""
    time.sleep(10)
    print(f"[수집] 소셜미디어 자동 수집 시작 (간격: {SOCIAL_INTERVAL // 3600}시간)")
    while True:
        today = datetime.now().strftime('%Y-%m-%d')
        run_collector('collect_social.py', ['--date', today])
        time.sleep(SOCIAL_INTERVAL)


def report_scheduler():
    """정기 보고서 자동 생성 스케줄러
    - 주간 보고서: 매주 월요일 자동 생성 (직전 7일)
    - 월간 보고서: 매월 1일 자동 생성 (직전 한 달)
    - 서버 시작 시: 이번 주/이번 달 보고서가 없으면 즉시 생성
    """
    time.sleep(15)

    if not os.environ.get('NAVER_CLIENT_ID'):
        print("[보고서] NAVER_CLIENT_ID 미설정 → 정기 보고서 자동 생성 비활성")
        return

    import json
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    manifest_path = os.path.join(reports_dir, 'index.json')

    def get_existing_reports():
        """매니페스트에서 기존 보고서 목록 로드 (type, date) → article_count"""
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return {(r['type'], r['date']): r.get('article_count', 0)
                        for r in data.get('reports', [])}
            except Exception:
                pass
        return {}

    def get_current_week_monday():
        """이번 주 월요일 날짜"""
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        return monday.strftime('%Y-%m-%d')

    def get_current_month_first():
        """이번 달 1일 날짜"""
        return datetime.now().replace(day=1).strftime('%Y-%m-%d')

    def generate_report(report_type, date_str):
        """보고서 생성 실행"""
        print(f"[보고서] {report_type} 보고서 생성 시작: {date_str}")
        success = run_collector('collect_news.py', ['--type', report_type, '--date', date_str])
        if success:
            print(f"[보고서] {report_type} 보고서 생성 완료: {date_str}")
        else:
            print(f"[보고서] {report_type} 보고서 생성 실패: {date_str}")
        return success

    def needs_generation(existing, report_type, date_str):
        """보고서가 없거나 0건이면 재생성 필요"""
        key = (report_type, date_str)
        if key not in existing:
            return True
        return existing[key] == 0  # 0건 보고서는 재생성 시도

    print("[보고서] 정기 보고서 자동 생성 스케줄러 시작")

    # 서버 시작 시 누락되거나 0건인 보고서 즉시 생성
    existing = get_existing_reports()
    monday = get_current_week_monday()
    month_first = get_current_month_first()

    if needs_generation(existing, 'weekly', monday):
        count = existing.get(('weekly', monday), -1)
        reason = "없음" if count == -1 else f"0건 → 재생성"
        print(f"[보고서] 이번 주 주간 보고서 {reason} → 생성 ({monday})")
        generate_report('weekly', monday)

    if needs_generation(existing, 'monthly', month_first):
        count = existing.get(('monthly', month_first), -1)
        reason = "없음" if count == -1 else f"0건 → 재생성"
        print(f"[보고서] 이번 달 월간 보고서 {reason} → 생성 ({month_first})")
        generate_report('monthly', month_first)

    # 주기적 체크 루프
    while True:
        time.sleep(REPORT_CHECK_INTERVAL)

        now = datetime.now()
        existing = get_existing_reports()

        # 월요일이면 주간 보고서 체크
        if now.weekday() == 0:  # 월요일
            monday = now.strftime('%Y-%m-%d')
            if needs_generation(existing, 'weekly', monday):
                generate_report('weekly', monday)

        # 1일이면 월간 보고서 체크
        if now.day == 1:
            month_first = now.strftime('%Y-%m-%d')
            if needs_generation(existing, 'monthly', month_first):
                generate_report('monthly', month_first)

        # 매시간: 최근 보고서 중 0건인 것 재생성 시도 (최대 1개)
        for (rtype, rdate), count in list(existing.items()):
            if count == 0:
                print(f"[보고서] 0건 보고서 재생성 시도: {rtype}/{rdate}")
                generate_report(rtype, rdate)
                break  # 한 번에 하나만


# 스케줄러 데몬 스레드 시작
news_thread = threading.Thread(target=news_scheduler, daemon=True)
social_thread = threading.Thread(target=social_scheduler, daemon=True)
report_thread = threading.Thread(target=report_scheduler, daemon=True)
news_thread.start()
social_thread.start()
report_thread.start()

handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
    print(f"Serving at http://127.0.0.1:{PORT}")
    print(f"[자동수집] 소셜미디어: 3시간 간격 | 뉴스: 6시간 간격 (API 키 필요)")
    print(f"[자동생성] 주간 보고서: 매주 월요일 | 월간 보고서: 매월 1일")
    httpd.serve_forever()
