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
SHALOM_COMPANY_ID = os.environ.get("SHALOM_COMPANY_ID") or os.environ.get("SHALOM_ID")
SHALOM_USER_ID = os.environ.get("SHALOM_USER_ID") or os.environ.get("SHALOM_ID")
SHALOM_PASSWORD = os.environ.get("SHALOM_PASSWORD") or os.environ.get("SHALOM_PASS")

# スプレッドシートID設定
MAIN_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY") or "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34"
FILTERED_SPREADSHEET_KEY = os.environ.get("FILTERED_SPREADSHEET_KEY") or "1cb8gOz19iN6IR7hXbPnlifDXMvcN91amOMG_raSQoTs"

# シートの gid 設定
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
def scrape_table_from_page(page, target_url, source_name):
    """指定されたURLへ遷移し、画面上のテーブルデータを抽出する"""
    print(f"[INFO] ページを開いています: {target_url}")
    page.goto(target_url, timeout=60000, wait_until="networkidle")
    
    # データのレンダリング待ち（5秒）
    page.wait_for_timeout(5000)

    # 画面上のテーブル行データを取得
    raw_rows = page.evaluate('''() => {
        const rows = Array.from(document.querySelectorAll('table tr'));
        return rows.map(row => {
            const cells = Array.from(row.querySelectorAll('th, td'));
            return cells.map(cell => cell.innerText.trim());
        }).filter(row => row.length > 0);
    }''')

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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # 1. ログイン処理
            print(f"[INFO] ログインページにアクセス: {SHALOM_LOGIN_URL}")
            page.goto(SHALOM_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # ログインフォームへの入力
            for frame in page.frames:
                inputs = frame.locator("input")
                if inputs.count() >= 2:
                    if SHALOM_COMPANY_ID:
                        inputs.nth(0).fill(SHALOM_COMPANY_ID)
                    if SHALOM_PASSWORD:
                        inputs.nth(1).fill(SHALOM_PASSWORD)
                    
                    submit_btn = frame.locator("button, input[type='submit']").first
                    if submit_btn.count() > 0:
                        submit_btn.click()
                    else:
                        frame.keyboard.press("Enter")
                    break
            
            # ログイン後の画面遷移・認証完了を長めに待機
            print("[INFO] ログイン完了待機中 (8秒)...")
            page.wait_for_timeout(8000)

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

    print(f"[INFO] フィルタリング完了: {len(combined_data_rows)} 件 ➔ {len(filtered_rows)} 件に絞り込みました。")
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


def get_worksheet_safe(spreadsheet, target_gid):
    """gidによる取得を試し、失敗した場合はインデックス/順序で安全に取得するフォールバック処理"""
    target_gid = int(target_gid)
    for ws in spreadsheet.worksheets():
        if ws.id == target_gid:
            return ws
    
    # gid が一致しない場合、シート順でフォールバック設定
    gid_index_map = {
        GID_EA1100W: 0,
        GID_MP0002W: 1,
        GID_COMBINED: 2,
        GID_FILTERED: 0
    }
    fallback_idx = gid_index_map.get(target_gid, 0)
    worksheets = spreadsheet.worksheets()
    if fallback_idx < len(worksheets):
        ws = worksheets[fallback_idx]
        print(f"[WARN] gid ({target_gid}) が見つからないため、{fallback_idx + 1}番目のシート '{ws.title}' を代わりに使用します。")
        return ws
    
    return worksheets[0]


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
    ws_ea = get_worksheet_safe(main_sh, GID_EA1100W)
    write_to_sheet(ws_ea, ea_info["headers"], ea_info["rows"])
    print("[INFO] EA1100W シートの更新が完了しました。")

    # 2. MP0002W の流し込み (gid: 1520113795)
    mp_info = fetched_results["MP0002W"]
    ws_mp = get_worksheet_safe(main_sh, GID_MP0002W)
    write_to_sheet(ws_mp, mp_info["headers"], mp_info["rows"])
    print("[INFO] MP0002W シートの更新が完了しました。")

    # 3. 指定10項目へフォーマット変換＆データ結合
    ea_mapped = map_rows_to_target_columns(ea_info["headers"], ea_info["rows"], "EA1100W")
    mp_mapped = map_rows_to_target_columns(mp_info["headers"], mp_info["rows"], "MP0002W")
    combined_rows = ea_mapped + mp_mapped

    ws_combined = get_worksheet_safe(main_sh, GID_COMBINED)
    write_to_sheet(ws_combined, TARGET_COLUMNS, combined_rows)
    print(f"[INFO] 統合シート（全 {len(combined_rows)} 件）の更新が完了しました。")

    # --- フィルタリング スプレッドシートの処理 ---
    # 4. 「終了」かつ「済」を除外して出力 (gid: 282241935)
    filtered_sh = gc.open_by_key(FILTERED_SPREADSHEET_KEY)
    ws_filtered = get_worksheet_safe(filtered_sh, GID_FILTERED)
    
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
