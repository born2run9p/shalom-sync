# -*- coding: utf-8 -*-
import json
import os
import time
from datetime import datetime
import gspread
from playwright.sync_api import sync_playwright
import pyotp

# ==========================================
# 設定情報 (GitHub Secrets / 環境変数から取得)
# ==========================================
SHALOM_ID = os.environ.get("SHALOM_ID") or "145371-01"
SHALOM_PASS = os.environ.get("SHALOM_PASS") or "Vy0h119900"
TOTP_SECRET = os.environ.get("TOTP_SECRET") or "ZJ276V7UI5G5JEE6"

# ご指定のターゲットスプレッドシートID
TARGET_SPREADSHEET_KEY = (
    os.environ.get("TARGET_SPREADSHEET_KEY")
    or "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34"
)
JSON_KEY_FILE = "service-account-key.json"

# GID による各シートの定義
GID_EGOV = "910840628"  # 電子申請シート
GID_MYNA = "1520113795"  # マイナ申請シート
GID_ALL = "368650283"  # 全件統合一覧シート
GID_PENDING = "282241935"  # 未完了・対応必要シート


def get_gspread_client():
  cred_json = os.environ.get("GCP_SA_KEY")
  if cred_json:
    key_dict = json.loads(cred_json)
    return gspread.service_account_from_dict(key_dict)
  else:
    return gspread.service_account(filename=JSON_KEY_FILE)


def get_worksheet_by_gid(sh, gid, fallback_title):
  """GIDをもとにワークシートを取得（見つからない場合は新規作成）"""
  for ws in sh.worksheets():
    if str(ws.id) == str(gid):
      return ws
  try:
    return sh.worksheet(fallback_title)
  except Exception:
    return sh.add_worksheet(title=fallback_title, rows=1000, cols=12)


# ------------------------------------------
# Playwright スクレイピング補助関数
# ------------------------------------------
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
  try:
    confirm_btn = page.locator(
        "button:has-text('はい'), input[value='画面を閉じる'], input[value='はい'],"
        " a:has-text('はい')"
    ).first
    confirm_btn.wait_for(timeout=5000)
    confirm_btn.click()
    print(
        f"   --> [{url_name}]"
        " ポップアップで『はい』をクリックしました！"
    )
  except Exception:
    print(
        f"   --> [{url_name}] 1つ目のポップアップ（はいボタン）は表示されませんでした。"
    )

  print(f"   --> [{url_name}] 画面の更新・データ処理中（30秒間待機）...")
  page.wait_for_timeout(30000)

  try:
    ok_btn = page.locator(
        "button:has-text('OK'), input[value='OK'], a:has-text('OK'),"
        " button:has-text('確認'), input[value='確認']"
    ).first
    ok_btn.wait_for(state="visible", timeout=10000)
    ok_btn.click()
    print(f"   --> [{url_name}] ポップアップで『OK』をクリックしました！")
    page.wait_for_timeout(3000)
  except Exception:
    print(
        f"   --> [{url_name}]"
        " 『OK』ボタンは見つかりませんでした。次の処理に進みます。"
    )


def scrape_table_data(page, url_name):
  """メインテーブルのみを特定してスクロール＆データ抽出を行う関数"""
  print(
      f"   --> [{url_name}] テーブル内部へ直接スクロール操作を実行中..."
  )
  scraped_data = []

  target_context = page
  if page.locator("table").count() == 0:
    for frame in page.frames:
      if frame.locator("table").count() > 0:
        target_context = frame
        print(
            f"   --> [{url_name}] iframe"
            " 内のテーブル領域を検出しました。"
        )
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
    is_first = step == 0
    main_table = get_main_table(target_context)
    current_rows = collect_visible_rows_from_main_table(
        main_table, is_first_fetch=is_first
    )

    header_row = scraped_data[0] if len(scraped_data) > 0 else None

    for row in current_rows:
      if header_row and row == header_row:
        continue
      if row not in scraped_data:
        scraped_data.append(row)

    print(
        f"   --> [{url_name} - {step + 1}回目] 取得件数:"
        f" {len(scraped_data)} 行"
    )

    if len(scraped_data) == last_count:
      same_count_limit += 1
      if same_count_limit >= 3:
        print(
            f"   --> [{url_name}]"
            " これ以上新しいデータがないためスクロール完了とみなします。"
        )
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


# ------------------------------------------
# データ抽出用ヘルパー関数
# ------------------------------------------
def parse_table_to_integrated_rows(
    raw_table, number_target_name, data_source_label, now_str
):
  """取得した二次元リストから必要な列（公文書保管完了を含む10項目）を抽出する"""
  if not raw_table or len(raw_table) < 2:
    return []

  headers = [str(h).strip() for h in raw_table[0]]
  rows = raw_table[1:]

  def get_val(row, target_names):
    if isinstance(target_names, str):
      target_names = [target_names]
    for target_name in target_names:
      for idx, h in enumerate(headers):
        if h == target_name:
          if idx < len(row):
            v = str(row[idx]).strip()
            if v:
              return v
    return ""

  parsed_rows = []
  for row in rows:
    office = get_val(row, ["事業所名", "事業所"])
    title = get_val(row, ["手続名", "手続名称", "手続き名"])
    number = get_val(row, number_target_name)
    kind = get_val(row, "種別")
    insured = get_val(row, "被保険者名")
    status = get_val(row, ["現在状況", "状況"])
    status_date = get_val(row, ["現在状況 日時", "現在状況日時", "日時"])
    doc_archived = get_val(
        row, ["公文書保管完了", "公文書保管", "公文書", "保管状況"]
    )

    if any([number, office, title, status]):
      parsed_rows.append([
          number,
          office,
          kind,
          title,
          insured,
          status,
          status_date,
          data_source_label,
          now_str,
          doc_archived,  # 10列目：公文書保管完了
      ])

  return parsed_rows


def is_finished_and_archived(row):
  """現在状況が『終了/完了』かつ公文書保管完了が『済』かどうかを判定"""
  status = str(row[5]).strip()
  doc_archived = str(row[9]).strip()

  is_status_done = any(k in status for k in ["終了", "完了"])
  is_doc_done = doc_archived in ["済", "完了", "〇", "○", "OK", "ok", "1", "True"]

  return is_status_done and is_doc_done


# ------------------------------------------
# メイン処理
# ------------------------------------------
def run():
  print(
      f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
      " 定期リモート同期処理を開始します..."
  )

  data_ea1100w = []
  data_mp0002w = []

  # 1. 自動ブラウザで社労夢から直接取得
  print("\n🚀 社労夢へリモートアクセス中...")
  with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    # --- ① ログイン画面を開く ---
    print("1. ログイン画面にアクセス中...")
    try:
      page.goto(
          "https://4ever.shalom-house.jp/login",
          wait_until="domcontentloaded",
          timeout=60000,
      )
    except Exception as e:
      print(f"   --> ページ読み込み警告: {e}")

    page.wait_for_timeout(5000)

    target_frame = page
    print("   --> ログイン入力フォームの検出を開始します...")

    found = False
    for _ in range(12):
      if page.locator("input").count() > 0:
        found = True
        break
      for frame in page.frames:
        if frame.locator("input").count() > 0:
          target_frame = frame
          found = True
          print("   --> iframe 内にログインフォームを検出しました。")
          break
      if found:
        break
      page.wait_for_timeout(5000)

    id_field = target_frame.locator(
        "input[type='text'], input[type='email'], input[name*='id'],"
        " input[name*='user'], input:not([type='password']):not([type='hidden'])"
    ).first

    try:
      id_field.wait_for(state="attached", timeout=30000)
      print(f"1. IDを入力中... ({SHALOM_ID})")
      id_field.click(force=True)
      id_field.press("Control+A")
      id_field.press("Backspace")
      id_field.type(SHALOM_ID, delay=50)
    except Exception as err:
      print(f"❌ ID入力フィールドの検出に失敗しました: {err}")
      raise err

    print("2. パスワードを入力中...")
    pass_field = target_frame.locator("input[type='password']").first
    pass_field.wait_for(state="attached", timeout=10000)
    pass_field.click(force=True)
    pass_field.press("Control+A")
    pass_field.press("Backspace")
    pass_field.type(SHALOM_PASS, delay=50)

    print("3. ログインボタンをクリックします...")
    login_btn = target_frame.locator(
        "button[type='submit'], input[type='submit'],"
        " button:has-text('ログイン'), input[value='ログイン']"
    ).first
    login_btn.click()

    # --- ② 2FA認証 ---
    print("4. 二要素認証（2FA）画面の待機中...")
    page.wait_for_selector(
        "input[type='tel'], input[type='number'], input[name*='otp'],"
        " input[name*='code'], input",
        timeout=20000,
    )
    page.wait_for_timeout(1000)

    totp = pyotp.TOTP(TOTP_SECRET)
    code = totp.now()
    print(f"   --> 生成されたワンタイムコード: {code}")

    otp_field = page.locator(
        "input[type='tel'], input[type='number'], input[name*='otp'],"
        " input[name*='code']"
    ).first
    otp_field.click()
    otp_field.fill(code)
    page.wait_for_timeout(500)

    auth_btn = page.locator(
        "button:has-text('認証'), input[value='認証'],"
        " button:has-text('送信'), button[type='submit'], input[type='submit']"
    ).first
    if auth_btn.is_visible():
      auth_btn.click()
    else:
      otp_field.press("Enter")

    # --- ③ 電子申請 (EA1100W) 取得 ---
    print("\n5. 電子申請ページ（EA1100W）へ移動中...")
    page.wait_for_timeout(4000)
    page.goto("https://4ever.shalom-house.jp/EA1100W")
    handle_popups_and_wait(page, "EA1100W")
    data_ea1100w = scrape_table_data(page, "EA1100W")

    # --- ④ マイナ申請 (MP0002W) 取得 ---
    print("\n6. マイナ申請ページ（MP0002W）へ移動中...")
    page.goto("https://4ever.shalom-house.jp/MP0002W")
    page.wait_for_timeout(4000)
    handle_popups_and_wait(page, "MP0002W")
    data_mp0002w = scrape_table_data(page, "MP0002W")

    browser.close()

  # 2. データの解析と統合
  now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

  rows_sheet1 = parse_table_to_integrated_rows(
      data_ea1100w, "到達番号", "電子申請", now_str
  )
  rows_sheet2 = parse_table_to_integrated_rows(
      data_mp0002w, "受付番号", "マイナ申請", now_str
  )

  all_rows = rows_sheet1 + rows_sheet2
  pending_rows = [r for r in all_rows if not is_finished_and_archived(r)]

  print(
      f"\n📊 統合完了: 電子申請 {len(rows_sheet1)}件 / マイナ申請 {len(rows_sheet2)}件"
      f" (合計 {len(all_rows)}件)"
  )
  print(f"📌 未完了・対応必要データ: {len(pending_rows)}件")

  if not all_rows:
    print("⚠️ 取得されたデータが0件でした。書き込みをスキップします。")
    return

  # 3. 各シートへの書き込み処理
  print("\n7. スプレッドシート各シートへ書き込み中...")
  gc = get_gspread_client()
  target_sh = gc.open_by_key(TARGET_SPREADSHEET_KEY)

  headers = [[
      "番号",
      "事業所名",
      "種別",
      "手続名",
      "被保険者名",
      "現在状況",
      "現在状況 日時",
      "データ元",
      "最終更新日時",
      "公文書保管完了",
  ]]

  # ① 電子申請シート (gid=910840628)
  ws_egov = get_worksheet_by_gid(target_sh, GID_EGOV, "e-Gov-check")
  ws_egov.clear()
  ws_egov.update(headers + rows_sheet1, "A1")
  print(
      f"  --> [1/4] 電子申請シート (gid:{GID_EGOV}) に {len(rows_sheet1)} 件更新"
  )

  # ② マイナ申請シート (gid=1520113795)
  ws_myna = get_worksheet_by_gid(target_sh, GID_MYNA, "myna -check")
  ws_myna.clear()
  ws_myna.update(headers + rows_sheet2, "A1")
  print(
      f"  --> [2/4] マイナ申請シート (gid:{GID_MYNA}) に {len(rows_sheet2)} 件更新"
  )

  # ③ 全件統合一覧シート (gid=368650283)
  ws_all = get_worksheet_by_gid(target_sh, GID_ALL, "全件統合一覧")
  ws_all.clear()
  ws_all.update(headers + all_rows, "A1")
  print(
      f"  --> [3/4] 全件統合一覧 (gid:{GID_ALL}) に {len(all_rows)} 件更新"
  )

  # ④ 未完了・対応必要一覧シート (gid=282241935)
  ws_pending = get_worksheet_by_gid(
      target_sh, GID_PENDING, "未完了・対応必要一覧"
  )
  ws_pending.clear()
  ws_pending.update(headers + pending_rows, "A1")
  print(
      f"  --> [4/4] 未完了・対応必要一覧 (gid:{GID_PENDING}) に"
      f" {len(pending_rows)} 件更新"
  )

  print("\n★ 完全リモート更新成功！すべてのシートへの振り分けが完了しました。")


if __name__ == "__main__":
  run()
