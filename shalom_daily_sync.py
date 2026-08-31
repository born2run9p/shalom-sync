# --- ③ 1つ目のページ（EA1100W）の処理 ---
        print("\n6. 1つ目の目的ページ（EA1100W）へ移動中...")
        page.wait_for_timeout(4000)
        page.goto(URL_EA1100W, wait_until="networkidle")  # 通信完了までしっかり待機
        page.wait_for_timeout(5000)  # 画面描画の確実な待機

        # 1. 「クリア(R)」ボタンを押下（ショートカット Alt+R のフォールバック付き）
        print("   --> [EA1100W] 『クリア(R)』ボタンをクリック中...")
        clear_btn_selectors = [
            "#input33",
            "button:has-text('クリア')",
            "input[value*='クリア']",
            "button:has-text('クリア(R)')",
            "input[value*='クリア(R)']",
            "input[type='button'][value*='クリア']"
        ]
        
        # 要素クリックを試行
        if not click_button_element(page, clear_btn_selectors, "クリア(R)ボタン"):
            print("   --> [補足] ボタンが直接見つからなかったため、ショートカットキー (Alt+R) を送信します...")
            page.keyboard.press("Alt+r")
            page.wait_for_timeout(2000)
        else:
            print("   --> 『クリア(R)』ボタンをクリックしました。")
        
        page.wait_for_timeout(3000)

        # 2. 2つのチェックボックス（#input23, #input24）をオンにする
        print("   --> [EA1100W] 指定のチェックボックスをオンに設定中...")
        chk1_selectors = ["#input23", "input[type='checkbox']#input23"]
        chk2_selectors = ["#input24", "input[type='checkbox']#input24"]

        if set_checkbox_checked(page, chk1_selectors, "チェックボックス1(input23)"):
            print("   --> チェックボックス(input23) をオンに設定しました。")
        if set_checkbox_checked(page, chk2_selectors, "チェックボックス2(input24)"):
            print("   --> チェックボックス(input24) をオンに設定しました。")
        page.wait_for_timeout(1000)

        # 3. 「検索(F)」ボタンを押下（ショートカット Alt+F のフォールバック付き）
        print("   --> [EA1100W] 『検索(F)』ボタンをクリック中...")
        search_btn_selectors = [
            "#input34",
            "button:has-text('検索')",
            "input[value*='検索']",
            "button:has-text('検索(F)')",
            "input[value*='検索(F)']",
            "input[type='button'][value*='検索']"
        ]
        if not click_button_element(page, search_btn_selectors, "検索(F)ボタン"):
            print("   --> [補足] 検索ボタンが見つからなかったため、ショートカットキー (Alt+F) を送信します...")
            page.keyboard.press("Alt+f")
            page.wait_for_timeout(2000)
        else:
            print("   --> 『検索(F)』ボタンをクリックしました。")
            
        page.wait_for_timeout(3000)
