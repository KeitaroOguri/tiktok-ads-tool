"""
TikTok Ads Bulk Manager - Streamlit Webアプリ
"""

import streamlit as st
from loguru import logger

st.set_page_config(
    page_title="TikTok Ads Bulk Manager",
    page_icon="🎵",
    layout="wide",
)

# -------------------------------------------------------
# サイドバー
# -------------------------------------------------------
st.sidebar.title("🎵 TikTok Ads Manager")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "メニュー",
    [
        "🏠 ホーム",
        "🔑 BC・アカウント管理",
        "📋 キャンペーン一覧",
        "📤 一括入稿",
        "📋 複製",
    ]
)

# -------------------------------------------------------
# ホーム
# -------------------------------------------------------
if page == "🏠 ホーム":
    st.title("🎵 TikTok Ads Bulk Manager")
    st.markdown("複数のビジネスセンター・広告アカウントを一括管理するツールです。")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**Step 1**\n\nBC・アカウント管理でビジネスセンターを登録・認証")
    with col2:
        st.info("**Step 2**\n\nGoogle Spreadsheetに入稿データを記入")
    with col3:
        st.info("**Step 3**\n\n一括入稿でTikTokに自動入稿")

# -------------------------------------------------------
# BC・アカウント管理
# -------------------------------------------------------
elif page == "🔑 BC・アカウント管理":
    st.title("🔑 ビジネスセンター・アカウント管理")

    tab1, tab2 = st.tabs(["BC登録・認証", "アカウント一覧"])

    with tab1:
        st.subheader("ビジネスセンターを追加")
        with st.form("add_bc_form"):
            bc_id = st.text_input("ビジネスセンターID", placeholder="例: 7000000000000000001")
            bc_name = st.text_input("BC名（管理用）", placeholder="例: クライアントA")
            submitted = st.form_submit_button("BCを登録", type="primary")

            if submitted:
                if not bc_id or not bc_name:
                    st.error("BC IDとBC名を入力してください")
                else:
                    try:
                        from tiktok_api.auth import TikTokAuth
                        auth = TikTokAuth()
                        auth.add_business_center(bc_id=bc_id, bc_name=bc_name)
                        st.success(f"✅ {bc_name} を登録しました")
                    except Exception as e:
                        st.error(f"エラー: {e}")

        st.markdown("---")
        st.subheader("OAuth認証")
        st.info("登録したBCごとに認証が必要です。認証URLをクリックしてTikTokで承認してください。")

        try:
            from tiktok_api.auth import TikTokAuth
            auth = TikTokAuth()
            bcs = auth.list_business_centers()

            if not bcs:
                st.warning("BCが登録されていません。上のフォームから追加してください。")
            else:
                for bc in bcs:
                    name = bc.get("name", "")
                    has_token = bool(bc.get("access_token"))
                    status = "✅ 認証済み" if has_token else "❌ 未認証"

                    with st.expander(f"{name}　{status}"):
                        auth_url = auth.get_auth_url(state=name)
                        st.markdown(f"[👉 TikTokで認証する]({auth_url})", unsafe_allow_html=True)
                        st.caption("認証後、リダイレクト先URLに含まれる `auth_code=` の値をコピーして貼り付けてください")

                        with st.form(f"token_form_{name}"):
                            auth_code = st.text_input("auth_code", placeholder="認証後URLから取得したコード")
                            token_submitted = st.form_submit_button("トークンを取得")

                            if token_submitted and auth_code:
                                try:
                                    token_data = auth._exchange_code_for_token(auth_code)
                                    auth._save_token(name, token_data)
                                    st.success("✅ 認証完了！")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"認証失敗: {e}")
        except Exception as e:
            st.error(f"設定読み込みエラー: {e}")

    with tab2:
        st.subheader("広告アカウント一覧")

        try:
            from tiktok_api.auth import TikTokAuth
            from tiktok_api.business import BusinessManager

            auth = TikTokAuth()
            bm = BusinessManager(auth)
            bcs = auth.list_business_centers()

            if not bcs:
                st.warning("BCが登録されていません")
            else:
                selected_bc = st.selectbox("BC選択", [bc["name"] for bc in bcs])

                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("APIから取得", type="primary"):
                        with st.spinner("取得中..."):
                            try:
                                accounts = bm.fetch_ad_accounts(selected_bc)
                                st.success(f"✅ {len(accounts)}件取得")
                                st.rerun()
                            except Exception as e:
                                st.error(f"取得失敗: {e}")

                accounts = bm.list_ad_accounts(selected_bc)
                if accounts:
                    import pandas as pd
                    df = pd.DataFrame(accounts)[["bc_name", "advertiser_id", "name", "status", "currency"]]
                    df.columns = ["BC名", "広告アカウントID", "アカウント名", "ステータス", "通貨"]
                    st.dataframe(df, use_container_width=True)
                else:
                    st.info("「APIから取得」ボタンで広告アカウントを取得してください")

                st.markdown("---")
                st.subheader("手動でアカウントを追加")
                st.caption("APIで取得できないアカウント（他BCから共有されたアカウントなど）を手動で登録できます。")
                with st.form("manual_add_account_form"):
                    col_id, col_name, col_cur = st.columns([3, 3, 1])
                    with col_id:
                        manual_adv_id = st.text_input("広告アカウントID", placeholder="例: 7412345678901234567")
                    with col_name:
                        manual_adv_name = st.text_input("アカウント名（管理用）", placeholder="例: クライアントA")
                    with col_cur:
                        manual_currency = st.selectbox("通貨", ["JPY", "USD"])
                    manual_submitted = st.form_submit_button("追加", type="primary")
                    if manual_submitted:
                        if not manual_adv_id or not manual_adv_name:
                            st.error("アカウントIDとアカウント名を入力してください")
                        else:
                            try:
                                added = bm.add_ad_account_manually(
                                    bc_name=selected_bc,
                                    advertiser_id=manual_adv_id.strip(),
                                    account_name=manual_adv_name.strip(),
                                    currency=manual_currency,
                                )
                                if added:
                                    st.success(f"✅ {manual_adv_name} を追加しました")
                                    st.rerun()
                                else:
                                    st.warning("このアカウントIDは既に登録されています")
                            except Exception as e:
                                st.error(f"追加失敗: {e}")

        except Exception as e:
            st.error(f"エラー: {e}")

# -------------------------------------------------------
# キャンペーン一覧
# -------------------------------------------------------
elif page == "📋 キャンペーン一覧":
    st.title("📋 キャンペーン一覧")

    try:
        import traceback
        from tiktok_api.auth import TikTokAuth
        from tiktok_api.business import BusinessManager
        from tiktok_api.campaign import CampaignManager

        auth = TikTokAuth()
        bm = BusinessManager(auth)
        accounts = bm.list_ad_accounts()

        if not accounts:
            st.warning("広告アカウントが登録されていません。BC・アカウント管理から取得してください。")
        else:
            account_options = {
                f"{a['bc_name']} / {a.get('name') or a.get('advertiser_id', '')}": a
                for a in accounts
            }
            selected = st.selectbox("広告アカウント選択", list(account_options.keys()))
            account = account_options[selected]

            if st.button("キャンペーン取得", type="primary"):
                with st.spinner("取得中..."):
                    try:
                        client = bm.get_client_for_account(
                            advertiser_id=account["advertiser_id"],
                            bc_name=account["bc_name"],
                        )
                        cm = CampaignManager(client)
                        campaigns = cm.list()

                        if campaigns:
                            import pandas as pd
                            df = pd.DataFrame(campaigns)
                            cols = ["campaign_id", "campaign_name", "status", "objective_type", "budget", "budget_mode"]
                            cols = [c for c in cols if c in df.columns]
                            st.dataframe(df[cols], use_container_width=True)
                        else:
                            st.info("キャンペーンがありません")
                        client.close()
                    except Exception as e:
                        st.error(f"取得失敗: {e}")
                        st.code(traceback.format_exc())
    except Exception as e:
        st.error(f"エラー: {e}")
        st.code(traceback.format_exc())

# -------------------------------------------------------
# 一括入稿
# -------------------------------------------------------
elif page == "📤 一括入稿":
    st.title("📤 一括入稿")

    import traceback

    tab_submit, tab_import, tab_monitor, tab_guide = st.tabs(
        ["📊 スプレッドシートから入稿", "📥 Excelインポート", "🔍 APIフィールド変更監視", "📖 使い方"]
    )

    # ===== 使い方 =====
    with tab_guide:
        st.subheader("スプレッドシートの準備")
        st.markdown("""
**① Google スプレッドシートを新規作成し、このツールと共有する**
- サービスアカウント: `tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com`
- 権限: **編集者**（入稿結果をシートに書き戻します）

**② スプレッドシートURLを貼り付けて「テンプレートシートを作成」を実行**
- `入稿データ` という1枚のシートが自動生成されます
- 📁キャンペーン（水色）・📂広告グループ/広告セット（緑）・📄広告（黄）・📊結果（グレー）でセクション色分けされます
- **列名はTikTok広告管理画面のエクスポートExcelと同じ**ため、エクスポートデータをそのままコピー貼り付け可能です
- プルダウン付き列は自動的にドロップダウン選択できます

**③ データ入力方法（3通り）**

📥 **A. Excelインポート（推奨）**
- 「Excelインポート」タブからTikTokエクスポートExcelをアップロード → 自動変換・書き込み

📋 **B. 手動入力**
- 1行 = 広告1件でシートに直接入力
- 同じ「キャンペーン名」を複数行に書いてもキャンペーンは1回だけ作成されます（広告セット名も同様）

🔄 **C. 再入稿（既存データ更新）**
- 「キャンペーンID」「広告セット ID」「広告ID」に既存IDが入っている行はスキップされます
- 新しい広告のみ「広告ID」を空欄にしてください

**④ 「データをプレビュー」→「一括入稿を実行」**
""")

        st.markdown("---")
        st.subheader("📋 シートの列一覧")

        from tiktok_api.sheets import UNIFIED_COLUMNS, SECTION_LABELS, SECTION_COLORS
        import pandas as pd

        prev_section = None
        rows = []
        for col in UNIFIED_COLUMNS:
            section = col["section"]
            if section != prev_section:
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                st.markdown(
                    f"**{SECTION_LABELS[section]}**"
                )
                rows = []
                prev_section = section
            rows.append({
                "列名": col["name"],
                "入力方法": "プルダウン" if col.get("options") else "テキスト入力",
                "選択肢": " / ".join(col["options"]) if col.get("options") else "",
                "メモ": col.get("note", "").replace("\n", " "),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ===== スプレッドシートから入稿 =====
    with tab_submit:
        st.subheader("スプレッドシートから一括入稿")

        # ── アカウント選択 ──
        try:
            from tiktok_api.auth import TikTokAuth
            from tiktok_api.business import BusinessManager

            auth = TikTokAuth()
            bm = BusinessManager(auth)
            accounts = bm.list_ad_accounts()

            if not accounts:
                st.warning("広告アカウントが登録されていません。BC・アカウント管理から取得してください。")
                st.stop()

            account_options = {
                f"{a['bc_name']} / {a.get('name', a['advertiser_id'])}": a
                for a in accounts
            }
            selected_account_key = st.selectbox("入稿先アカウント", list(account_options.keys()))
            selected_account = account_options[selected_account_key]

        except Exception as e:
            st.error(f"アカウント読み込みエラー: {e}")
            st.stop()

        # ── スプレッドシートURL ──
        ss_url = st.text_input(
            "Google スプレッドシートURL",
            placeholder="https://docs.google.com/spreadsheets/d/xxxxx/edit",
        )

        # ── オプション（Slack） ──
        with st.expander("⚙️ オプション設定"):
            slack_webhook = st.text_input(
                "Slack Webhook URL（任意）",
                placeholder="https://hooks.slack.com/services/xxx/xxx/xxx",
                help="入稿完了時にSlack通知を送ります",
            )

        # ── ピクセル・アイデンティティ設定（アカウントごとに保存） ──
        import json
        from pathlib import Path as _Path

        _advertiser_id = selected_account["advertiser_id"]
        _settings_path = _Path("config/pixel_identity_settings.json")
        _settings_path.parent.mkdir(parents=True, exist_ok=True)

        def _load_all_settings() -> dict:
            if _settings_path.exists():
                try:
                    return json.loads(_settings_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return {}

        def _load_pi_settings(advertiser_id: str) -> dict:
            all_data = _load_all_settings()
            return all_data.get(advertiser_id, {"pixels": [], "identities": []})

        def _save_pi_settings(advertiser_id: str, data: dict):
            all_data = _load_all_settings()
            all_data[advertiser_id] = data
            _settings_path.write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")

        pi_settings = _load_pi_settings(_advertiser_id)

        with st.expander("📡 ピクセル・TikTokアカウント設定（プルダウンに表示する項目を登録）"):
            st.caption(
                f"🔑 現在の設定対象アカウント: **{selected_account_key}**（advertiser_id: `{_advertiser_id}`）\n\n"
                "TikTokの広告管理画面から確認できるピクセルIDとTikTokアカウント情報を登録してください。\n"
                "アカウントごとに個別保存されます。"
            )

            col_px, col_id = st.columns(2)

            with col_px:
                st.markdown("**📡 ピクセル**")
                st.caption("形式: `名前,pixel_id`（1行1件）\n例: `メインピクセル,CVCI6QJC77UDL07BVQP0`")
                px_text = "\n".join(
                    f"{p['name']},{p['pixel_id']}" for p in pi_settings.get("pixels", [])
                )
                new_px_text = st.text_area(
                    "ピクセル一覧",
                    value=px_text,
                    height=140,
                    key=f"px_input_{_advertiser_id}",
                    label_visibility="collapsed",
                )

            with col_id:
                st.markdown("**👤 TikTokアカウント（アイデンティティ）**")
                st.caption(
                    "形式: `表示名,identity_id,identity_type`（1行1件）\n"
                    "例: `澤村アカウント,f3fcd787-c94d-5b86-a8d4-49740e624dcd,BC_AUTH_TT`"
                )
                id_text = "\n".join(
                    f"{i['name']},{i['identity_id']},{i['identity_type']}"
                    for i in pi_settings.get("identities", [])
                )
                new_id_text = st.text_area(
                    "アイデンティティ一覧",
                    value=id_text,
                    height=140,
                    key=f"id_input_{_advertiser_id}",
                    label_visibility="collapsed",
                )

            if st.button("💾 設定を保存", key=f"save_pi_{_advertiser_id}"):
                new_pixels = []
                for line in new_px_text.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2 and parts[1]:
                        new_pixels.append({"name": parts[0], "pixel_id": parts[1]})

                new_identities = []
                for line in new_id_text.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2 and parts[1]:
                        new_identities.append({
                            "name": parts[0],
                            "identity_id": parts[1],
                            "identity_type": parts[2] if len(parts) >= 3 else "BC_AUTH_TT",
                        })

                _save_pi_settings(_advertiser_id, {"pixels": new_pixels, "identities": new_identities})
                st.success(
                    f"✅ [{selected_account_key}] に保存しました\n"
                    f"ピクセル {len(new_pixels)}件 / アカウント {len(new_identities)}件"
                )
                pi_settings = {"pixels": new_pixels, "identities": new_identities}

        # 設定からプルダウン選択肢を生成
        _pixel_opts = [
            f"{p['name']} [{p['pixel_id']}]"
            for p in pi_settings.get("pixels", [])
            if p.get("pixel_id")
        ]
        _identity_opts = [
            f"{i['name']} [{i['identity_id']}|{i['identity_type']}]"
            for i in pi_settings.get("identities", [])
            if i.get("identity_id")
        ]

        col_init, col_preview = st.columns(2)

        # テンプレート初期化
        with col_init:
            if st.button("📋 テンプレートシートを作成", disabled=not ss_url):
                with st.spinner("シート作成中..."):
                    try:
                        from tiktok_api.sheets import GoogleSheetsManager
                        creds = dict(st.secrets["gcp_service_account"])
                        gsm = GoogleSheetsManager(ss_url, creds)
                        gsm.initialize_template(
                            pixel_options=_pixel_opts or None,
                            identity_id_options=_identity_opts or None,
                        )
                        msg = "✅ テンプレートシート「入稿データ」を作成しました！\n\n"
                        if _pixel_opts:
                            msg += f"📡 ピクセル {len(_pixel_opts)}件 をプルダウンに追加\n"
                        if _identity_opts:
                            msg += f"👤 TikTokアカウント {len(_identity_opts)}件 をプルダウンに追加\n"
                        msg += "\nスプレッドシートを開いてデータを入力してください。"
                        st.success(msg)
                    except Exception as e:
                        st.error(f"シート作成エラー: {e}")
                        st.code(traceback.format_exc())

        # データプレビュー
        with col_preview:
            if st.button("👁️ データをプレビュー", disabled=not ss_url):
                with st.spinner("データ読み込み中..."):
                    try:
                        from tiktok_api.sheets import GoogleSheetsManager
                        creds = dict(st.secrets["gcp_service_account"])
                        gsm = GoogleSheetsManager(ss_url, creds)
                        df = gsm.read_data()
                        st.session_state["preview_df"] = df
                        st.session_state["preview_ss_url"] = ss_url
                        st.success(f"✅ {len(df)}行 読み込み完了")
                    except Exception as e:
                        st.error(f"データ読み込みエラー: {e}")
                        st.code(traceback.format_exc())

        # プレビュー表示
        if "preview_df" in st.session_state:
            df = st.session_state["preview_df"]

            if df.empty:
                st.warning("データがありません。スプレッドシートに入力してから再度プレビューしてください。")
            else:
                # セクションごとに色分け表示
                from tiktok_api.sheets import UNIFIED_COLUMNS as _COLS
                import pandas as pd

                section_cols = {"campaign": [], "adgroup": [], "ad": [], "result": []}
                for c in _COLS:
                    key = c["name"]
                    if key in df.columns:
                        section_cols[c["section"]].append(key)

                sec_tabs = st.tabs(["📁 キャンペーン", "📂 広告グループ", "📄 広告", "📊 結果"])
                for tab_ui, (section_key, cols) in zip(
                    sec_tabs,
                    [("campaign", section_cols["campaign"]),
                     ("adgroup",  section_cols["adgroup"]),
                     ("ad",       section_cols["ad"]),
                     ("result",   section_cols["result"])],
                ):
                    with tab_ui:
                        show_cols = [c for c in cols if c in df.columns]
                        if show_cols:
                            st.dataframe(df[show_cols], use_container_width=True)
                        else:
                            st.info("データなし")

                st.markdown("---")
                st.info(f"**{len(df)}行** を入稿します（1行 = 広告1件）")

                if st.button("🚀 一括入稿を実行", type="primary"):
                    progress = st.progress(0, text="入稿準備中...")
                    status_box = st.empty()

                    with st.spinner("入稿中... しばらくお待ちください"):
                        try:
                            from tiktok_api.bulk_submission import BulkSubmissionProcessor
                            from tiktok_api.sheets import GoogleSheetsManager

                            client = bm.get_client_for_account(
                                advertiser_id=selected_account["advertiser_id"],
                                bc_name=selected_account["bc_name"],
                            )
                            creds = dict(st.secrets["gcp_service_account"])
                            processor = BulkSubmissionProcessor(client, gcp_credentials=creds)
                            gsm = GoogleSheetsManager(st.session_state["preview_ss_url"], creds)

                            progress.progress(10, text="📁 入稿中...")
                            results = processor.process_unified(df)
                            progress.progress(80, text="📊 結果をシートに書き戻し中...")
                            gsm.write_results([r.to_dict() for r in results])
                            client.close()
                            progress.progress(100, text="完了！")

                            # ── 集計 ──
                            ok      = [r for r in results if r.status == "success"]
                            skipped = [r for r in results if r.status == "skipped"]
                            errors  = [r for r in results if r.status == "error"]

                            if errors:
                                status_box.warning(
                                    f"⚠️ 入稿完了（エラーあり）: "
                                    f"成功 **{len(ok)}件** / スキップ **{len(skipped)}件** / エラー **{len(errors)}件**"
                                )
                            else:
                                status_box.success(
                                    f"✅ 入稿完了！ 成功 **{len(ok)}件** / スキップ **{len(skipped)}件**"
                                )

                            # ── 結果テーブル ──
                            import pandas as pd
                            result_df = pd.DataFrame([{
                                "行": r.row_index,
                                "ステータス": {
                                    "success": "✅ 成功",
                                    "error":   "❌ エラー",
                                    "skipped": "⏭️ スキップ",
                                }.get(r.status, r.status),
                                "キャンペーンID":  r.campaign_id,
                                "広告グループID":  r.adgroup_id,
                                "広告ID":         r.ad_id,
                                "エラー":          r.error,
                            } for r in results])
                            st.dataframe(result_df, use_container_width=True)

                            # ── Slack通知 ──
                            if slack_webhook:
                                try:
                                    from tiktok_api.slack_notifier import SlackNotifier
                                    SlackNotifier(slack_webhook).send_submission_summary(
                                        account_name=selected_account.get("name", selected_account["advertiser_id"]),
                                        campaign_count=len(ok),
                                        adgroup_count=len(ok),
                                        ad_count=len(ok),
                                        error_count=len(errors),
                                    )
                                    st.info("📨 Slack通知送信済み")
                                except Exception as slack_err:
                                    st.warning(f"Slack通知失敗: {slack_err}")

                        except Exception as e:
                            st.error(f"入稿エラー: {e}")
                            st.code(traceback.format_exc())

    # ===== Excelインポート =====
    with tab_import:
        st.subheader("TikTok広告エクスポートExcelをシートにインポート")
        st.info(
            "TikTok広告管理画面からエクスポートしたExcelファイル（「広告」シート）を\n"
            "統合シート形式に変換してスプレッドシートに書き込みます。"
        )

        col_imp1, col_imp2 = st.columns([2, 1])
        with col_imp1:
            ss_url_imp = st.text_input(
                "インポート先スプレッドシートURL",
                placeholder="https://docs.google.com/spreadsheets/d/xxxxx/edit",
                key="import_ss_url",
            )
        with col_imp2:
            append_mode = st.checkbox(
                "既存データに追記する",
                value=False,
                help="OFFの場合は既存データを全削除して上書きします",
            )

        uploaded_file = st.file_uploader(
            "Excelファイルをアップロード（.xlsx）",
            type=["xlsx"],
            key="excel_uploader",
        )

        if uploaded_file is not None:
            import tempfile, os, pandas as pd

            # 一時ファイルに保存
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            try:
                from tiktok_api.excel_importer import convert_excel_to_unified

                with st.spinner("変換中..."):
                    df_imp = convert_excel_to_unified(tmp_path)

                st.success(f"✅ {len(df_imp)}行に変換しました")

                # プレビュー
                from tiktok_api.sheets import UNIFIED_COLUMNS as _IMP_COLS
                sec_tabs_imp = st.tabs(["📁 キャンペーン", "📂 広告グループ", "📄 広告", "📊 結果(既存ID)"])
                section_map = {"campaign": 0, "adgroup": 1, "ad": 2, "result": 3}
                section_col_lists = [[], [], [], []]
                for c in _IMP_COLS:
                    section_col_lists[section_map[c["section"]]].append(c["name"])

                for tab_ui_imp, cols_imp in zip(sec_tabs_imp, section_col_lists):
                    with tab_ui_imp:
                        show = [c for c in cols_imp if c in df_imp.columns]
                        if show:
                            st.dataframe(df_imp[show], use_container_width=True, hide_index=True)

                st.markdown("---")
                st.warning(
                    "⚠️ **動画素材IDについて**: エクスポートExcelには動画IDは含まれていません。\n"
                    "「動画素材ID」列は空欄になっています。\n"
                    "インポート後にスプレッドシートで動画素材IDを入力するか、"
                    "「Google Drive動画URL」列にDriveのURLを入力してください。"
                )
                st.info(
                    "📌 「キャンペーンID」「広告グループID」「広告ID」は既存IDが自動入力されます。\n"
                    "→ **一括入稿を実行するとステータスが「skipped」になり、再入稿はスキップされます。**\n"
                    "→ 新規入稿したい場合はこれらのID列を空欄にしてください。"
                )

                if st.button(
                    "📤 スプレッドシートに書き込む",
                    type="primary",
                    disabled=not ss_url_imp,
                ):
                    with st.spinner("書き込み中..."):
                        try:
                            from tiktok_api.excel_importer import write_to_sheet
                            creds = dict(st.secrets["gcp_service_account"])
                            write_to_sheet(df_imp, ss_url_imp, creds, append=append_mode)
                            st.success(
                                f"✅ {len(df_imp)}行をスプレッドシートに書き込みました！\n\n"
                                "スプレッドシートを開いて内容を確認し、"
                                "「スプレッドシートから入稿」タブから入稿を実行してください。"
                            )
                        except Exception as e:
                            st.error(f"書き込みエラー: {e}")
                            st.code(traceback.format_exc())

            except Exception as e:
                st.error(f"変換エラー: {e}")
                st.code(traceback.format_exc())
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    # ===== APIフィールド変更監視 =====
    with tab_monitor:
        st.subheader("TikTok APIフィールド変更監視")
        st.info(
            "キャンペーン・広告グループ・広告のAPIレスポンスフィールドを記録し、"
            "変更があれば検知します。初回実行でスナップショットを保存し、2回目以降に差分を通知します。"
        )

        try:
            from tiktok_api.auth import TikTokAuth
            from tiktok_api.business import BusinessManager
            from tiktok_api.api_monitor import APIFieldMonitor

            auth = TikTokAuth()
            bm = BusinessManager(auth)
            accounts = bm.list_ad_accounts()

            if not accounts:
                st.warning("広告アカウントが登録されていません")
            else:
                account_options_mon = {
                    f"{a['bc_name']} / {a.get('name', a['advertiser_id'])}": a
                    for a in accounts
                }
                selected_mon = st.selectbox(
                    "チェック対象アカウント",
                    list(account_options_mon.keys()),
                    key="monitor_account",
                )
                account_mon = account_options_mon[selected_mon]

                slack_webhook_mon = st.text_input(
                    "Slack Webhook URL（変更検知時に通知）",
                    placeholder="https://hooks.slack.com/services/xxx/xxx/xxx",
                    key="monitor_slack",
                )

                monitor = APIFieldMonitor()
                snapshot_info = monitor.get_snapshot_info()

                if snapshot_info:
                    st.markdown("**保存済みスナップショット:**")
                    import pandas as pd
                    snap_rows = [
                        {"キー": k, "フィールド数": v["field_count"], "最終更新": v["updated_at"]}
                        for k, v in snapshot_info.items()
                    ]
                    st.dataframe(pd.DataFrame(snap_rows), use_container_width=True, hide_index=True)
                else:
                    st.info("スナップショットはまだありません。「チェック実行」で初回保存します。")

                if st.button("🔍 フィールドチェック実行", type="primary"):
                    with st.spinner("APIチェック中..."):
                        try:
                            client_mon = bm.get_client_for_account(
                                advertiser_id=account_mon["advertiser_id"],
                                bc_name=account_mon["bc_name"],
                            )
                            results_mon = monitor.run_full_check(
                                client=client_mon,
                                bc_name=account_mon["bc_name"],
                                account_name=account_mon.get("name", account_mon["advertiser_id"]),
                                slack_webhook=slack_webhook_mon or None,
                            )
                            client_mon.close()

                            all_changes = [c for changes in results_mon.values() for c in changes]

                            if all_changes:
                                st.warning(f"⚠️ {len(all_changes)}件のフィールド変更を検知！")
                                entity_label = {"campaign": "キャンペーン", "adgroup": "広告グループ", "ad": "広告"}
                                for c in all_changes:
                                    icon = "🆕" if c["type"] == "追加" else "❌"
                                    entity = entity_label.get(c.get("entity", ""), "")
                                    st.markdown(f"{icon} **[{entity}]** `{c['field']}` — {c['detail']}")
                                if slack_webhook_mon:
                                    st.info("📨 Slack通知送信済み")
                            else:
                                st.success("✅ フィールド変更なし")

                        except Exception as e:
                            st.error(f"チェックエラー: {e}")
                            st.code(traceback.format_exc())

        except Exception as e:
            st.error(f"エラー: {e}")
            st.code(traceback.format_exc())

# -------------------------------------------------------
# 複製
# -------------------------------------------------------
elif page == "📋 複製":
    st.title("📋 複製")

    try:
        from tiktok_api.auth import TikTokAuth
        from tiktok_api.business import BusinessManager
        from tiktok_api.duplicate import DuplicateManager

        auth = TikTokAuth()
        bm = BusinessManager(auth)
        accounts = bm.list_ad_accounts()

        if not accounts:
            st.warning("広告アカウントが登録されていません")
        else:
            account_options = {
                f"{a['bc_name']} / {a.get('name', a['advertiser_id'])}": a
                for a in accounts
            }

            tab1, tab2, tab3 = st.tabs(["キャンペーン複製", "広告グループ複製", "広告複製"])

            with tab1:
                st.subheader("キャンペーン複製")
                src_account = st.selectbox("複製元アカウント", list(account_options.keys()), key="camp_src")
                campaign_id = st.text_input("複製元キャンペーンID")
                name_suffix = st.text_input("名前のサフィックス", value="_複製")
                include_adgroups = st.checkbox("広告グループも複製する", value=True)
                include_ads = st.checkbox("広告も複製する", value=True)

                # 複製先アカウント（同一 or 別アカウント）
                dest_same = st.radio("複製先", ["同じアカウント", "別のアカウント"], key="camp_dest_type")
                dest_account_key = src_account
                if dest_same == "別のアカウント":
                    dest_account_key = st.selectbox("複製先アカウント", list(account_options.keys()), key="camp_dst")

                if st.button("複製実行", type="primary", key="camp_dup"):
                    if not campaign_id:
                        st.error("キャンペーンIDを入力してください")
                    else:
                        with st.spinner("複製中..."):
                            try:
                                src = account_options[src_account]
                                dst = account_options[dest_account_key]
                                src_client = bm.get_client_for_account(src["advertiser_id"], src["bc_name"])
                                dst_client = bm.get_client_for_account(dst["advertiser_id"], dst["bc_name"])

                                dm = DuplicateManager(src_client, dst_client)
                                result = dm.duplicate_campaign(
                                    campaign_id=campaign_id,
                                    name_suffix=name_suffix,
                                    include_adgroups=include_adgroups,
                                    include_ads=include_ads,
                                )
                                summary = result.summary()
                                st.success(f"✅ 複製完了！新しいID: {summary['new_id']}")
                                st.json(summary)
                                src_client.close()
                                dst_client.close()
                            except Exception as e:
                                st.error(f"複製失敗: {e}")

            with tab2:
                st.subheader("広告グループ複製")
                src_account_ag = st.selectbox("複製元アカウント", list(account_options.keys()), key="ag_src")
                adgroup_id = st.text_input("複製元広告グループID")
                dest_campaign_id = st.text_input("複製先キャンペーンID")
                name_suffix_ag = st.text_input("名前のサフィックス", value="_複製", key="ag_suffix")
                include_ads_ag = st.checkbox("広告も複製する", value=True, key="ag_ads")

                dest_same_ag = st.radio("複製先", ["同じアカウント", "別のアカウント"], key="ag_dest_type")
                dest_account_ag_key = src_account_ag
                if dest_same_ag == "別のアカウント":
                    dest_account_ag_key = st.selectbox("複製先アカウント", list(account_options.keys()), key="ag_dst")

                if st.button("複製実行", type="primary", key="ag_dup"):
                    if not adgroup_id or not dest_campaign_id:
                        st.error("広告グループIDと複製先キャンペーンIDを入力してください")
                    else:
                        with st.spinner("複製中..."):
                            try:
                                src = account_options[src_account_ag]
                                dst = account_options[dest_account_ag_key]
                                src_client = bm.get_client_for_account(src["advertiser_id"], src["bc_name"])
                                dst_client = bm.get_client_for_account(dst["advertiser_id"], dst["bc_name"])

                                dm = DuplicateManager(src_client, dst_client)
                                result = dm.duplicate_adgroup(
                                    adgroup_id=adgroup_id,
                                    dest_campaign_id=dest_campaign_id,
                                    name_suffix=name_suffix_ag,
                                    include_ads=include_ads_ag,
                                )
                                st.success(f"✅ 複製完了！新しいID: {result.new_id}")
                                st.json(result.summary())
                                src_client.close()
                                dst_client.close()
                            except Exception as e:
                                st.error(f"複製失敗: {e}")

            with tab3:
                st.subheader("広告複製")
                src_account_ad = st.selectbox("複製元アカウント", list(account_options.keys()), key="ad_src")
                ad_id = st.text_input("複製元広告ID")
                dest_adgroup_id = st.text_input("複製先広告グループID")
                name_suffix_ad = st.text_input("名前のサフィックス", value="_複製", key="ad_suffix")

                dest_same_ad = st.radio("複製先", ["同じアカウント", "別のアカウント"], key="ad_dest_type")
                dest_account_ad_key = src_account_ad
                if dest_same_ad == "別のアカウント":
                    dest_account_ad_key = st.selectbox("複製先アカウント", list(account_options.keys()), key="ad_dst")

                if st.button("複製実行", type="primary", key="ad_dup"):
                    if not ad_id or not dest_adgroup_id:
                        st.error("広告IDと複製先広告グループIDを入力してください")
                    else:
                        with st.spinner("複製中..."):
                            try:
                                src = account_options[src_account_ad]
                                dst = account_options[dest_account_ad_key]
                                src_client = bm.get_client_for_account(src["advertiser_id"], src["bc_name"])
                                dst_client = bm.get_client_for_account(dst["advertiser_id"], dst["bc_name"])

                                dm = DuplicateManager(src_client, dst_client)
                                result = dm.duplicate_ad(
                                    ad_id=ad_id,
                                    dest_adgroup_id=dest_adgroup_id,
                                    name_suffix=name_suffix_ad,
                                )
                                st.success(f"✅ 複製完了！新しいID: {result.new_id}")
                                st.json(result.summary())
                                src_client.close()
                                dst_client.close()
                            except Exception as e:
                                st.error(f"複製失敗: {e}")

    except Exception as e:
        st.error(f"エラー: {e}")
