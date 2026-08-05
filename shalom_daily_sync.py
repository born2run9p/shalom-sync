# -*- coding: utf-8 -*-
import os
import json
import time
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

def get_column_value(row, possible_keys, default=""):
    """表記ゆれに対応して値を取り出すヘルパー関数"""
    for k in possible_keys:
        if k in row and row[k] is not None:
            val = str(row[k]).strip()
            if val:
                return val
    return default

def run():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 定期更新処理を開始します...")
    
    gc = get_gspread_client()
    
    # 1. データ取得
    data_sheet1 = fetch_sheet_data(gc, SHALOM_SHEET1_KEY)
    data_sheet2 = fetch_sheet_data(gc, SHALOM_SHEET2_KEY)
    
    if not data_sheet1 and not data_sheet2:
        print("❌ 両方のシートからデータを取得できませんでした。処理を中断します。")
        raise Exception("社労夢データの取得に失敗しました。共有権限を確認してください。")

    # 2. データの統合（表記ゆれ吸収）
    combined_data = {}
    
    # 列名の候補リスト
    keys_no = ["申請番号", "ID", "受付番号"]
    keys_title = ["手続名称", "手続き名", "手続名", "申請手続"]
    keys_status = ["現在状況", "ステータス", "現在のステータス", "状況"]
    keys_doc = ["公文書保管完了", "公文書", "公文書取得状況", "保管状況", "公文書状況"]

    for row in data_sheet1 + data_sheet2:
        shinsei_no = get_column_value(row, keys_no)
        if shinsei_no:
            combined_data[shinsei_no] = {
                "title": get_column_value(row, keys_title),
                "status": get_column_value(row, keys_status),
                "doc_status": get_column_value(row, keys_doc, default="未取得"),
                "raw": row
            }

    print(f"   --> 社労夢データの統合完了: 合計 {len(combined_data)} 件")

    # 3. 出力先シート準備
    target_sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    
    try:
        ws_pickup = target_sh.worksheet("ピックアップ一覧")
    except:
        ws_pickup = target_sh.add_worksheet(title="ピックアップ一覧", rows=1000, cols=10)
        
    try:
        ws_all = target_sh.worksheet("全件統合一覧")
    except:
        ws_all = target_sh.add_worksheet(title="全件統合一覧", rows=1000, cols=10)

    # 前回のピックアップ結果を取得
    existing_records = ws_pickup.get_all_records()
    prev_map = {}
    for rec in existing_records:
        s_no = str(rec.get("申請番号", "")).strip()
        if s_no:
            prev_map[s_no] = {
                "status": str(rec.get("現在のステータス", "")).strip(),
                "doc_status": str(rec.get("公文書取得状況", "")).strip()
            }

    # 4. 判定とデータ作成
    pickup_rows = []
    all_rows = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    for s_no, item in combined_data.items():
        title = item["title"]
        curr_status = item["status"]
        curr_doc_status = item["doc_status"]

        prev_info = prev_map.get(s_no, {"status": "新規", "doc_status": "未取得"})
        prev_status = prev_info["status"]

        # ---------------------------------------------------------
        # 【除外判定】
        # ・ステータスが「手続終了」または「終了」
        # ・かつ 公文書が「済」または「保存済み」または「完了」または「取得済」
        # ---------------------------------------------------------
        is_status_finished = curr_status in ["手続終了", "終了", "完了"]
        is_doc_finished = any(w in curr_doc_status for w in ["済", "保存済み", "完了", "取得済"])
        
        is_fully_completed = is_status_finished and is_doc_finished

        # 全件統合用
        all_rows.append([s_no, title, curr_status, curr_doc_status, now_str])

        # ピックアップ判定
        is_changed = (prev_status != "新規" and prev_status != curr_status)

        if not is_fully_completed or is_changed:
            reasons = []
            if is_changed:
                reasons.append("ステータス変更")
            if not is_fully_completed:
                if not is_status_finished:
                    reasons.append("進行中")
                else:
                    reasons.append("公文書未取得/未保管")

            pickup_rows.append([
                s_no,
                title,
                curr_status,
                prev_status,
                curr_doc_status,
                " / ".join(reasons),
                now_str
            ])

    # 5. 書き込み（互換性を高めた記述）
    pickup_headers = [["申請番号", "手続名称", "現在のステータス", "前回のステータス", "公文書取得状況", "ピックアップ理由", "最終更新日時"]]
    ws_pickup.clear()
    ws_pickup.update(pickup_headers + pickup_rows, 'A1')

    all_headers = [["申請番号", "手続名称", "現在のステータス", "公文書取得状況", "最終更新日時"]]
    ws_all.clear()
    ws_all.update(all_headers + all_rows, 'A1')

    print(f"★ 更新成功！ ピックアップ({len(pickup_rows)}件) / 全件({len(all_rows)}件)")

if __name__ == "__main__":
    run()
