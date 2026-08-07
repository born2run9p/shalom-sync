import os
import sys
import time
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 環境変数と設定値
# ==========================================
SHALOM_LOGIN_URL = os.environ.get("SHALOM_LOGIN_URL") or "https://4ever.shalom-house.jp/login"

# Secretsの各種キー名に対応
SHALOM_COMPANY_ID = os.environ.get("SHALOM_COMPANY_ID") or os.environ.get("SHALOM_ID")
SHALOM_USER_ID = os.environ.get("SHALOM_USER_ID") or os.environ.get("SHALOM_ID")
SHALOM_PASSWORD = os.environ.get("SHALOM_PASSWORD") or os.environ.get("SHALOM_PASS")

# 2要素認証コード（必要に応じて設定）
SHALOM_2FA_CODE = os.environ.get("SHALOM_2FA_CODE") or ""

# スプレッドシートID設定
MAIN_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY") or "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34"
FILTERED_SPREADSHEET_KEY = os.environ.get("FILTERED_SPREADSHEET_KEY") or "1cb8gOz19iN6IR7hXbPnlifDXMvcN91amOMG_raSQoTs"

# シートの gid 設定（既存の実際のシート）
GID_EA1100W = 910840628
GID_MP0002W = 1520113795
GID_COMBINED = 368650283
GID_FILTERED = 282241935

GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.environ.get("GCP_SA_KEY")

# 統合シートの指定カラム（並び順）
TARGET_COLUMNS = [
    "番号",
    "事業所名",
    "種別",
    "手続名",
    "被保険者名",
    "現在状況",
    "現在状況 日時",
    "データ元",
    "公文書保管完了",
    "最終更新日時"
]


# ==========================================
# 2. 社労夢からのデータスクレイピング (Playwright)
# ==========================================
def handle_login(page):
    """ログインページのロード待ち、ID/PASS入力、2要素認証待ちを行う"""
    print(f"[INFO] ログインページにアクセス: {SHALOM_LOGIN_URL}")
    page.goto(SHALOM_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")

    # 1. ログイン入力フォームが開くまでしっかり待機 (10秒)
    print("[INFO] ログインページのロードおよびフォーム表示を待機中 (10秒)...")
    page.wait_for_timeout(10000)

    try:
        page.wait_for_selector("input", timeout=20000)
        print("[INFO] ログイン入力フィールドを検出しました。")
    except Exception:
        print("[WARN] inputフィールドの明示的検出にタイムアウトしましたが処理を継続します。")

    # 2. ID / パスワードの入力
    form_filled = False
    for frame in page.frames:
        inputs = frame.locator("input[type='text'], input[type='password'], input:not([type='hidden'])")
        if inputs.count() >= 2:
            print("[INFO] ID / パスワードを入力中...")
            if SHALOM_COMPANY_ID:
                inputs.nth(0).fill(SHALOM_COMPANY_ID)
            if SHALOM_PASSWORD:
                inputs.nth(1).fill(SHALOM_PASSWORD)
            
            submit_btn = frame.locator("button, input[type='submit'], .btn-login, #loginBtn").first
            if submit_btn.count() > 0:
                submit_btn.click()
            else:
                frame.keyboard.press("Enter")
            form_filled = True
            break

    if not form_filled:
        print("[WARN] フォームを検出できなかったため、キーボードのEnterキー送信を試みます。")
        page.keyboard.press("Enter")

    # 3. ログイン押下後の画面遷移および2要素認証の待機 (15秒)
    print("[INFO] ログイン後の処理・画面遷移を待機中 (15秒)...")
    page.wait_for_timeout(15000)

    current_url = page.url
    page_content = page.content()
    print(f"[INFO] ログイン操作後の現在URL: {current_url}")

    # 2要素認証（OTP / 承認待ち）のチェック
    if "auth" in current_url.lower() or "two-factor" in current_url.lower() or "認証" in page_content or "ワンタイム" in page_content:
        print("[WARN] 2要素認証（または追加承認）画面が検出されました。")
        page.screenshot(path="login_2fa_detected.png")

        if SHALOM_2FA_CODE:
            print("[INFO] 設定された認証コードを入力します...")
            otp_input = page.locator("input[type='text'], input[type='number']").first
            if otp_input.count() > 0:
                otp_input.fill(SHALOM_2FA_CODE)
                page.keyboard.press("Enter")
                page.wait_for_timeout(10000)
        else:
            print("[WARN] 2要素認証の突破を試みるため、追加で 15 秒間待機します...")
            page.wait_for_timeout(15000)


def scrape_table_from_page(page, target_url, source_name):
    """指定されたURLへ遷移し、画面上のテーブルデータを抽出する"""
    print(f"[INFO] ページを開いています: {target_url}")
    
    page.goto(target_url, timeout=60000, wait_until="networkidle")
    current_url = page.url
    
    # ログイン画面へリダイレクトされた場合の判定
    if "login" in current_url.lower():
        print(f"[ERROR] {source_name} へのアクセス時にログイン画面へ戻されました。ログインが完了していません。")
        page.screenshot(path=f"error_{source_name}_redirect.png")
        return [], []

    print(f"[INFO] {source_name} のテーブル要素読み込みを待機中 (最大20秒)...")
    try:
        page.wait_for_selector("table, tr", timeout=20000)
    except Exception:
        print(f"[WARN] {source_name} でタイムアウト内に `table` タグが検出されませんでした。")
        page.screenshot(path=f"error_{source_name}_notable.png")

    page.wait_for_timeout(5000)

    # テーブルデータの収集
    raw_rows = []
    for frame in page.frames:
        try:
            rows = frame.evaluate('''() => {
                const trElements = Array.from(document.querySelectorAll('table tr'));
                return trElements.map(row => {
                    const cells = Array.from(row.querySelectorAll('th, td'));
                    return cells.map(cell => cell.innerText.trim());
                }).filter(row => row.length > 0);
            }''')
            if rows:
                raw_rows.extend(rows)
        except Exception:
            continue

    if not raw_rows:
        print(f"[WARN] {target_url} からテーブルデータが検出されませんでした。")
        return [], []

    headers = raw_rows[0]
    data_rows = raw_rows[1:] if len(raw_rows) > 1 else []
    print(f"[INFO] {source_name} から {len(data_rows)} 件のデータを取得しました。")
    return headers, data_rows


def fetch_all_shalom_data():
    print("[INFO] 社労夢へのリモートアクセスを開始します...")
    
    with sync_playwright() as p:
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
            # 1. ログイン処理
            handle_login(page)

            # 2. EA1100W データの取得
            ea_headers, ea_data = scrape_table_from_page(
                page, "https://4ever.shalom-house.jp/EA1100W", "EA1100W"
            )

            # 3. MP0002W データの取得
            mp_headers, mp_data = scrape_table_from_page(
                page, "https://4ever.shalom-house.jp/MP0002W", "MP0002W"
            )

            return {
                "EA1100W": {"headers": ea_headers, "rows": ea_data},
                "MP0002W": {"headers": mp_headers, "rows": mp_data}
            }

        except Exception as e:
            print(f"[ERROR] 社労夢データ取得中にエラーが発生しました: {e}")
            page.screenshot(path="fatal_error.png")
            raise
        finally:
            browser.close()


# ==========================================
# 3. データ整形・結合・フィルタリング処理
# ==========================================
def map_rows_to_target_columns(headers, rows, source_label):
    """取得したテーブルデータを指定10項目のフォーマットに変換する"""
    mapped_results = []
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    header_map = {name.strip(): idx for idx, name in enumerate(headers)}

    def get_val(row, col_name):
        idx = header_map.get(col_name)
        if idx is not None and idx < len(row):
            return row[idx]
        return ""

    for row in rows:
        formatted_row = [
            get_val(row, "番号"),
            get_val(row, "事業所名"),
            get_val(row, "種別"),
            get_val(row, "手続名"),
            get_val(row, "被保険者名"),
            get_val(row, "現在状況"),
            get_val(row, "現在状況 日時") or get_val(row, "現在状況日時"),
            source_label,  # データ元
            get_val(row, "公文書保管完了"),
            now_str        # 最終更新日時
        ]
        mapped_results.append(formatted_row)

    return mapped_results


def filter_completed_rows(combined_data_rows):
    """「現在状況」に“終了”を含み、かつ「公文書保管完了」に“済”を含む行を除外する"""
    filtered_rows = []
    for row in combined_data_rows:
        current_status = row[5] if len(row) > 5 else ""
        doc_storage = row[8] if len(row) > 8 else ""

        is_target_for_exclusion = ("終了" in current_status) and ("済" in doc_storage)

        if not is_target_for_exclusion:
            filtered_rows.append(row)

    print(f"[INFO] フィルタリング完了: {len(combined_data_rows)} 件 ➔ {len(filtered_rows)} 件に絞り込みました（除外: {len(combined_data_rows) - len(filtered_rows)} 件）。")
    return filtered_rows


# ==========================================
# 4. Google スプレッドシート書き込み処理
# ==========================================
def get_gspread_client():
    if GOOGLE_CREDENTIALS_JSON:
        import json
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return gspread.authorize(creds)
    return gspread.service_account()


def get_worksheet_by_gid(spreadsheet, target_gid):
    """指定された gid の既存シートを取得する"""
    target_gid_int = int(target_gid)
    
    try:
        # gspread の `get_worksheet_by_id` で直接既存シートを取得
        ws = spreadsheet.get_worksheet_by_id(target_gid_int)
        if ws:
            print(f"[INFO] gid ({target_gid}) に一致するシート '{ws.title}' を正常に取得しました。")
            return ws
    except Exception as e:
        print(f"[WARN] get_worksheet_by_id 取得時エラー: {e}")

    # フォールバック探索
    for ws in spreadsheet.worksheets():
        sheet_id = getattr(ws, 'id', getattr(ws, '_properties', {}).get('sheetId'))
        if str(sheet_id) == str(target_gid):
            print(f"[INFO] 検出されたシート: '{ws.title}' (gid: {sheet_id})")
            return ws

    raise ValueError(f"[ERROR] 指定された gid ({target_gid}) のシートが見つかりませんでした。スプレッドシートの権限（Googleサービスアカウントへの共有）をご確認ください。")


def write_to_sheet(sheet, headers, rows):
    sheet.clear()
    payload = [headers] + rows if headers else rows
    if payload:
        sheet.update('A1', payload)


def sync_to_spreadsheets(fetched_results):
    print("[INFO] スプレッドシートへのデータ同期を開始します...")
    gc = get_gspread_client()

    # --- メイン スプレッドシートの処理 ---
    main_sh = gc.open_by_key(MAIN_SPREADSHEET_KEY)

    # 1. EA1100W の流し込み (gid: 910840628)
    ea_info = fetched_results["EA1100W"]
    ws_ea = get_worksheet_by_gid(main_sh, GID_EA1100W)
    write_to_sheet(ws_ea, ea_info["headers"], ea_info["rows"])
    print("[INFO] EA1100W シートの更新が完了しました。")

    # 2. MP0002W の流し込み (gid: 1520113795)
    mp_info = fetched_results["MP0002W"]
    ws_mp = get_worksheet_by_gid(main_sh, GID_MP0002W)
    write_to_sheet(ws_mp, mp_info["headers"], mp_info["rows"])
    print("[INFO] MP0002W シートの更新が完了しました。")

    # 3. 指定10項目へフォーマット変換＆データ結合 (gid: 368650283)
    ea_mapped = map_rows_to_target_columns(ea_info["headers"], ea_info["rows"], "EA1100W")
    mp_mapped = map_rows_to_target_columns(mp_info["headers"], mp_info["rows"], "MP0002W")
    combined_rows = ea_mapped + mp_mapped

    ws_combined = get_worksheet_by_gid(main_sh, GID_COMBINED)
    write_to_sheet(ws_combined, TARGET_COLUMNS, combined_rows)
    print(f"[INFO] 統合シート（全 {len(combined_rows)} 件）の更新が完了しました。")

    # --- フィルタリング スプレッドシートの処理 (gid: 282241935) ---
    filtered_sh = gc.open_by_key(FILTERED_SPREADSHEET_KEY)
    ws_filtered = get_worksheet_by_gid(filtered_sh, GID_FILTERED)
    
    filtered_rows = filter_completed_rows(combined_rows)
    write_to_sheet(ws_filtered, TARGET_COLUMNS, filtered_rows)
    print("[INFO] フィルタリング後のシート更新が完了しました。")


# ==========================================
# 5. メイン実行処理
# ==========================================
def run():
    print("[INFO] ===== 社労夢 デイリー同期処理 開始 =====")
    try:
        data = fetch_all_shalom_data()
        sync_to_spreadsheets(data)
        print("[INFO] ===== 社労夢 デイリー同期処理 正常終了 =====")
    except Exception as e:
        print(f"[FATAL] 処理が異常終了しました: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
