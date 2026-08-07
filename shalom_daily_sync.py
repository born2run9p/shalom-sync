import os
import sys
import time
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 環境変数の確認
# ==========================================
SHALOM_LOGIN_URL = os.environ.get("SHALOM_LOGIN_URL")
SHALOM_COMPANY_ID = os.environ.get("SHALOM_COMPANY_ID") or os.environ.get("SHALOM_ID")
SHALOM_USER_ID = os.environ.get("SHALOM_USER_ID")
SHALOM_PASSWORD = os.environ.get("SHALOM_PASSWORD")
TARGET_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

missing_vars = []
if not TARGET_SPREADSHEET_KEY:
    missing_vars.append("TARGET_SPREADSHEET_KEY")

if missing_vars:
    print(f"[ERROR] 以下の環境変数が設定されていません: {', '.join(missing_vars)}")
    print("GitHubのリポジトリ Settings -> Secrets and variables -> Actions を確認してください。")
    sys.exit(1)


# ==========================================
# 2. 社労夢からのデータ取得 (Playwright)
# ==========================================
def fetch_shalom_data():
    print("[INFO] 社労夢へのリモートアクセスを開始します...")
    
    with sync_playwright() as p:
        # デバッグや画面確認をしやすくするため、必要に応じて headless=False に変更可能
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        try:
            # 1. ログインページへアクセス
            target_url = SHALOM_LOGIN_URL or "https://www.e-shalom.org/" # ※デフォルトURLがある場合は指定
            print(f"[INFO] ログインページを開いています: {target_url}")
            
            # ページ読み込みのタイムアウトを 60 秒に延長
            page.goto(target_url, timeout=60000, wait_until="networkidle")

            # 2. ログイン要素の待機処理（最大60秒待機）
            print("[INFO] ログインフォームの読み込みを待機しています...")
            
            # company_id または 汎用的な入力フォームの出現を監視
            try:
                page.wait_for_selector("input[name='company_id']", timeout=60000)
            except Exception:
                # タイムアウトした場合、状況特定のためスクリーンショットを出力
                page.screenshot(path="login_error_screenshot.png")
                print("[ERROR] ログイン入力欄が見つかりませんでした。現在の画面のスクリーンショット (login_error_screenshot.png) を保存しました。")
                raise

            # 3. ログイン情報の入力
            print("[INFO] ログイン情報を入力中...")
            if SHALOM_COMPANY_ID:
                page.fill("input[name='company_id']", SHALOM_COMPANY_ID)
            if SHALOM_USER_ID:
                page.fill("input[name='user_id']", SHALOM_USER_ID)
            if SHALOM_PASSWORD:
                page.fill("input[name='password']", SHALOM_PASSWORD)

            # 4. ログインボタンのクリック
            print("[INFO] ログインボタンをクリックします...")
            # 送信ボタンのセレクタ（環境に合わせて要調整）
            submit_button = page.locator("input[type='submit'], button[type='submit']").first
            submit_button.click()

            page.wait_for_load_state("networkidle", timeout=60000)
            print("[INFO] ログイン処理が完了しました。")

            # --------------------------------------------------
            # ※ここに社労夢内のデータ取得・CSVダウンロード等の処理を記述
            # --------------------------------------------------
            
            # 取得データのサンプル（実際の抽出処理に合わせて変更してください）
            fetched_data = [
                ["更新日時", "ステータス"],
                [time.strftime("%Y-%m-%d %H:%M:%S"), "成功"]
            ]

            return fetched_data

        except Exception as e:
            print(f"[ERROR] 社労夢からのデータ取得中にエラーが発生しました: {e}")
            raise
        finally:
            browser.close()


# ==========================================
# 3. Google スプレッドシートへの書き込み
# ==========================================
def update_spreadsheet(data):
    print("[INFO] スプレッドシートへの書き込み処理を開始します...")
    
    # サービスアカウント認証の設定
    if GOOGLE_CREDENTIALS_JSON:
        import json
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
    else:
        # ローカル等でデフォルトの認証ファイルを使用する場合
        gc = gspread.service_account()

    sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    worksheet = sh.get_worksheet(0) # 一番左のシートを指定

    # データを書き込み
    worksheet.clear()
    worksheet.update('A1', data)
    print("[INFO] スプレッドシートの更新が完了しました！")


# ==========================================
# 4. メイン実行処理
# ==========================================
def run():
    print("[INFO] ===== 社労夢 デイリー同期処理 開始 =====")
    try:
        raw_data = fetch_shalom_data()
        if raw_data:
            update_spreadsheet(raw_data)
        print("[INFO] ===== 社労夢 デイリー同期処理 正常終了 =====")
    except Exception as e:
        print(f"[FATAL] 処理が異常終了しました: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
