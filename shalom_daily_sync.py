import os
import sys
import json
import time
import pyotp
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 環境変数と設定値
# ==========================================
SHALOM_ID = os.environ.get("SHALOM_ID")
SHALOM_PASS = os.environ.get("SHALOM_PASS")
TOTP_SECRET = os.environ.get("TOTP_SECRET")
GCP_SA_KEY = os.environ.get("GCP_SA_KEY")
TARGET_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY")

# エラーログに出ていた gid と フォールバック用のシート名
TARGET_GID = 910840628
TARGET_SHEET_NAME = "電子申請"


def get_chrome_driver():
    """Headless Chrome Driverの設定・立ち上げ"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=chrome_options)


def login_to_shalom(driver):
    """社労夢へのログイン処理（TOTP 2要素認証自動突破を含む）"""
    print("[INFO] ===== 社労夢 デイリー同期処理 開始 =====")
    print("[INFO] 社労夢へのリモートアクセスを開始します...")
    
    login_url = "https://4ever.shalom-house.jp/login"
    driver.get(login_url)
    
    wait = WebDriverWait(driver, 20)
    
    print(f"[INFO] ログインページにアクセス: {login_url}")
    print("[INFO] ログインページのロードおよびフォーム表示を待機中...")
    
    # ID / パスワード入力フィールドの取得と入力
    id_field = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='id'], input[name='userId'], input[type='text']"))
    )
    pass_field = driver.find_element(By.CSS_SELECTOR, "input[name='password'], input[type='password']")
    
    print("[INFO] ログイン入力フィールドを検出しました。")
    print("[INFO] ID / パスワードを入力中...")
    
    id_field.clear()
    id_field.send_keys(SHALOM_ID)
    pass_field.clear()
    pass_field.send_keys(SHALOM_PASS)
    
    # ログインボタン押下
    submit_btn = driver.find_element(By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
    submit_btn.click()
    
    time.sleep(5)
    
    # ------------------------------------------
    # 2要素認証（TOTP）突破処理
    # ------------------------------------------
    print(f"[INFO] ログイン操作後の現在URL: {driver.current_url}")
    
    if "login" in driver.current_url or TOTP_SECRET:
        print("[WARN] 2要素認証（または追加承認）画面を処理します...")
        try:
            # OTP入力フィールドを検索
            totp_input = wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input[name*='totp'], input[name*='code'], input[name*='otp'], input[type='text']"
                ))
            )
            
            if TOTP_SECRET and totp_input:
                print("[INFO] TOTP_SECRET からワンタイムパスワードを自動生成中...")
                totp = pyotp.TOTP(TOTP_SECRET)
                otp_code = totp.now()
                
                totp_input.clear()
                totp_input.send_keys(otp_code)
                print(f"[INFO] ワンタイムパスワード ({otp_code}) を入力しました。")
                
                # 認証・送信ボタン押下
                auth_btn = driver.find_element(
                    By.XPATH, "//button[contains(text(),'認証') or contains(text(),'送信') or @type='submit']"
                )
                auth_btn.click()
                print("[INFO] ログイン完了・画面遷移を待機中 (15秒)...")
                time.sleep(15)
        except Exception as e:
            print(f"[WARN] 2要素認証の全自動突破をスキップ/試行失敗: {e}")


def fetch_shalom_data(driver):
    """データ取得ページ（EA1100W, MP0002W）へのアクセスとデータ収集"""
    wait = WebDriverWait(driver, 20)
    scraped_df = None

    # EA1100W アクセス
    url_ea = "https://4ever.shalom-house.jp/EA1100W"
    print(f"[INFO] ページを開いています: {url_ea}")
    driver.get(url_ea)
    
    try:
        print("[INFO] EA1100W のテーブル要素読み込みを待機中 (最大20秒)...")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # HTMLからテーブルデータを読み込み
        dfs = pd.read_html(driver.page_source)
        if dfs:
            scraped_df = dfs[0]
            print(f"[INFO] EA1100W からデータテーブルを取得しました ({len(scraped_df)} 行)")
        else:
            print(f"[WARN] {url_ea} からテーブルデータが検出されませんでした。")
    except Exception as e:
        print(f"[WARN] EA1100W でタイムアウトまたはテーブル検出失敗: {e}")

    # MP0002W アクセス検証
    url_mp = "https://4ever.shalom-house.jp/MP0002W"
    print(f"[INFO] ページを開いています: {url_mp}")
    driver.get(url_mp)
    
    if "login" in driver.current_url:
        print("[ERROR] MP0002W へのアクセス時にログイン画面へ戻されました。ログインが完了していません。")
        return None

    return scraped_df


def sync_to_spreadsheet(df):
    """Google スプレッドシートへのデータ同期（エラーハンドリング・フォールバック付き）"""
    print("[INFO] スプレッドシートへのデータ同期を開始します...")
    
    if not GCP_SA_KEY:
        raise ValueError("[ERROR] GCP_SA_KEY 環境変数がセットされていません。")
        
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    sa_info = json.loads(GCP_SA_KEY)
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    
    spreadsheet = client.open_by_key(TARGET_SPREADSHEET_KEY)
    worksheet = None

    # 1. gid によるシート取得を優先試行
    try:
        worksheet = spreadsheet.get_worksheet_by_id(TARGET_GID)
        print(f"[INFO] gid ({TARGET_GID}) のシートを正常に取得しました。")
    except Exception as e:
        print(f"[WARN] get_worksheet_by_id 取得時エラー: id {TARGET_GID} not found")
        print(f"[INFO] 代替手段としてシート名 '{TARGET_SHEET_NAME}' での取得を試みます...")
        
        # 2. シート名によるフォールバック取得
        try:
            worksheet = spreadsheet.worksheet(TARGET_SHEET_NAME)
            print(f"[INFO] シート名 '{TARGET_SHEET_NAME}' でシートを取得しました。")
        except Exception:
            print("[WARN] 指定したシート名が見つからないため、1番目のワークシート（sheet1）を使用します。")
            worksheet = spreadsheet.sheet1

    if not worksheet:
        raise Exception("[ERROR] 指定されたワークシートが見つからず、同期を中断しました。")

    # データ書き込み処理
    if df is not None and not df.empty:
        df_cleaned = df.fillna("")
        headers = df_cleaned.columns.tolist()
        values = df_cleaned.values.tolist()
        
        worksheet.clear()
        worksheet.update('A1', [headers] + values)
        print("[INFO] スプレッドシートへのデータ書き込みが正常に完了しました。")
    else:
        print("[WARN] 同期対象のデータが空です。更新をスキップします。")


def main():
    driver = None
    try:
        driver = get_chrome_driver()
        
        # 1. ログイン
        login_to_shalom(driver)
        
        # 2. データ取得
        df = fetch_shalom_data(driver)
        
        if df is None:
            print("[FATAL] 処理が異常終了しました: ログイン状態の保持またはデータ取得に失敗しました。")
            sys.exit(1)
            
        # 3. スプレッドシートへ同期
        sync_to_spreadsheet(df)
        print("[INFO] すべての処理が成功しました。")
        
    except Exception as e:
        print(f"[FATAL] 処理が異常終了しました: {e}")
        sys.exit(1)
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
