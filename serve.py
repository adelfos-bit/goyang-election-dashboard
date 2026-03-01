import http.server
import socketserver
import os
import sys
import subprocess
import threading
import time
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(line_buffering=True)

# .env 파일에서 환경변수 로드
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

PORT = 3000
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
PYTHON = sys.executable

# 수집 주기 (초)
NEWS_INTERVAL = 6 * 3600    # 6시간
SOCIAL_INTERVAL = 3 * 3600  # 3시간


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


# 스케줄러 데몬 스레드 시작
news_thread = threading.Thread(target=news_scheduler, daemon=True)
social_thread = threading.Thread(target=social_scheduler, daemon=True)
news_thread.start()
social_thread.start()

handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("", PORT), handler) as httpd:
    print(f"Serving at http://127.0.0.1:{PORT}")
    print(f"[자동수집] 소셜미디어: 3시간 간격 | 뉴스: 6시간 간격 (API 키 필요)")
    httpd.serve_forever()
