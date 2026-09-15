# -*- coding: utf-8 -*-
import os
import sys
import json
import time
from datetime import datetime
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
GCP_SA_KEY = os.environ.get("GCP_SA_KEY")

# スプレッドシートID
SPREADSHEET_KEY_1 = "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34"

# シートGID定義
GID_EA1100W = 910840628
GID_MP0002W = 1520113795
GID_LAST_UPDATE = 1090515274  # 最終更新シートのGID

# URL定義
URL_EA1100W = "https://4ever.shalom-house.jp/EA1100W"
URL_MP0002W = "https://4ever.shalom-house.jp/MP0002W"


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
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            pass
        
        for frame in page.frames:
            try:
                f_loc = frame.locator(selector).first
                if f_loc.count() > 0 and f_loc.is_visible():
                    return f_loc
            except Exception:
                pass
    return None


def fill_input_field(page, selectors, value, field_name="入力欄"):
    """要素が存在するまで待機して値を入力"""
    start_time = time.time()
    while time.time() - start_time < 30:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.wait_for(state="visible", timeout=3000)
                loc.click(force=True)
                loc.fill("")
                loc.type(value, delay=50)
                return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    
    print(f"[ERROR] {field_name} が見つかりませんでした。")
    raise TimeoutError(f"{field_name} の取得に失敗しました。")


def click_button_element(page, selectors, button_name="ボタン", timeout_sec=10):
    """ボタン要素を検索してクリック (force=True 対応)"""
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                try:
                    loc.click(timeout=2000)
                except Exception:
                    loc.click(force=True)
                return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    return False


def set_checkbox_checked(page, selectors, checkbox_name="チェックボックス"):
    """チェックボックス要素を確実にオン（チェック状態）にする"""
    start_time = time.time()
    while time.time() - start_time < 15:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                if not loc.is_checked():
                    try:
                        loc.check(force=True, timeout=2000)
                    except Exception:
                        loc.click(force=True)
                return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    print(f"   --> [{checkbox_name}] の設定に失敗しました。")
    return False


def handle_ea1100w_dialog_sequence(page):
    """整理されたフローに基づく EA1100W 遷移時のダイアログ連鎖処理"""
    print("   --> EA1100W アクセス直後のダイアログ処理を開始します...")
    ok_selectors = ["#MsgBoxBtnOK", "button#MsgBoxBtnOK", "button:has-text('OK')"]
    yes_selectors = ["#MsgBoxBtnYes", "button#MsgBoxBtnYes", "button:has-text('はい')"]

    has_initial_ok = click_button_element(page, ok_selectors, "初回 OKボタン", timeout_sec=3)

    if has_initial_ok:
        print("   --> 【分岐: パターンA】メッセージボックスが表示されていました。")
        print("       [1/4] 1つ目の「OK」をクリックしました。")
        page.wait_for_timeout(2000)

        if click_button_element(page, yes_selectors, "はい(Y)ボタン", timeout_sec=10):
            print("       [2/4] 「はい(Y)」をクリックしました。データ読み込み中...")
        
        page.wait_for_timeout(15000)

        if click_button_element(page, ok_selectors, "2回目の OKボタン", timeout_sec=15):
            print("       [3/4] 「OK」をクリックしました。")
            page.wait_for_timeout(2000)

        if click_button_element(page, ok_selectors, "3回目の OKボタン", timeout_sec=10):
            print("       [4/4] 「OK」をクリックしました。")
            page.wait_for_timeout(2000)

    else:
        print("   --> 【分岐: パターンB】メッセージボックス（OK）は出ていませんでした。")
        if click_button_element(page, yes_selectors, "はい(Y)ボタン", timeout_sec=10):
            print("       [1/2] 「はい(Y)」をクリックしました。データ読み込み中...")
        
        page.wait_for_timeout(15000)

        if click_button_element(page, ok_selectors, "OKボタン", timeout_sec=15):
            print("       [2/2] 「OK」をクリックしました。")
            page.wait_for_timeout(2000)


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
    """MP0002W 用の共通ポップアップ処理"""
    popup_selectors = ["#MsgBoxBtnYes", "button:has-text('はい')", "input[value='はい']"]
    if click_button_element(page, popup_selectors, f"{url_name} - はいボタン", timeout_sec=10):
        print(f"   --> [{url_name}] ポップアップで『はい』をクリックしました！")

    print(f"   --> [{url_name}] 画面の更新・データ処理中（30秒間待機）...")
    page.wait_for_timeout(30000)

    ok_selectors = ["#MsgBoxBtnOK", "button:has-text('OK')", "input[value='OK']"]
    if click_button_element(page, ok_selectors, f"{url_name} - OKボタン", timeout_sec=15):
        print(f"   --> [{url_name}] ポップアップで『OK』をクリックしました！")
        page.wait_for_timeout(3000)


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


def update_worksheet_by_gid(doc, gid, raw_matrix):
    """GIDから指定ワークシートを取得し、データを更新する"""
    try:
        ws = doc.get_worksheet_by_id(gid)
        if not ws:
            raise ValueError(f"GID: {gid} のシートが見つかりません。")
        ws.clear()
        if raw_matrix:
            ws.update(range_name='A1', values=raw_matrix, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        print(f"[ERROR] GID: {gid} への更新中にエラーが発生しました: {e}")
        return False


def update_last_updated_timestamp(doc, gid):
    """指定GID（最終更新シート）の A1 セルに現在日時を書き込む"""
    try:
        ws = doc.get_worksheet_by_id(gid)
        if not ws:
            print(f"[WARNING] 最終更新シート (GID: {gid}) が見つかりませんでした。")
            return False
        
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        ws.update(range_name='A1', values=[[now_str]], value_input_option='USER_ENTERED')
        print(f"★【最終更新日時記録】「最終更新」シートのA1に '{now_str}' を書き込みました。")
        return True
    except Exception as e:
        print(f"[ERROR] 最終更新日時の記録中にエラーが発生しました: {e}")
        return False


def run():
    print("1. Googleスプレッドシートに接続中...")
    gc = get_gspread_client()
    doc1 = gc.open_by_key(SPREADSHEET_KEY_1)

    print("2. 自動ブラウザを起動して社労夢にアクセス中...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True
        )
        page = context.new_page()

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

        # ID入力
        id_selectors = [
            "input[name='userId']", "input[name='id']", "input[name='loginId']",
            "input[placeholder*='ID']", "input[placeholder*='ユーザー']",
            "input[type='text']", "input:not([type='password']):not([type='hidden'])"
        ]
        print(f"1. IDを入力中... ({SHALOM_ID})")
        fill_input_field(page, id_selectors, SHALOM_ID, "ID入力欄")
        page.wait_for_timeout(1000)

        # パスワード入力
        pass_selectors = [
            "input[type='password']", "input[name='password']", "input[name='pass']"
        ]
        print("2. パスワードを入力中...")
        fill_input_field(page, pass_selectors, SHALOM_PASS, "パスワード入力欄")
        page.wait_for_timeout(1000)

        # ログインボタンクリック
        print("3. ログインボタンをクリックします...")
        login_btn_selectors = [
            "button[type='submit']", "input[type='submit']",
            "button:has-text('ログイン')", "input[value='ログイン']", "a:has-text('ログイン')"
        ]
        click_button_element(page, login_btn_selectors, "ログインボタン")

        # --- ② 二要素認証（2FA） ---
        print("4. 二要素認証（2FA）画面の待機中...")
        page.wait_for_timeout(4000)

        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()
        print(f"   --> 生成されたワンタイムコード: {code}")

        otp_selectors = [
            "input[type='tel']", "input[type='number']",
            "input[name*='otp']", "input[name*='code']",
            "input[placeholder*='コード']", "input[placeholder*='認証']"
        ]

        try:
            fill_input_field(page, otp_selectors, code, "OTP入力欄")
            page.wait_for_timeout(500)

            print("5. 認証ボタンをクリックして送信中...")
            auth_btn_selectors = [
                "button:has-text('認証')", "input[value='認証']",
                "button:has-text('送信')", "button[type='submit']", "input[type='submit']"
            ]
            click_button_element(page, auth_btn_selectors, "認証ボタン")
        except Exception as e:
            print(f"   --> 2FA画面をスキップまたは処理成功: {e}")

        # --- ③ 1つ目のページ（EA1100W）の処理 ---
        print("\n6. 1つ目の目的ページ（EA1100W）へ移動中...")
        page.wait_for_timeout(5000)
        page.goto(URL_EA1100W, wait_until="networkidle")
        page.wait_for_timeout(5000)

        handle_ea1100w_dialog_sequence(page)

        toggle_selectors = ["#toggle", "a#toggle", "a:has-text('検索エリアをひらく')"]
        if click_button_element(page, toggle_selectors, "検索エリアをひらく", timeout_sec=3):
            print("   --> 『検索エリアをひらく』をクリックしました。")
            page.wait_for_timeout(1500)

        print("   --> [EA1100W] 『クリア(R)』ボタンをクリック中...")
        clear_btn_selectors = ["#input33", "button#input33", "button:has-text('クリア')"]
        click_button_element(page, clear_btn_selectors, "クリアボタン", timeout_sec=10)
        page.wait_for_timeout(3000)

        print("   --> [EA1100W] 『手続終了』(input23) チェックボックスをオンに設定中...")
        chk_end_selectors = ["#input23", "input[type='checkbox']#input23"]
        set_checkbox_checked(page, chk_end_selectors, "手続終了チェックボックス")

        print("   --> [EA1100W] 『エラー』(input24) チェックボックスをオンに設定中...")
        chk_err_selectors = ["#input24", "input[type='checkbox']#input24"]
        set_checkbox_checked(page, chk_err_selectors, "エラーチェックボックス")

        page.wait_for_timeout(2000)

        print("   --> [EA1100W] 『検索(F)』ボタンをクリック中...")
        search_btn_selectors = ["#input34", "button#input34", "button:has-text('検索')"]
        click_button_element(page, search_btn_selectors, "検索ボタン", timeout_sec=10)

        print("   --> 検索完了待機中 (6秒間)...")
        page.wait_for_timeout(6000)

        ok_selectors = ["#MsgBoxBtnOK", "button#MsgBoxBtnOK", "button:has-text('OK')"]
        if click_button_element(page, ok_selectors, "検索後 OKボタン", timeout_sec=5):
            print("   --> 検索後の『OK』ボタンをクリックしました。")
            page.wait_for_timeout(2000)

        ea_data = scrape_table_data(page, "EA1100W")

        print(f"\n7. スプレッドシート（EA1100W用 gid: {GID_EA1100W}）を更新中...")
        if update_worksheet_by_gid(doc1, GID_EA1100W, ea_data):
            print(f"★【成功】EA1100W のデータ {len(ea_data)} 行を書き込みました！")
            # --- 電子申請（EA1100W）のデータ書き込みに成功したため、「最終更新」シートのA1に現在日時を書き込む ---
            update_last_updated_timestamp(doc1, GID_LAST_UPDATE)

        # --- ④ 2つ目のページ（MP0002W）の処理 ---
        print("\n8. 2つ目の目的ページ（MP0002W）へ移動中...")
        page.goto(URL_MP0002W, wait_until="load")
        page.wait_for_timeout(5000)

        handle_popups_and_wait(page, "MP0002W")
        mp_data = scrape_table_data(page, "MP0002W")

        print(f"\n9. スプレッドシート（MP0002W用 gid: {GID_MP0002W}）を更新中...")
        if update_worksheet_by_gid(doc1, GID_MP0002W, mp_data):
            print(f"★【成功】MP0002W のデータ {len(mp_data)} 行を書き込みました！")

        browser.close()

    print("\nすべてのスクレイピングおよびシート書き込みプロセスが正常に完了しました。")


if __name__ == "__main__":
    run()
