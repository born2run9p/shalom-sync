# -*- coding: utf-8 -*-
import os
import json
import time
import gspread
from datetime import datetime

# ==========================================
# 設定情報
# ==========================================
SHALOM_SHEET1_KEY = os.environ.get("SHALOM_SHEET1_KEY", "社労夢シート1のID")
SHALOM_SHEET2_KEY = os.environ.get("SHALOM_SHEET2_KEY", "社労夢シート2のID")
TARGET_SPREADSHEET_KEY = os.environ.get("TARGET_SPREADSHEET_KEY", "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34")

# Service Account キー
JSON_KEY_FILE = "service-account-key.json"

def get_gspread_client():
    """環境変数（クラウド用）またはローカルJSONファイルから認証情報を作成"""
    cred_json = os.environ.get("GCP_SA_KEY")
    if cred_json:
        key_dict = json.loads(cred_json)
        return gspread.service_account_from_dict(key_dict)
    else:
        return gspread.service_account(filename=JSON_KEY_FILE)

def fetch_sheet_data(gc, key):
    """スプレッドシートからデータを取得"""
    try:
        sh = gc.open_by_key(key)
        ws = sh.sheet1
        return ws.get_all_records()
    except Exception as e:
        print(f"シート(ID: {key})の取得エラー: {e}")
        return []

def run():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 定期更新処理を開始します...")
    
    gc = get_gspread_client()
    
    # 1. 社労夢の2つのシートからデータ取得
    data_sheet1 = fetch_sheet_data(gc, SHALOM_SHEET1_KEY)
    data_sheet2 = fetch_sheet_data(gc, SHALOM_SHEET2_KEY)
    
    # 2つのシートのデータを統合（申請番号をキーに重複排除）
    combined_data = {}
    
    # シート1の読み込み
    for row in data_sheet1:
        shinsei_no = str(row.get("申請番号", "")).strip()
        if shinsei_no:
            combined_data[shinsei_no] = {
                "title": str(row.get("手続名称", row.get("手続き名", ""))).strip(),
                "status": str(row.get("現在状況", "")).strip(),
                "doc_status": str(row.get("公文書保管完了", "")).strip(),
                "raw": row
            }

    # シート2の読み込み（重複がある場合は上書き、または追加）
    for row in data_sheet2:
        shinsei_no = str(row.get("申請番号", "")).strip()
        if shinsei_no:
            combined_data[shinsei_no] = {
                "title": str(row.get("手続名称", row.get("手続き名", ""))).strip(),
                "status": str(row.get("現在状況", "")).strip(),
                "doc_status": str(row.get("公文書保管完了", "")).strip(),
                "raw": row
            }

    print(f"   --> 社労夢データの統合完了: 合計 {len(combined_data)} 件")

    # 2. 対象スプレッドシートと各ワークシートの準備
    target_sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    
    # タブ1: ピックアップ一覧
    try:
        ws_pickup = target_sh.worksheet("ピックアップ一覧")
    except:
        ws_pickup = target_sh.add_worksheet(title="ピックアップ一覧", rows=1000, cols=10)
        
    # タブ2: 全件統合一覧
    try:
        ws_all = target_sh.worksheet("全件統合一覧")
    except:
        ws_all = target_sh.add_worksheet(title="全件統合一覧", rows=1000, cols=10)

    # 3. 前回の出力結果を取得して比較用マップを作成
    existing_records = ws_pickup.get_all_records()
    prev_map = {}
    for rec in existing_records:
        s_no = str(rec.get("申請番号", "")).strip()
        if s_no:
            prev_map[s_no] = {
                "status": str(rec.get("現在のステータス", "")).strip(),
                "doc_status": str(rec.get("公文書取得状況", "")).strip()
            }

    # 4. フィルタリングとデータ整形
    pickup_rows = []
    all_rows = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    for s_no, item in combined_data.items():
        title = item["title"]
        curr_status = item["status"]
        curr_doc_status = item["doc_status"]
        if not curr_doc_status:
            curr_doc_status = "未取得"

        prev_info = prev_map.get(s_no, {"status": "新規", "doc_status": "未取得"})
        prev_status = prev_info["status"]

        # ---------------------------------------------------------
        # 【厳密判定】除外対象判定
        # シート1: 「現在状況」が「手続終了」 かつ 「公文書保管完了」が「済」
        # シート2: 「現在状況」が「終了」 かつ 「公文書保管完了」が「保存済み」
        # ---------------------------------------------------------
        is_sheet1_completed = (curr_status == "手続終了" and curr_doc_status == "済")
        is_sheet2_completed = (curr_status == "終了" and curr_doc_status == "保存済み")
        
        # どちらかの完了パターンに当てはまれば「完全終了（除外）」
        is_fully_completed = is_sheet1_completed or is_sheet2_completed

        # 全件用データには必ず追加
        all_rows.append([s_no, title, curr_status, curr_doc_status, now_str])

        # 【ピックアップ条件】「完全終了」ではないもの、または前回からステータスが変わったもの
        is_changed = (prev_status != "新規" and prev_status != curr_status)

        if not is_fully_completed or is_changed:
            reasons = []
            if is_changed:
                reasons.append("ステータス変更")
            if not is_fully_completed:
                if "終了" not in curr_status:
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

    # 5. スプレッドシート（各タブ）への書き込み
    # 表1: ピックアップ一覧
    ws_pickup.clear()
    pickup_headers = [["申請番号", "手続名称", "現在のステータス", "前回のステータス", "公文書取得状況", "ピックアップ理由", "最終更新日時"]]
    ws_pickup.update(range_name='A1', values=pickup_headers + pickup_rows)

    # 表2: 全件統合一覧
    ws_all.clear()
    all_headers = [["申請番号", "手続名称", "現在のステータス", "公文書取得状況", "最終更新日時"]]
    ws_all.update(range_name='A1', values=all_headers + all_rows)

    print(f"★ 更新完了: ピックアップ({len(pickup_rows)}件) / 全件({len(all_rows)}件)")

if __name__ == "__main__":
    run()
