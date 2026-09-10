def collect_visible_rows_from_main_table(main_table, is_first_fetch=False):
    """メインテーブルのみから行データを抽出する（改行以降の文字列を確実に削除）"""
    extracted_rows = []
    if not main_table:
        return extracted_rows

    rows = main_table.locator("tr").all()
    for row in rows:
        th_count = row.locator("th").count()
        td_count = row.locator("td").count()
        
        if not is_first_fetch and th_count > 0 and td_count == 0:
            continue

        # 各セル（th/td）のinnerTextを評価し、最初の改行以降をカット
        cells = row.locator("th, td").evaluate_all("""
            elements => elements.map(el => {
                // <br> タグを改行コードに置換したうえで innerText を取得
                let text = el.innerText || el.textContent || "";
                // 最初に見つかる改行（\n や \r）または半角/全角の改行タグ以降をすべて削除
                let firstLine = text.split(/[\r\n]+/)[0];
                return firstLine ? firstLine.trim() : "";
            })
        """)

        if any(cells):
            extracted_rows.append(cells)

    return extracted_rows
