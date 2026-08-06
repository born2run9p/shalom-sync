import os
import json
import time
import re
import pyotp
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# ------------------------------------------------------------------------------
# 1. 環境変数の取得とバリデーション
# ------------------------------------------------------------------------------
SHALOM_ID = os.environ.get("SHALOM_ID")
SHALOM_PASS = os.environ.get("SHALOM_PASS")
TOTP_SECRET = os.environ.get("TOTP_SECRET")
GCP_SA_KEY_JSON = os.environ.get("GCP_SA_KEY")
TARGET_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY")

if not all([SHALOM_ID, SHALOM_PASS, TOTP_SECRET, GCP_SA_KEY_JSON, TARGET_SPREADSHEET_KEY]):
    raise ValueError("[ERROR] 必須の環境変数が設定されていません。GitHub Secrets を確認してください。")

# ------------------------------------------------------------------------------
# 2. Google スプレッドシートの認証と接続設定
# ------------------------------------------------------------------------------
def get_gspread_client(sa_key_json):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    key_dict = json.loads(sa_key_json)
    creds = Credentials.from_service_account_info(key_dict, scopes=scopes)
    return gspread.authorize(creds)

# ------------------------------------------------------------------------------
# 3. 社労夢ログイン & データ取得 (Playwright)
# ------------------------------------------------------------------------------
def fetch_shalom_data():
    print("[INFO] 社労夢へのリモートアクセスを開始します...")
    
    with sync_playwright() as p:
        # ブラウザ起動 (headless=True)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # ログインページへ移動
            print("[INFO] ログインページを開いています...")
            page.goto("https://www.shalom-house.jp/login/", wait_until="networkidle")

            # ID / PASS 入力
            page.fill("input[name='company_id']", SHALOM_ID)
            page.fill("input[name='password']", SHALOM_PASS)
            
            # ワンタイムパスワード (TOTP) 生成と入力
            totp = pyotp.TOTP(TOTP_SECRET)
            otp_code = totp.now()
            print(f"[INFO] 2段階認証コードを生成しました: {otp_code}")
            
            if page.locator("input[name='otp']").is_visible():
                page.fill("input[name='otp']", otp_code)

            # ログインボタンクリック
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")
            print("[INFO] ログインに成功しました。")

            # データ取得処理（公文書／電子申請一覧）
            # ※ 社労夢画面のテーブルから行データを抽出
            page.goto("https://www.shalom-house.jp/e-gov/list", wait_until="networkidle")
            time.sleep(3) # 読み込み安定用ウェイティング

            rows = page.locator("table.data-table tbody tr").all()
            print(f"[INFO] 取得対象データ件数: {len(rows)} 件")

            data_list = []
            for row in rows:
                cols = [c.inner_text().strip() for c in row.locator("td").all()]
                if not cols or len(cols) < 5:
                    continue
                
                # 想定データ構造の抽出（社労夢のテーブル列順に合わせる）
                # 例: [申請日時, 会社名, 手続名, 現在状況, 公文書保管完了, ...]
                item = {
                    "apply_date": cols[0] if len(cols) > 0 else "",
                    "company_name": cols[1] if len(cols) > 1 else "",
                    "procedure_name": cols[2] if len(cols) > 2 else "",
                    "status": cols[3] if len(cols) > 3 else "",          # 現在状況
                    "archive_status": cols[4] if len(cols) > 4 else "",  # 公文書保管完了
                    "raw_cols": cols
                }
                data_list.append(item)

            browser.close()
            return data_list

        except Exception as e:
            browser.close()
            print(f"[ERROR] 社労夢からのデータ取得中にエラーが発生しました: {e}")
            raise e

# ------------------------------------------------------------------------------
# 4. データのフィルタリングとスプレッドシート更新
# ------------------------------------------------------------------------------
def filter_and_update_sheets(gc, raw_data):
    sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    
    # 対象のワークシート (gid: 1520113795)
    # gspreadではgid指定でワークシートを取得可能
    target_worksheet = None
    for ws in sh.worksheets():
        if str(ws.id) == "1520113795":
            target_worksheet = ws
            break

    if not target_worksheet:
        print("[WARNING] gid: 1520113795 のシートが見つからないため、1枚目のシートを使用します。")
        target_worksheet = sh.get_worksheet(0)

    print(f"[INFO] 更新対象シート: {target_worksheet.title} (gid: {target_worksheet.id})")

    # --- 条件抽出フィルタリング ---
    # 条件: 「現在状況」が「終了」 かつ 「公文書保管完了」が「保存済み」のものは除外
    filtered_rows = []
    excluded_count = 0

    for item in raw_data:
        status = item.get("status", "").strip()
        archive_status = item.get("archive_status", "").strip()

        # 除外条件判定
        if status == "終了" and archive_status == "保存済み":
            excluded_count += 1
            continue

        # 除外されなかったデータを保持
        filtered_rows.append(item["raw_cols"])

    print(f"[INFO] フィルタリング完了: 全 {len(raw_data)} 件中、{excluded_count} 件を除外（残数: {len(filtered_rows)} 件）")

    # スプレッドシートへの書き込み
    # 既存データのクリアと一括上書き
    if filtered_rows:
        # ヘッダー行を維持するためにA2セル以降をクリアして書き込み
        target_worksheet.sub_archive_range = f"A2:Z{len(filtered_rows) + 500}"
        target_worksheet.batch_clear([target_worksheet.sub_archive_range])
        target_worksheet.update("A2", filtered_rows)
        print("[SUCCESS] スプレッドシートへの書き込みが完了しました。")
    else:
        print("[INFO] 書き込む対象データがありません。")

# ------------------------------------------------------------------------------
# 5. メイン実行処理
# ------------------------------------------------------------------------------
def run():
    print("[INFO] ===== 社労夢 デイリー同期処理 開始 =====")
    
    # Google API 接続
    gc = get_gspread_client(GCP_SA_KEY_JSON)
    
    # 社労夢データ取得
    raw_data = fetch_shalom_data()
    
    # フィルタリング & 書き込み
    filter_and_update_sheets(gc, raw_data)
    
    print("[INFO] ===== 社労夢 デイリー同期処理 完了 =====")

if __name__ == "__main__":
    run()
