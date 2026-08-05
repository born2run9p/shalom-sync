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

def fetch_sheet_data_with_debug(gc, key, sheet_label):
    """シートデータを取得し、構造をデバッグ出力する"""
    try:
        print(f"\n🔍 [{sheet_label}] (ID: {key}) を読み込み中...")
        sh = gc.open_by_key(key)
        
        # 最初のワークシートを取得
        ws = sh.get_worksheet(0)
        print(f"   └ ワークシート名: '{ws.title}'")

        # 全行取得してヘッダーやデータ構造を確認
        all_values = ws.get_all_values()
        if not all_values:
            print(f"⚠️ [{sheet_label}] シート全体が完全に空です。")
            return []

        print(f"   └ 総行数: {len(all_values)} 行")
        print(f"   └ 1行目のデータ(ヘッダー候補): {all_values[0]}")

        # 辞書形式で取得
        data = ws.get_all_records()
        print(f"   └ レコード変換結果: {len(data)} 件")
        if data:
            print(f"   └ 取得できた列名一覧: {list(data[0].keys())}")
            print(f"   └ 1件目のサンプルデータ: {data[0]}")
        else:
            print(f"⚠️ [{sheet_label}] get_all_records() で0件でした。1行目がヘッダーになっていない可能性があります。")

        return data
    except Exception as e:
        print(f"❌ [{sheet_label}] 取得エラー: {e}")
        return []

def extract_value(row, target_key):
    """指定した列名（前後の空白無視）から値を取り出す"""
    if not isinstance(row, dict):
        return ""
    # 完全一致
    if target_key in row and row[target_key] is not None:
        return str(row[target_key]).strip()
    # 前後の空白を吸収して検索
    for k, v in row.items():
        if k.strip() == target_key and v is not None:
            return str(v).strip()
    return ""

def run():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 定期更新処理を開始します...")
    
    gc = get_gspread_client()
    
    # 1. 各シートからデータ取得（デバッグ付き）
    data_sheet1 = fetch_sheet_data_with_debug(gc, SHALOM_SHEET1_KEY, "シート1(電子申請)")
    data_sheet2 = fetch_sheet_data_with_debug(gc, SHALOM_SHEET2_KEY, "シート2(マイナ申請)")
    
    if not data_sheet1 and not data_sheet2:
        print("\n❌ 両方のシートからデータを取得できませんでした。処理を中断します。")
        raise Exception("社労夢データの取得に失敗しました。")

    all_rows = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 2. シート1の処理（電子申請：到達番号）
    count_sheet1 = 0
    for row in data_sheet1:
        office = extract_value(row, "事業所名")
        title = extract_value(row, "手続名") or extract_value(row, "手続名称")
        number = extract_value(row, "到達番号")
        kind = extract_value(row, "種別")
        insured = extract_value(row, "被保険者名")
        status = extract_value(row, "現在状況")
        status_date = extract_value(row, "現在状況 日時") or extract_value(row, "現在状況日時")

        # 完全に空の行以外を取り込む
        if any([number, office, title, status]):
            all_rows.append([
                number,
                office,
                kind,
                title,
                insured,
                status,
                status_date,
                "電子申請",
                now_str
            ])
            count_sheet1 += 1

    # 3. シート2の処理（マイナ申請：受付番号）
    count_sheet2 = 0
    for row in data_sheet2:
        office = extract_value(row, "事業所名")
        title = extract_value(row, "手続名") or extract_value(row, "手続名称")
        number = extract_value(row, "受付番号")
        kind = extract_value(row, "種別")
        insured = extract_value(row, "被保険者名")
        status = extract_value(row, "現在状況")
        status_date = extract_value(row, "現在状況 日時") or extract_value(row, "現在状況日時")

        if any([number, office, title, status]):
            all_rows.append([
                number,
                office,
                kind,
                title,
                insured,
                status,
                status_date,
                "マイナ申請",
                now_str
            ])
            count_sheet2 += 1

    print(f"\n📊 抽出結果: 電子申請 {count_sheet1}件 / マイナ申請 {count_sheet2}件 (合計 {len(all_rows)}件)")

    # 4. 出力先シート書き込み
    target_sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)
    
    try:
        ws_all = target_sh.worksheet("全件統合一覧")
    except:
        ws_all = target_sh.add_worksheet(title="全件統合一覧", rows=1000, cols=10)

    headers = [["番号", "事業所名", "種別", "手続名", "被保険者名", "現在状況", "現在状況 日時", "データ元", "最終更新日時"]]
    ws_all.clear()
    ws_all.update(headers + all_rows, 'A1')

    print(f"★ 更新成功！ 全件統合一覧に {len(all_rows)} 件を書き込みました。")

if __name__ == "__main__":
    run()
