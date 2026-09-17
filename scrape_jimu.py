# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import csv
import io
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

# スプレッドシートID（書き込み対象）
SPREADSHEET_KEY_TARGET = "14ykRH_2i39InbR3iBvUaYOClEcE0WZJ1NVeBXC1Ekmk"

# シートGID定義（事務組（社労夢）シート）
GID_JIMU = 1556116174

# URL定義
URL_DT0005W = "https://4ever.shalom-house.jp/DT0005W"


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


def select_option_by_text_or_value(page, selectors, target_text, option_name="ドロップダウン"):
    """ドロップダウンメニューからテキストまたは値で要素を選択"""
    start_time = time.time()
    while time.time() - start_time < 15:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.scroll_into_view_if_needed()
                try:
                    loc.select_option(label=target_text, timeout=2000)
                    return True
                except Exception:
                    pass
                options = loc.locator("option").all()
                for opt in options:
                    if target_text in opt.inner_text():
                        val = opt.get_attribute("value")
                        if val:
                            loc.select_option(value=val)
                            return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    print(f"[ERROR] {option_name} で '{target_text}' の選択に失敗しました。")
    return False


def parse_csv_bytes_all_columns(file_bytes):
    """ダウンロードしたCSVバイナリを全列解析"""
    text_content = None
    for encoding in ['cp932', 'shift_jis', 'utf-8-sig', 'utf-8']:
        try:
            text_content = file_bytes.decode(encoding)
            break
        except Exception:
            continue
            
    if not text_content:
        raise ValueError("CSVファイルの文字コード判定に失敗しました。")

    f = io.StringIO(text_content)
    reader = csv.reader(f)
    
    extracted_rows = []
    for row in reader:
        if any(c.strip() for c in row):
            extracted_rows.append(row)

    return extracted_rows


def update_worksheet_all_columns(doc, gid, raw_matrix):
    """指定GIDのシートを全クリアして全データをコピー"""
    try:
        ws = doc.get_worksheet_by_id(gid)
        if not ws:
            raise ValueError(f"GID: {gid} のシートが見つかりません。")
        
        # 全データ書き換えのためシート全体をクリア
        ws.clear()
        
        if raw_matrix:
            ws.update(range_name='A1', values=raw_matrix, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        print(f"[ERROR] GID: {gid} への書き込み中にエラーが発生しました: {e}")
        return False


def run():
    print("1. Googleスプレッドシートに接続中...")
    gc = get_gspread_client()
    doc_target = gc.open_by_key(SPREADSHEET_KEY_TARGET)

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
            ignore_https_errors=True,
            accept_downloads=True
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

        # --- ③ DT0005W 画面への移動と操作 ---
        print("\n6. 目的ページ（DT0005W）へ移動中...")
        page.wait_for_timeout(5000)
        page.goto(URL_DT0005W, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # 1. 「事務組合事業所情報」を選択
        print("   --> 「事務組合事業所情報」を選択中...")
        select_input1 = ["#input1", "select#input1"]
        select_option_by_text_or_value(page, select_input1, "事務組合事業所情報", "情報種別ドロップダウン")
        page.wait_for_timeout(2000)

        # 2. 「事務組合確認」を選択
        print("   --> 「事務組合確認」を選択中...")
        input3_selectors = ["#input3", "input#input3", "select#input3"]
        select_option_by_text_or_value(page, input3_selectors, "事務組合確認", "条件選択欄")
        page.wait_for_timeout(1500)

        # 3. 「全体」ラジオボタンを選択
        print("   --> 「全体」ラジオボタンを選択中...")
        rdo_all = [
            "#DT0005WCompanyOption_input1",
            "input#DT0005WCompanyOption_input1",
            "label:has-text('全体') input"
        ]
        click_button_element(page, rdo_all, "全体ラジオボタン", timeout_sec=10)
        page.wait_for_timeout(1500)

        # 4. 「出力」ボタンを押すと同時に「はい」ダイアログおよび「ダウンロード」を処理
        print("   --> 「出力」ボタンをクリック中...")
        btn_output_selector = "button:has-text('出力'):not([disabled])"
        
        download = None
        with page.expect_download(timeout=40000) as download_info:
            page.locator(btn_output_selector).first.click(force=True)
            page.wait_for_timeout(2000)

            # 「はい」ボタンが出たら押す
            print("   --> 「はい」ボタンをクリック中...")
            btn_yes_selectors = ["#MsgBoxBtnYes", "button#MsgBoxBtnYes", "button:has-text('はい')"]
            click_button_element(page, btn_yes_selectors, "はいボタン", timeout_sec=10)

        download = download_info.value
        print(f"   --> ダウンロード完了: {download.suggested_filename}")

        # 5. ファイルの読み込みと解析
        download_path = download.path()
        with open(download_path, "rb") as f:
            file_bytes = f.read()

        print("   --> CSVデータを解析中...")
        extracted_data = parse_csv_bytes_all_columns(file_bytes)
        print(f"   --> 抽出件数: {len(extracted_data)} 行")

        # 6. スプレッドシート（事務組（社労夢）シート）へ書き込み
        print(f"\n7. スプレッドシート（事務組（社労夢） gid: {GID_JIMU}）を更新中...")
        if update_worksheet_all_columns(doc_target, GID_JIMU, extracted_data):
            print(f"★【成功】「事務組（社労夢）」シートに {len(extracted_data)} 行のデータを正常にコピーしました！")

        browser.close()

    print("\nすべてのスクレイピングおよびシート書き込みプロセスが正常に完了しました。")


if __name__ == "__main__":
    run()
