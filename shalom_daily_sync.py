# -*- coding: utf-8 -*-
import os
import json
import gspread
from datetime import datetime

# ==========================================
# 設定情報
# ==========================================
SHALOM_SHEET1_KEY = os.environ.get("SHALOM_SHEET1_KEY") or "14IbYjp3hizNBbb_h0wqu5H217U4UrU5-KKh0DX_QVtk"
SHALOM_SHEET2_KEY = os.environ.get("SHALOM_SHEET2_KEY") or "1TrGFfFzDzaPaxafgUeKHfsmhvqMs98-xSB-sl7LRrBw"
TARGET_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY") or "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34"

JSON_KEY_FILE = "service-account-key.json"

def get_gspread_client():
    cred_json = os.environ.get("GCP_SA_KEY")
    if cred_json:
        key_dict = json.loads(cred_json)
        return gspread.service_account_from_dict(key_dict)
    else:
        return gspread.service_account(filename=JSON_KEY_FILE)

def fetch_sheet_data(gc, key):
    try:
        print(f"   --> シート(ID: {key}) を読み込み中...")
        sh = gc.open_by_key(key)
        ws = sh.sheet1
        data = ws.get_all_records()
        print(f"   --> {len(data)} 件のデータを取得しました。")
        return data
    except Exception as e:
        print(f"❌ シート(ID: {key})の取得エラー: {e}")
        return []

def extract_value(row, possible_keys):
    """複数考えられる列名から値を抽出し、トリムする関数"""
    for k in possible_keys:
        if k in row and row[k] is not None:
            val = str(row[k]).strip()
            if val:
                return val
    return ""

def run():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 定期更新処理を開始します...")
    
    gc = get_gspread_client()
    
    # 1. 各シートからデータ取得
    data_sheet1 = fetch_sheet_data(gc, SHALOM_SHEET1_KEY)
    data_sheet2 = fetch_sheet_data(gc, SHALOM_SHEET2_KEY)
    
    if not data_sheet1 and not data_sheet2:
        print("❌ 両方のシートからデータを取得できませんでした。処理を中断します。")
        raise Exception("社労夢データの取得に失敗しました。共有権限を確認してください。")

    all_rows = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 2. シート1の処理（到達番号 -> 番号）
    for row in data_sheet1:
        number = extract_value(row, ["到達番号", "申請番号", "番号"])
        if not number:
            continue
            
        office = extract_value(row, ["事業所名", "事業所"])
        kind = extract_value(row, ["種別"])
        title = extract_value(row, ["手続名", "手続名称", "手続き名"])
        insured = extract_value(row, ["被保険者名", "被保険者"])
        status = extract_value(row, ["現在状況", "ステータス", "状況"])
        status_date = extract_value(row, ["現在状況 日時", "現在状況日時", "日時"])

        all_rows.append([
            number,
            office,
            kind,
            title,
            insured,
            status,
            status_date,
            "シート1",
            now_str
        ])

    # 3. シート2の処理（受付番号 -> 番号）
    for row in data_sheet2:
        number = extract_value(row, ["受付番号", "申請番号", "番号"])
        if not number:
            continue

        office = extract_value(row, ["事業所名", "事業所"])
        kind = extract_value(row, ["種別"])
        title = extract_value(row, ["手続名", "手続名称", "手続き名"])
        insured = extract_value(row, ["被保険者名", "被保険者"])
        status = extract_value(row, ["現在状況", "ステータス", "状況"])
        status_date = extract_value(row, ["現在状況 日時", "現在状況日時", "日時"])

        all_rows.append([
            number,
            office,
            kind,
            title,
            insured,
            status,
            status_date,
            "シート2",
            now_str
        ])

    print(f"   --> データ抽出完了: 合計 {len(all_rows)} 件")

    # 4. 出力先シート準備
    target_sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    
    try:
        ws_all = target_sh.worksheet("全件統合一覧")
    except:
        ws_all = target_sh.add_worksheet(title="全件統合一覧", rows=1000, cols=10)

    # 5. 書き込み
    headers = [["番号", "事業所名", "種別", "手続名", "被保険者名", "現在状況", "現在状況 日時", "データ元", "最終更新日時"]]
    ws_all.clear()
    ws_all.update(headers + all_rows, 'A1')

    print(f"★ 更新成功！ 全件統合一覧に {len(all_rows)} 件を書き込みました。")

if __name__ == "__main__":
    run()
