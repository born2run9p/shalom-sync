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
    raise TimeoutError(f"{name}の取得に失敗しました。")

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
    return False

def run():
    print("1. Googleスプレッドシートへ接続...")
    gc = get_gspread_client()
    doc = gc.open_by_key(SPREADSHEET_KEY)

    print("2. ブラウザ起動＆ログイン開始...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # ログイン処理
        page.goto("https://4ever.shalom-house.jp/login", wait_until="load")
        page.wait_for_timeout(3000)

        fill_input_field(page, ["input[name='userId']", "input[type='text']"], SHALOM_ID, "ID")
        page.wait_for_timeout(1000)
        fill_input_field(page, ["input[type='password']"], SHALOM_PASS, "パスワード")
        page.wait_for_timeout(1000)
        click_button_element(page, ["button[type='submit']", "button:has-text('ログイン')"], "ログイン")

        # 2FA
        page.wait_for_timeout(4000)
        totp = pyotp.TOTP(TOTP_SECRET)
        try:
            fill_input_field(page, ["input[type='tel']", "input[type='number']"], totp.now(), "2FA")
            page.wait_for_timeout(500)
            click_button_element(page, ["button:has-text('認証')", "button[type='submit']"], "認証")
        except Exception:
            pass

        # 目的ページへ遷移
        print("3. DT0005W ページへ移動中...")
        page.wait_for_timeout(4000)
        page.goto("https://4ever.shalom-house.jp/DT0005W", wait_until="load")
        page.wait_for_timeout(3000)

        # プルダウン選択（被保険者基本情報 & 全従業員）
        print("4. プルダウン項目の選択中...")
        page.locator("#input1").select_option(label="被保険者基本情報")
        page.wait_for_timeout(1000)
        page.locator("#input3").select_option(label="全従業員")
        page.wait_for_timeout(1000)

        # CSVダウンロード実行
        print("5. 出力実行およびCSVダウンロード待機...")
        with page.expect_download(timeout=60000) as download_info:
            # 出力ボタンクリック
            click_button_element(page, ["button:has-text('出力')", "#input1_span ~ button"], "出力ボタン")
            page.wait_for_timeout(1500)
            
            # ポップアップ「はい(Y)」クリック
            popup_selectors = ["button:has-text('はい')", "button:has-text('はい(Y)')", "input[value*='はい']"]
            click_button_element(page, popup_selectors, "はいボタン")

        download = download_info.value
        csv_path = download.path()
        print(f"   --> CSVダウンロード完了: {csv_path}")

        browser.close()

    # CSV読み込み & A~G列の抽出
    print("6. CSVデータの整形処理中...")
    try:
        df = pd.read_csv(csv_path, encoding='cp932')
    except Exception:
        df = pd.read_csv(csv_path, encoding='utf-8')

    # A~G列（先頭7列）のみ取得
    df_sub = df.iloc[:, :7]
    matrix = [df_sub.columns.tolist()] + df_sub.fillna("").values.tolist()

    # スプレッドシート更新
    print("7. スプレッドシート更新中...")
    ws = doc.get_worksheet_by_id(TARGET_GID)
    ws.clear()
    ws.update(range_name='A1', values=matrix, value_input_option='USER_ENTERED')
    print("★【成功】A〜G列への転記が正常に完了しました！")

if __name__ == "__main__":
    run()
