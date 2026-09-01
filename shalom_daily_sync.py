# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import datetime
import re
import pyotp
import gspread
import pandas as pd
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

# スプレッドシートID
SPREADSHEET_KEY_1 = "12drmIzzXsTyx_16TBOzTWxMygNrBuQv_r-8HSnT_V34"
SPREADSHEET_KEY_2 = "1cb8gOz19iN6IR7hXbPnlifDXMvcN91amOMG_raSQoTs"

# シートGID定義
GID_EA1100W = 910840628
GID_MP0002W = 1520113795
GID_COMBINED = 368650283
GID_FILTERED = 282241935

# URL定義
URL_EA1100W = "https://4ever.shalom-house.jp/EA1100W"
URL_MP0002W = "https://4ever.shalom-house.jp/MP0002W"

# 統合シート用（10項目）
TARGET_COLUMNS = [
    "番号", "事業所名", "種別", "手続名", "被保険者名",
    "現在状況", "現在状況 日時", "データ元", "公文書保管完了", "最終更新日時"
]

# ピックアップシート用（9項目）
PICKUP_COLUMNS = [
    "データ元", "番号", "事業所名", "種別", "手続名",
    "被保険者名", "現在状況", "現在状況 日時", "最終更新日時"
]

GCP_SA_KEY = os.environ.get("GCP_SA_KEY")


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


def clean_cell_text(val):
    """セル値の前後の不要な空白（半角・全角・改行・タブ）を安全に除去する"""
    if not val or pd.isna(val):
        return ""
    return str(val).strip(' \t\n\r\u3000')


def clean_status_value(val):
    """(100%) や 100% などのパーセント表記を取り除く"""
    if not val or pd.isna(val):
        return ""
    val_str = str(val)
    cleaned = re.sub(r'[\(（]?\s*[0-9０-９]+\s*[%％]\s*[\)）]?', '', val_str)
    return clean_cell_text(cleaned)


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


def click_button_element(page, selectors, button_name="ボタン"):
    """ボタン要素を強力に検索してクリック (force=True 対応)"""
    start_time = time.time()
    while time.time() - start_time < 20:
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
    print(f"   --> [{button_name}] のクリック対象が見つからないか、クリックできませんでした。")
    return False


def set_checkbox_checked(page, selectors, checkbox_name="チェックボックス"):
    """チェックボックス要素を確実にオン（チェック状態）にする"""
    start_time = time.time()
    while time.time() - start_time < 20:
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


def handle_initial_msgbox(page):
    """画面表示直後に出るポップアップ（MsgBoxBtnOK）を処理する"""
    print("   --> メッセージボックス（MsgBoxBtnOK）の表示を確認中...")
    msg_box_selectors = [
        "#MsgBoxBtnOK",
        "button#MsgBoxBtnOK",
        "button:has-text('OK')"
    ]
    if click_button_element(page, msg_box_selectors, "初期ポップアップのOKボタン"):
        print("   --> ★ 初期メッセージボックスの『OK』をクリックしました。")
        page.wait_for_timeout(2000)
    else:
        print("   --> 初期メッセージボックスは表示されませんでした。")


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
    popup_selectors = ["button:has-text('はい')", "input[value='画面を閉じる']", "input[value='はい']", "a:has-text('はい')"]
    if click_button_element(page, popup_selectors, f"{url_name} - はいボタン"):
        print(f"   --> [{url_name}] ポップアップで『はい』をクリックしました！")
    else:
        print(f"   --> [{url_name}] 1つ目のポップアップ（はいボタン）は表示されませんでした。")

    print(f"   --> [{url_name}] 画面の更新・データ処理中（30秒間待機）...")
    page.wait_for_timeout(30000)

    ok_selectors = ["#MsgBoxBtnOK", "button:has-text('OK')", "input[value='OK']", "a:has-text('OK')", "button:has-text('確認')"]
    if click_button_element(page, ok_selectors, f"{url_name} - OKボタン"):
        print(f"   --> [{url_name}] ポップアップで『OK』をクリックしました！")
        page.wait_for_timeout(3000)
    else:
        print(f"   --> [{url_name}] 『OK』ボタンは見つかりませんでした。次の処理に進みます。")


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


def format_datetime_str(val):
    """和暦（令和/平成/R/H）を含む文字列を yyyy/mm/dd hh:mm:ss 形式に変換する関数"""
    if not val or pd.isna(val):
        return ""
    val_str = str(val).strip()
    if not val_str:
        return ""

    val_str = val_str.translate(str.maketrans({
        '０':'0','１':'1','２':'2','３':'3','４':'4',
        '５':'5','６':'6','７':'7','８':'8','９':'9',
        '：':':','／':'/','．':'.'
    }))

    wareki_match = re.search(r'(令和|平成|R|H)\s*([0-9元]+)\s*[\.年/]\s*([0-9]+)\s*[\.月/]\s*([0-9]+)', val_str, re.IGNORECASE)
    
    if wareki_match:
        era = wareki_match.group(1).upper()
        year_str = wareki_match.group(2)
        month = int(wareki_match.group(3))
        day = int(wareki_match.group(4))

        year_num = 1 if year_str == "元" else int(year_str)

        if era in ["令和", "R"]:
            seireki_year = 2018 + year_num
        elif era in ["平成", "H"]:
            seireki_year = 1988 + year_num
        else:
            seireki_year = year_num

        time_match = re.search(r'([0-9]{1,2})\s*[:時]\s*([0-9]{1,2})(?:\s*[:分]\s*([0-9]{1,2}))?', val_str)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            second = int(time_match.group(3)) if time_match.group(3) else 0
        else:
            hour, minute, second = 0, 0, 0

        try:
            dt = datetime.datetime(seireki_year, month, day, hour, minute, second)
            return dt.strftime("%Y/%m/%d %H:%M:%S")
        except Exception:
            pass

    try:
        dt = pd.to_datetime(val_str)
        if pd.notna(dt):
            return dt.strftime("%Y/%m/%d %H:%M:%S")
    except Exception:
        pass

    return val_str


def process_and_align_data(raw_data, source_label):
    """スクレイピングデータを10項目の標準カラムフォーマットに変換・補正する"""
    if not raw_data or len(raw_data) < 2:
        return pd.DataFrame(columns=TARGET_COLUMNS)

    headers = [str(h).strip() for h in raw_data[0]]
    rows = raw_data[1:]

    header_len = len(headers)
    normalized_rows = []
    for r in rows:
        if len(r) < header_len:
            r = r + [""] * (header_len - len(r))
        elif len(r) > header_len:
            r = r[:header_len]
        normalized_rows.append(r)

    df = pd.DataFrame(normalized_rows, columns=headers)
    now_str = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    if source_label == "電子申請":
        if "到達番号" in df.columns:
            df["番号"] = df["到達番号"]
    elif source_label == "マイナ申請":
        if "受付番号" in df.columns:
            df["番号"] = df["受付番号"]

    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    if "現在状況" in df.columns:
        df["現在状況"] = df["現在状況"].apply(clean_status_value)

    if "現在状況 日時" in df.columns:
        df["現在状況 日時"] = df["現在状況 日時"].apply(clean_status_value).apply(format_datetime_str)

    df["データ元"] = source_label
    df["最終更新日時"] = now_str

    res_df = df[TARGET_COLUMNS].copy()
    for col in res_df.columns:
        res_df[col] = res_df[col].apply(clean_cell_text)

    return res_df


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


def run():
    print("1. Googleスプレッドシートに接続中...")
    gc = get_gspread_client()
    
    doc1 = gc.open_by_key(SPREADSHEET_KEY_1)
    doc2 = gc.open_by_key(SPREADSHEET_KEY_2)

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
        print("   --> ページの完全ロード完了を待機中 (8秒間)")
        page.wait_for_timeout(8000)

        # ★ 最優先：画面表示時にポップアップが出た場合は「OK」を押す
        handle_initial_msgbox(page)

        # 1. 「クリア(R)」ボタン（#input33）を直接クリック
        print("   --> [EA1100W] 『クリア(R)』ボタンをクリック中...")
        clear_btn_selectors = [
            "#input33",
            "button#input33",
            "button:has-text('クリア')",
            "button[value*='クリア']"
        ]
        if click_button_element(page, clear_btn_selectors, "クリアボタン"):
            print("   --> 『クリア』ボタンをクリックしました。")
        else:
            print("   --> 『クリア』ボタンが見つかりませんでした。")
        
        # クリア処理後の描画完了を待機
        page.wait_for_timeout(4000)

        # 2. 指定のチェックボックス（input23, input24, input25/エラー）をオンにする
        print("   --> [EA1100W] チェックボックス（エラー項目含む）をオンに設定中...")
        chk1_selectors = ["#input23", "input[type='checkbox']#input23"]
        chk2_selectors = ["#input24", "input[type='checkbox']#input24"]
        
        err_chk_selectors = [
            "#input25",
            "input[type='checkbox']#input25",
            "label:has-text('エラー') input",
            "input[type='checkbox']:has-text('エラー')",
            "tr:has-text('エラー') input[type='checkbox']"
        ]

        if set_checkbox_checked(page, chk1_selectors, "チェックボックス(input23)"):
            print("   --> チェックボックス(input23) をオンに設定しました。")
            
        if set_checkbox_checked(page, chk2_selectors, "チェックボックス(input24)"):
            print("   --> チェックボックス(input24) をオンに設定しました。")
            
        if set_checkbox_checked(page, err_chk_selectors, "エラーチェックボックス"):
            print("   --> エラーのチェックボックス をオンに設定しました。")

        # チェック完了後の反映待機
        page.wait_for_timeout(3000)

        # 3. 「検索(F)」ボタン（#input34）を直接クリック
        print("   --> [EA1100W] 『検索(F)』ボタンをクリック中...")
        search_btn_selectors = [
            "#input34",
            "button#input34",
            "button:has-text('検索')",
            "button[value*='検索']"
        ]
        if click_button_element(page, search_btn_selectors, "検索ボタン"):
            print("   --> 『検索』ボタンをクリックしました。")
        else:
            print("   --> 『検索』ボタンが見つかりませんでした。")

        # 検索処理・通信完了の待機
        print("   --> 検索結果の読み込みを待機中 (6秒間)...")
        page.wait_for_timeout(6000)

        # 4. 検索後にダイアログが出た場合の「OK」クリック
        print("   --> [EA1100W] ポップアップ確認（OKボタン待ち）...")
        handle_initial_msgbox(page)

        # 5. 表のデータを取得
        ea_data = scrape_table_data(page, "EA1100W")

        print("\n7. スプレッドシート（EA1100W用 gid: 910840628）を更新中...")
        if update_worksheet_by_gid(doc1, GID_EA1100W, ea_data):
            print(f"★【成功】EA1100W のデータ {len(ea_data)} 行を書き込みました！")

        # --- ④ 2つ目のページ（MP0002W）の処理 ---
        print("\n8. 2つ目の目的ページ（MP0002W）へ移動中...")
        page.goto(URL_MP0002W, wait_until="load")
        page.wait_for_timeout(5000)

        handle_popups_and_wait(page, "MP0002W")
        mp_data = scrape_table_data(page, "MP0002W")

        print("\n9. スプレッドシート（MP0002W用 gid: 1520113795）を更新中...")
        if update_worksheet_by_gid(doc1, GID_MP0002W, mp_data):
            print(f"★【成功】MP0002W のデータ {len(mp_data)} 行を書き込みました！")

        browser.close()

    # --- ⑤ データの統合・10項目フォーマット化 ---
    print("\n10. データの整形および10項目への統合処理中...")
    df_ea = process_and_align_data(ea_data, "電子申請")
    df_mp = process_and_align_data(mp_data, "マイナ申請")

    combined_df = pd.concat([df_ea, df_mp], ignore_index=True)

    for col in combined_df.columns:
        combined_df[col] = combined_df[col].apply(clean_cell_text)

    combined_matrix = [combined_df.columns.tolist()] + combined_df.fillna("").values.tolist()

    print("11. 統合スプレッドシート（gid: 368650283）を更新中...")
    if update_worksheet_by_gid(doc1, GID_COMBINED, combined_matrix):
        print(f"★【成功】統合データ {len(combined_df)} 件を書き込みました！")

    # --- ⑥ フィルタリング処理 ---
    print("\n12. 条件（現在状況:『終了』かつ 公文書保管完了:『済』）の除外フィルタリング実行中...")
    
    cond_status = combined_df["現在状況"].astype(str).str.contains("終了", na=False)
    cond_doc = combined_df["公文書保管完了"].astype(str).str.contains("済", na=False)

    filtered_df = combined_df[~(cond_status & cond_doc)].copy()

    pickup_df = filtered_df[PICKUP_COLUMNS].copy()

    for col in pickup_df.columns:
        pickup_df[col] = pickup_df[col].apply(clean_cell_text)

    def generate_source_hyperlink(source_val):
        source = str(source_val)
        if source == "電子申請":
            return f'=HYPERLINK("{URL_EA1100W}", "{source}")'
        elif source == "マイナ申請":
            return f'=HYPERLINK("{URL_MP0002W}", "{source}")'
        return source

    if "データ元" in pickup_df.columns:
        pickup_df["データ元"] = pickup_df["データ元"].apply(generate_source_hyperlink)

    filtered_matrix = [pickup_df.columns.tolist()] + pickup_df.fillna("").values.tolist()

    print("13. ピックアップ用スプレッドシート（別ブック gid: 282241935）を更新中...")
    if update_worksheet_by_gid(doc2, GID_FILTERED, filtered_matrix):
        print(f"★【成功】ピックアップデータ {len(pickup_df)} 件を更新し、A列にハイパーリンクを設定しました！")

    print("\nすべての同期・更新プロセスが正常に完了しました。")


if __name__ == "__main__":
    run()
