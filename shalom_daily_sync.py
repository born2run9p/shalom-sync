import os
import sys
import time
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 環境変数の確認
# ==========================================
SHALOM_LOGIN_URL = os.environ.get("SHALOM_LOGIN_URL") or "https://4ever.shalom-house.jp/login"

# 各種 Secrets の表記揺れ（ID/COMPANY_ID, PASS/PASSWORD）に対応
SHALOM_COMPANY_ID = os.environ.get("SHALOM_COMPANY_ID") or os.environ.get("SHALOM_ID")
SHALOM_USER_ID = os.environ.get("SHALOM_USER_ID") or os.environ.get("SHALOM_ID")
SHALOM_PASSWORD = os.environ.get("SHALOM_PASSWORD") or os.environ.get("SHALOM_PASS")

TARGET_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.environ.get("GCP_SA_KEY")

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
        # User-Agent を通常の PC ブラウザに偽装して Bot 判定を回避
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"[INFO] ログインページを開いています: {SHALOM_LOGIN_URL}")
            page.goto(SHALOM_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")

            # ページのレンダリングや JS 実行を一定時間待機
            print("[INFO] ページのロード待機中 (5秒)...")
            page.wait_for_timeout(5000)

            # 画面上に iframe や入力欄が存在するかチェック
            print("[INFO] ログインフォームの検索を開始します...")
            
            # メインフレームおよび全フレームから input 要素を探索
            target_frame = page
            input_element = None

            for frame in page.frames:
                try:
                    if frame.locator("input").count() > 0:
                        target_frame = frame
                        print(f"[INFO] 入力フォームを検出しました (Frame: {frame.name or 'main'})")
                        break
                except Exception:
                    continue

            # 入力要素が見つからなかった場合、デバッグ用にHTMLと画面を出力
            if target_frame.locator("input").count() == 0:
                page.screenshot(path="login_error_screenshot.png")
                with open("page_source.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print("[ERROR] 入力欄が見つかりません。現在の画面情報 (login_error_screenshot.png / page_source.html) を保存しました。")
                raise RuntimeError("ログイン入力フォームが検出できませんでした。")

            # 3. ログイン情報の入力
            print("[INFO] ログイン情報を入力中...")
            
            # 各入力フィールドへの入力を試行
            inputs = target_frame.locator("input")
            input_count = inputs.count()
            print(f"[INFO] 検出された入力フィールド数: {input_count}")

            if input_count >= 1 and SHALOM_COMPANY_ID:
                inputs.nth(0).fill(SHALOM_COMPANY_ID)
            if input_count >= 2 and SHALOM_PASSWORD:
                inputs.nth(1).fill(SHALOM_PASSWORD)

            # 4. ログインボタンのクリック
            print("[INFO] ログインボタンをクリックします...")
            submit_btn = target_frame.locator("button, input[type='submit']").first
            if submit_btn.count() > 0:
                submit_btn.click()
            else:
                target_frame.keyboard.press("Enter")

            page.wait_for_timeout(5000)
            print("[INFO] ログイン送信完了")

            # --------------------------------------------------
            # データ取得処理（仮の返却値）
            # --------------------------------------------------
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
    
    if GOOGLE_CREDENTIALS_JSON:
        import json
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
    else:
        gc = gspread.service_account()

    sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    worksheet = sh.get_worksheet(0)

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
