# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import pyotp
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# Windows環境でのログ文字化け防止
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ==========================================
# 環境変数からの設定値取得
# ==========================================
SHALOM_ID = os.environ.get("SHALOM_ID", "145371-01")
SHALOM_PASS = os.environ.get("SHALOM_PASS")
TOTP_SECRET = os.environ.get("TOTP_SECRET")

# Googleスプレッドシート設定
SPREADSHEET_KEY_1 = os.environ.get("SPREADSHEET_KEY_1", "14IbYjp3hizNBbb_h0wqu5H217U4UrU5-KKh0DX_QVtk")  # EA1100W用
SPREADSHEET_KEY_2 = os.environ.get("SPREADSHEET_KEY_2", "1TrGFfFzDzaPaxafgUeKHfsmhvqMs98-xSB-sl7LRrBw")  # MP0002W用
GCP_SA_KEY = os.environ.get("GCP_SA_KEY")


def get_gspread_client():
    """GCP Service Account Key から gspread クライアントを初期化"""
    if not GCP_SA_KEY:
        raise ValueError("[ERROR] GCP_SA_KEY 環境変数が設定されていません。")
    
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    sa_info = json.loads(GCP_SA_KEY)
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def get_main_table(target_context):
    """画面内（またはiframe内）で最も行数が多く、目視可能なメインテーブルを特定する"""
    tables = target_context.locator("table")
    max_rows = -1
    main_table = None

    for i in range(tables.count()):
        t = tables.nth(i)
        if t.is_visible():
            row_count = t.locator("tr").count()
            if row_count > max_rows:
                max_rows = row_count
                main_table = t
    return main_table


def collect_visible_rows_from_main_table(main_table, is_first_fetch=False):
    """メインテーブルのみから行データを抽出する"""
    extracted_rows = []
    if not main_table:
        return extracted_rows

    rows = main_table.locator("tr").all()
    for row in rows:
        th_count = row.locator("th").count()
        td_count = row.locator("td").count()
        
        # 2回目以降のスクロールでヘッダー（thのみ）があればスキップ
        if not is_first_fetch and th_count > 0 and td_count == 0:
            continue

        cells = row.locator("th, td").all_text_contents()
        clean_cells = [c.strip() for c in cells]

        if any(clean_cells):
            extracted_rows.append(clean_cells)

    return extracted_rows


def handle_popups_and_wait(page, url_name):
    """「はい」押下 ➜ 30秒待機 ➜ 「OK」押下の共通ポップアップ処理"""
    # 1つ目のポップアップ（「はい」ボタン）
    try:
        confirm_btn = page.locator("button:has-text('はい'), input[value='画面を閉じる'], input[value='はい'], a:has-text('はい')").first
        confirm_btn.wait_for(timeout=5000)
        confirm_btn.click()
        print(f"   --> [{url_name}] ポップアップで『はい』をクリックしました！")
    except Exception:
        print(f"   --> [{url_name}] 1つ目のポップアップ（はいボタン）は表示されませんでした。")

    # 更新処理待機 (30秒)
    print(f"   --> [{url_name}] 画面の更新・データ処理中（30秒間待機）...")
    page.wait_for_timeout(30000)

    # 2つ目のポップアップ（「OK」ボタン）
    try:
        ok_btn = page.locator("button:has-text('OK'), input[value='OK'], a:has-text('OK'), button:has-text('確認'), input[value='確認']").first
        ok_btn.wait_for(state="visible", timeout=10000)
        ok_btn.click()
        print(f"   --> [{url_name}] ポップアップで『OK』をクリックしました！")
        page.wait_for_timeout(3000)
    except Exception:
        print(f"   --> [{url_name}] 『OK』ボタンは見つかりませんでした。次の処理に進みます。")


def scrape_table_data(page, url_name):
    """メインテーブルのみを特定してスクロール＆データ抽出を行う汎用関数"""
    print(f"   --> [{url_name}] テーブル内部へ直接スクロール操作を実行中...")
    scraped_data = []

    # コンテキスト（メインページまたは iframe）を特定
    target_context = page
    if page.locator("table").count() == 0:
        for frame in page.frames:
            if frame.locator("table").count() > 0:
                target_context = frame
                print(f"   --> [{url_name}] iframe 内のテーブル領域を検出しました。")
                break

    # 一番行数の多いメインテーブル要素を特定
    main_table = get_main_table(target_context)

    if main_table and main_table.count() > 0:
        try:
            main_table.click(position={"x": 50, "y": 50}, timeout=3000)
        except Exception:
            pass

    last_count = 0
    same_count_limit = 0

    for step in range(35):
        is_first = (step == 0)
        main_table = get_main_table(target_context)
        current_rows = collect_visible_rows_from_main_table(main_table, is_first_fetch=is_first)

        header_row = scraped_data[0] if len(scraped_data) > 0 else None

        for row in current_rows:
            if header_row and row == header_row:
                continue
            if row not in scraped_data:
                scraped_data.append(row)

        print(f"   --> [{url_name} - {step + 1}回目] 取得件数: {len(scraped_data)} 行")

        if len(scraped_data) == last_count:
            same_count_limit += 1
            if same_count_limit >= 3:
                print(f"   --> [{url_name}] これ以上新しいデータがないためスクロール完了とみなします。")
                break
        else:
            same_count_limit = 0

        last_count = len(scraped_data)

        # メインテーブルのスクロールバーを操作
        target_context.evaluate("""
            () => {
                const allDivs = document.querySelectorAll('div, section, main, tbody');
                for (const el of allDivs) {
                    if (el.scrollHeight > el.clientHeight && el.clientHeight > 100) {
                        el.scrollTop += 400;
                    }
                }
            }
        """)

        page.keyboard.press("PageDown")
        page.wait_for_timeout(1000)

    return scraped_data


def run():
    print("1. Googleスプレッドシートに接続中...")
    gc = get_gspread_client()
    
    # スプレッドシート1 (EA1100W用)
    sheet1 = gc.open_by_key(SPREADSHEET_KEY_1).sheet1
    # スプレッドシート2 (MP0002W用)
    sheet2 = gc.open_by_key(SPREADSHEET_KEY_2).sheet1

    print("2. 自動ブラウザを起動して社労夢にアクセス中...")
    with sync_playwright() as p:
        # Headlessモードで起動 (CI環境用)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # --- ① ログイン画面を開く ---
        page.goto("https://4ever.shalom-house.jp/login")
        page.wait_for_timeout(3000)

        # ID入力
        print(f"1. IDを入力中... ({SHALOM_ID})")
        id_field = page.locator("input[type='text'], input:not([type='password']):not([type='hidden'])").first
        id_field.click()
        id_field.press("Control+A")
        id_field.press("Backspace")
        id_field.type(SHALOM_ID, delay=50)
        page.wait_for_timeout(1000)

        # パスワード入力
        print("2. パスワードを入力中...")
        pass_field = page.locator("input[type='password']").first
        pass_field.click()
        pass_field.press("Control+A")
        pass_field.press("Backspace")
        pass_field.type(SHALOM_PASS, delay=50)
        page.wait_for_timeout(1000)

        # ログインボタンクリック
        print("3. ログインボタンをクリックします...")
        page.locator("button[type='submit'], input[type='submit'], button:has-text('ログイン')").first.click()

        # --- ② 二要素認証（2FA） ---
        print("4. 二要素認証（2FA）画面の待機中...")
        page.wait_for_selector("input[type='tel'], input[type='number'], input[name*='otp'], input[name*='code'], input", timeout=15000)
        page.wait_for_timeout(1000)

        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()
        print(f"   --> 生成されたワンタイムコード: {code}")

        otp_field = page.locator("input[type='tel'], input[type='number'], input[name*='otp'], input[name*='code']").first
        otp_field.click()
        otp_field.fill(code)
        page.wait_for_timeout(500)

        print("5. 認証ボタンをクリックして送信中...")
        auth_btn = page.locator("button:has-text('認証'), input[value='認証'], button:has-text('送信'), button[type='submit'], input[type='submit']").first
        
        if auth_btn.is_visible():
            auth_btn.click()
        else:
            otp_field.press("Enter")

        # --- ③ 1つ目のページ（EA1100W）の処理 ---
        print("\n6. 1つ目の目的ページ（EA1100W）へ移動中...")
        page.wait_for_timeout(4000)
        page.goto("https://4ever.shalom-house.jp/EA1100W")

        # ポップアップ＆30秒待機処理 (EA1100W)
        handle_popups_and_wait(page, "EA1100W")

        # EA1100W のデータ取得 ＆ スプレッドシート1へ保存
        ea_data = scrape_table_data(page, "EA1100W")
        
        print("\n7. スプレッドシート1（EA1100W用）を更新中...")
        sheet1.clear()
        if ea_data:
            sheet1.update('A1', ea_data)
            print(f"★【成功】EA1100W のデータ {len(ea_data)} 行を 1つ目のスプレッドシートに書き込みました！")

        # --- ④ 2つ目のページ（MP0002W）の処理 ---
        print("\n8. 2つ目の目的ページ（MP0002W）へ移動中...")
        page.goto("https://4ever.shalom-house.jp/MP0002W")
        page.wait_for_timeout(4000)

        # ポップアップ＆30秒待機処理 (MP0002W)
        handle_popups_and_wait(page, "MP0002W")

        # MP0002W のデータ取得 ＆ スプレッドシート2へ保存
        mp_data = scrape_table_data(page, "MP0002W")

        print("\n9. スプレッドシート2（MP0002W用）を更新中...")
        sheet2.clear()
        if mp_data:
            sheet2.update('A1', mp_data)
            print(f"★【成功】MP0002W のデータ {len(mp_data)} 行を 2つ目のスプレッドシートに書き込みました！")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    run()
