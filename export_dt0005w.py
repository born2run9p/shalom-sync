# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import pyotp
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 環境変数・定数設定
SHALOM_ID = os.environ.get("SHALOM_ID", "145371-01")
SHALOM_PASS = os.environ.get("SHALOM_PASS")
TOTP_SECRET = os.environ.get("TOTP_SECRET")
GCP_SA_KEY = os.environ.get("GCP_SA_KEY")

SPREADSHEET_KEY = "14ykRH_2i39InbR3iBvUaYOClEcE0WZJ1NVeBXC1Ekmk"
TARGET_GID = 201499241

def get_gspread_client():
    if not GCP_SA_KEY:
        raise ValueError("[ERROR] GCP_SA_KEY が設定されていません。")
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(json.loads(GCP_SA_KEY), scopes=scopes)
    return gspread.authorize(creds)

def find_locator_in_page_or_frames(page, selectors):
    for selector in selectors:
        loc = page.locator(selector).first
        if loc.count() > 0:
            return loc
        for frame in page.frames:
            f_loc = frame.locator(selector).first
            if f_loc.count() > 0:
                return f_loc
    return None

def fill_input_field(page, selectors, value, name="入力欄"):
    start = time.time()
    while time.time() - start < 30:
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
    
    print(f"[ERROR] {name} が見つかりませんでした。")
    print(f"        現在のURL: {page.url}")
    print(f"        ページタイトル: {page.title()}")
    raise TimeoutError(f"{name} の取得に失敗しました。")

def click_button_element(page, selectors, name="ボタン"):
    start = time.time()
    while time.time() - start < 15:
        loc = find_locator_in_page_or_frames(page, selectors)
        if loc:
            try:
                loc.click()
                return True
            except Exception:
                pass
        page.wait_for_timeout(1000)
    print(f"   --> [{name}] のクリック対象が見つからないためスキップします。")
    return False

def run():
    print("1. Googleスプレッドシートへ接続...")
    gc = get_gspread_client()
    doc = gc.open_by_key(SPREADSHEET_KEY)

    print("2. ブラウザ起動＆ログイン開始...")
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

        # 自動化フラグの隠蔽
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # ログイン処理
        login_url = "https://4ever.shalom-house.jp/login"
        print(f"URLにアクセス中: {login_url}")
        page.goto(login_url, wait_until="load")
        page.wait_for_timeout(4000)

        id_selectors = [
            "input[name='userId']", "input[name='id']", "input[name='loginId']",
            "input[placeholder*='ID']", "input[placeholder*='ユーザー']",
            "input[type='text']", "input:not([type='password']):not([type='hidden'])"
        ]
        print(f"1. IDを入力中... ({SHALOM_ID})")
        fill_input_field(page, id_selectors, SHALOM_ID, "ID入力欄")
        page.wait_for_timeout(1000)

        pass_selectors = [
            "input[type='password']", "input[name='password']", "input[name='pass']"
        ]
        print("2. パスワードを入力中...")
        fill_input_field(page, pass_selectors, SHALOM_PASS, "パスワード入力欄")
        page.wait_for_timeout(1000)

        login_btn_selectors = [
            "button[type='submit']", "input[type='submit']",
            "button:has-text('ログイン')", "input[value='ログイン']", "a:has-text('ログイン')"
        ]
        print("3. ログインボタンをクリックします...")
        click_button_element(page, login_btn_selectors, "ログインボタン")

        # 2FA
        print("4. 二要素認証（2FA）処理...")
        page.wait_for_timeout(4000)
        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()

        otp_selectors = [
            "input[type='tel']", "input[type='number']",
            "input[name*='otp']", "input[name*='code']",
            "input[placeholder*='コード']", "input[placeholder*='認証']"
        ]

        try:
            fill_input_field(page, otp_selectors, code, "OTP入力欄")
            page.wait_for_timeout(500)
            auth_btn_selectors = [
                "button:has-text('認証')", "input[value='認証']",
                "button:has-text('送信')", "button[type='submit']", "input[type='submit']"
            ]
            click_button_element(page, auth_btn_selectors, "認証ボタン")
        except Exception as e:
            print(f"   --> 2FA処理スキップまたは完了: {e}")

        # 目的ページへ遷移
        print("\n5. DT0005W ページへ移動中...")
        page.wait_for_timeout(4000)
        page.goto("https://4ever.shalom-house.jp/DT0005W", wait_until="load")
        page.wait_for_timeout(4000)

        # プルダウン選択（被保険者基本情報 & 全従業員）
        print("6. プルダウン項目の選択中...")
        page.locator("#input1").select_option(label="被保険者基本情報")
        page.wait_for_timeout(1500)
        page.locator("#input3").select_option(label="全従業員")
        page.wait_for_timeout(1500)

        # CSVダウンロード実行
        print("7. 出力実行およびCSVダウンロード待機...")
        with page.expect_download(timeout=60000) as download_info:
            click_button_element(page, ["button:has-text('出力')", "#input1_span ~ button"], "出力ボタン")
            page.wait_for_timeout(1500)
            
            popup_selectors = ["button:has-text('はい')", "button:has-text('はい(Y)')", "input[value*='はい']"]
            click_button_element(page, popup_selectors, "はいボタン")

        download = download_info.value
        csv_path = download.path()
        print(f"   --> CSVダウンロード完了: {csv_path}")

        browser.close()

    # CSV読み込み & A~G列の抽出
    print("8. CSVデータの整形処理中...")
    try:
        df = pd.read_csv(csv_path, encoding='cp932')
    except Exception:
        df = pd.read_csv(csv_path, encoding='utf-8')

    df_sub = df.iloc[:, :7]
    matrix = [df_sub.columns.tolist()] + df_sub.fillna("").values.tolist()

    # スプレッドシート更新
    print("9. スプレッドシート更新中...")
    ws = doc.get_worksheet_by_id(TARGET_GID)
    ws.clear()
    ws.update(range_name='A1', values=matrix, value_input_option='USER_ENTERED')
    print("★【成功】A〜G列への転記が正常に完了しました！")

if __name__ == "__main__":
    run()
