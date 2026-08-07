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


def find_locator_in_page_or_frames(page, selectors):
    """メインページおよびすべてのiframe内から対象ロケータを探索"""
    for selector in selectors:
        loc = page.locator(selector).first
        if loc.count() > 0:
            return loc
        
        for frame in page.frames:
            f_loc = frame.locator(selector).first
            if f_loc.count() > 0:
                return f_loc
    return None


def fill_input_field(page, selectors, value, field_name="入力欄"):
    """要素が存在するまで待機して値を入力"""
    start_time = time.time()
    while time.time() - start_time < 30:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.wait_for(state="attached", timeout=3000)
                loc.click()
                loc.fill("")
                loc.type(value, delay=50)
                return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    
    # 失敗時のデバッグ情報出力
    print(f"[ERROR] {field_name} が見つかりませんでした。")
    print(f"        現在のURL: {page.url}")
    print(f"        ページタイトル: {page.title()}")
    raise TimeoutError(f"{field_name} の取得に失敗しました。")


def click_button_element(page, selectors, button_name="ボタン"):
    """ボタン要素を検索してクリック"""
    start_time = time.time()
    while time.time() - start_time < 15:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.click()
                return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    print(f"   --> [{button_name}] のクリック対象が見つからないためスキップします。")
    return False


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
        
        if not is_first_fetch and th_count > 0 and td_count == 0:
            continue

        cells = row.locator("th, td").all_text_contents()
        clean_cells = [c.strip() for c in cells]

        if any(clean_cells):
            extracted_rows.append(clean_cells)

    return extracted_rows


def handle_popups_and_wait(page, url_name):
    """「はい」押下 ➜ 30秒待機 ➜ 「OK」押下の共通ポップアップ処理"""
    popup_selectors = ["button:has-text('はい')", "input[value='画面を閉じる']", "input[value='はい']", "a:has-text('はい')"]
    if click_button_element(page, popup_selectors, f"{url_name} - はいボタン"):
        print(f"   --> [{url_name}] ポップアップで『はい』をクリックしました！")
    else:
        print(f"   --> [{url_name}] 1つ目のポップアップ（はいボタン）は表示されませんでした。")

    print(f"   --> [{url_name}] 画面の更新・データ処理中（30秒間待機）...")
    page.wait_for_timeout(30000)

    ok_selectors = ["button:has-text('OK')", "input[value='OK']", "a:has-text('OK')", "button:has-text('確認')", "input[value='確認']"]
    if click_button_element(page, ok_selectors, f"{url_name} - OKボタン"):
        print(f"   --> [{url_name}] ポップアップで『OK』をクリックしました！")
        page.wait_for_timeout(3000)
    else:
        print(f"   --> [{url_name}] 『OK』ボタンは見つかりませんでした。次の処理に進みます。")


def scrape_table_data(page, url_name):
    """メインテーブルのみを特定してスクロール＆データ抽出を行う汎用関数"""
    print(f"   --> [{url_name}] テーブル内部へ直接スクロール操作を実行中...")
    scraped_data = []

    target_context = page
    if page.locator("table").count() == 0:
        for frame in page.frames:
            if frame.locator("table").count() > 0:
                target_context = frame
                print(f"   --> [{url_name}] iframe 内のテーブル領域を検出しました。")
                break

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
    
    sheet1 = gc.open_by_key(SPREADSHEET_KEY_1).sheet1
    sheet2 = gc.open_by_key(SPREADSHEET_KEY_2).sheet1

    print("2. 自動ブラウザを起動して社労夢にアクセス中...")
    with sync_playwright() as p:
        # アンチボット検知回避オプションを追加して起動
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ]
        )
        
        # 実機PCのUser-Agentとビューポートサイズを設定
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True
        )
        page = context.new_page()

        # webdriver 検出フラグを偽装解除
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # --- ① ログイン画面を開く ---
        login_url = "https://4ever.shalom-house.jp/login"
        print(f"URLにアクセス中: {login_url}")
        page.goto(login_url, wait_until="load")
        page.wait_for_timeout(3000)

        print(f"   --> 読み込み完了時URL: {page.url}")
        print(f"   --> ページタイトル: {page.title()}")

        # ID入力
        id_selectors = [
            "input[name='userId']",
            "input[name='id']",
            "input[name='loginId']",
            "input[placeholder*='ID']",
            "input[placeholder*='ユーザー']",
            "input[type='text']",
            "input:not([type='password']):not([type='hidden'])"
        ]
        print(f"1. IDを入力中... ({SHALOM_ID})")
        fill_input_field(page, id_selectors, SHALOM_ID, "ID入力欄")
        page.wait_for_timeout(1000)

        # パスワード入力
        pass_selectors = [
            "input[type='password']",
            "input[name='password']",
            "input[name='pass']"
        ]
        print("2. パスワードを入力中...")
        fill_input_field(page, pass_selectors, SHALOM_PASS, "パスワード入力欄")
        page.wait_for_timeout(1000)

        # ログインボタンクリック
        print("3. ログインボタンをクリックします...")
        login_btn_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('ログイン')",
            "input[value='ログイン']",
            "a:has-text('ログイン')"
        ]
        click_button_element(page, login_btn_selectors, "ログインボタン")

        # --- ② 二要素認証（2FA） ---
        print("4. 二要素認証（2FA）画面の待機中...")
        page.wait_for_timeout(4000)

        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()
        print(f"   --> 生成されたワンタイムコード: {code}")

        otp_selectors = [
            "input[type='tel']",
            "input[type='number']",
            "input[name*='otp']",
            "input[name*='code']",
            "input[placeholder*='コード']",
            "input[placeholder*='認証']"
        ]

        try:
            fill_input_field(page, otp_selectors, code, "OTP入力欄")
            page.wait_for_timeout(500)

            print("5. 認証ボタンをクリックして送信中...")
            auth_btn_selectors = [
                "button:has-text('認証')",
                "input[value='認証']",
                "button:has-text('送信')",
                "button[type='submit']",
                "input[type='submit']"
            ]
            click_button_element(page, auth_btn_selectors, "認証ボタン")
        except Exception as e:
            print(f"   --> 2FA画面をスキップまたは処理成功: {e}")

        # --- ③ 1つ目のページ（EA1100W）の処理 ---
        print("\n6. 1つ目の目的ページ（EA1100W）へ移動中...")
        page.wait_for_timeout(4000)
        page.goto("https://4ever.shalom-house.jp/EA1100W", wait_until="load")

        handle_popups_and_wait(page, "EA1100W")

        ea_data = scrape_table_data(page, "EA1100W")
        
        print("\n7. スプレッドシート1（EA1100W用）を更新中...")
        sheet1.clear()
        if ea_data:
            sheet1.update('A1', ea_data)
            print(f"★【成功】EA1100W のデータ {len(ea_data)} 行を 1つ目のスプレッドシートに書き込みました！")

        # --- ④ 2つ目のページ（MP0002W）の処理 ---
        print("\n8. 2つ目の目的ページ（MP0002W）へ移動中...")
        page.goto("https://4ever.shalom-house.jp/MP0002W", wait_until="load")
        page.wait_for_timeout(4000)

        handle_popups_and_wait(page, "MP0002W")

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
