def collect_visible_rows_from_main_table(main_table, is_first_fetch=False):
    """メインテーブルのみから行データを抽出する（改行以降の文字列を削除）"""
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
        clean_cells = []
        for c in cells:
            # 1. 改行文字 (\r\n, \n, \r) で分割し、1行目（改行より前）だけを取得
            first_line = c.splitlines()[0] if c.splitlines() else ""
            # 2. 前後の不要な空白をトリム
            clean_cells.append(first_line.strip())

        if any(clean_cells):
            extracted_rows.append(clean_cells)

    return extracted_rows
