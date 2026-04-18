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

    tab_submit, tab_monitor, tab_guide = st.tabs(
        ["📊 スプレッドシートから入稿", "🔍 APIフィールド変更監視", "📖 使い方"]
    )

    # ===== 使い方 =====
    with tab_guide:
        st.subheader("スプレッドシートの準備")
        st.markdown("""
**① Google スプレッドシートを新規作成し、このツールと共有する**
- サービスアカウント: `tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com`
- 権限: **編集者**（入稿結果をシートに書き戻します）

**② スプレッドシートURLを貼り付けて「テンプレート初期化」を実行**
- 3つのシート（キャンペーン・広告グループ・広告）が自動作成されます

**③ 各シートにデータを入力**
""")

        with st.expander("📋 キャンペーンシートの列"):
            st.markdown("""
| 列名 | 説明 | 例 |
|------|------|----|
| キャンペーン名 | 必須 | 夏のキャンペーン |
| 目標タイプ | リーチ / トラフィック / 動画視聴 / コンバージョン / アプリインストール | トラフィック |
| 予算タイプ | 無制限 / 日予算 / 総予算 | 日予算 |
| 予算 | 数値（予算タイプが無制限の場合は空） | 5000 |
| ステータス | 自動入力（入稿結果） | |
| 作成済みID | 自動入力 or 既存IDを手入力するとスキップ | |
| エラー内容 | 自動入力 | |
""")

        with st.expander("📋 広告グループシートの列"):
            st.markdown("""
| 列名 | 説明 | 例 |
|------|------|----|
| キャンペーン名 | キャンペーンシートの名前と一致させる | 夏のキャンペーン |
| 広告グループ名 | 必須 | 男性30代向け |
| 配置タイプ | 自動 / 手動 | 自動 |
| 予算タイプ | 無制限 / 日予算 / 総予算 | 日予算 |
| 日予算 | 数値 | 2000 |
| スケジュール | 開始日から / 期間指定 | 開始日から |
| 開始日時 | YYYY-MM-DD HH:MM:SS | 2024-07-01 00:00:00 |
| 終了日時 | 期間指定時のみ | 2024-07-31 23:59:59 |
| 最適化目標 | クリック / リーチ / コンバージョン / 動画再生 | クリック |
| 入札タイプ | 自動入札 / カスタム | 自動入札 |
| 入札価格 | カスタム入札時のみ数値 | |
| ターゲット地域 | 地域IDをカンマ区切り | |
| 年齢層 | AGE_18_24,AGE_25_34 等カンマ区切り | |
| 性別 | すべて / 男性 / 女性 | すべて |
""")

        with st.expander("📋 広告シートの列"):
            st.markdown("""
| 列名 | 説明 | 例 |
|------|------|----|
| 広告グループ名 | 広告グループシートの名前と一致させる | 男性30代向け |
| 広告名 | 必須 | 夏の広告_動画A |
| 広告フォーマット | SINGLE_VIDEO / IMAGE | SINGLE_VIDEO |
| 動画素材ID | TikTok上のvideo_id | 7xxx...xxx |
| サムネイル素材ID | TikTok上のimage_id | |
| 広告テキスト | 広告の説明テキスト | 夏のセール開催中！ |
| CTA | 詳しくはこちら / 今すぐ購入 / 今すぐ登録 等 | 詳しくはこちら |
| ランディングURL | https://... | https://example.com |
| 表示名 | ブランド名など | MyBrand |
""")

    # ===== スプレッドシートから入稿 =====
    with tab_submit:
        st.subheader("スプレッドシートから一括入稿")

        # アカウント選択
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

        # スプレッドシートURL
        ss_url = st.text_input(
            "Google スプレッドシートURL",
            placeholder="https://docs.google.com/spreadsheets/d/xxxxx/edit",
        )

        # Slack Webhook（オプション）
        with st.expander("⚙️ オプション設定"):
            slack_webhook = st.text_input(
                "Slack Webhook URL（任意）",
                placeholder="https://hooks.slack.com/services/xxx/xxx/xxx",
                help="入稿完了時にSlack通知を送ります",
            )

        col_init, col_preview = st.columns(2)

        # テンプレート初期化
        with col_init:
            if st.button("📋 テンプレートシートを作成", disabled=not ss_url):
                if not ss_url:
                    st.error("スプレッドシートURLを入力してください")
                else:
                    with st.spinner("シート作成中..."):
                        try:
                            from tiktok_api.sheets import GoogleSheetsManager
                            creds = dict(st.secrets["gcp_service_account"])
                            gsm = GoogleSheetsManager(ss_url, creds)
                            gsm.initialize_template()
                            st.success("✅ テンプレートシートを作成しました。スプレッドシートにデータを入力してください。")
                        except Exception as e:
                            st.error(f"シート作成エラー: {e}")
                            st.code(traceback.format_exc())

        # プレビュー
        with col_preview:
            if st.button("👁️ データをプレビュー", disabled=not ss_url):
                if not ss_url:
                    st.error("スプレッドシートURLを入力してください")
                else:
                    with st.spinner("データ読み込み中..."):
                        try:
                            from tiktok_api.sheets import GoogleSheetsManager
                            creds = dict(st.secrets["gcp_service_account"])
                            gsm = GoogleSheetsManager(ss_url, creds)

                            df_c = gsm.read_campaigns()
                            df_ag = gsm.read_adgroups()
                            df_ad = gsm.read_ads()

                            st.session_state["preview_campaigns"] = df_c
                            st.session_state["preview_adgroups"] = df_ag
                            st.session_state["preview_ads"] = df_ad
                            st.session_state["preview_ss_url"] = ss_url
                            st.success(f"✅ 読み込み完了: キャンペーン{len(df_c)}件 / 広告グループ{len(df_ag)}件 / 広告{len(df_ad)}件")
                        except Exception as e:
                            st.error(f"データ読み込みエラー: {e}")
                            st.code(traceback.format_exc())

        # プレビュー表示
        if "preview_campaigns" in st.session_state:
            df_c = st.session_state["preview_campaigns"]
            df_ag = st.session_state["preview_adgroups"]
            df_ad = st.session_state["preview_ads"]

            p1, p2, p3 = st.tabs(["キャンペーン", "広告グループ", "広告"])
            with p1:
                st.dataframe(df_c, use_container_width=True)
            with p2:
                st.dataframe(df_ag, use_container_width=True)
            with p3:
                st.dataframe(df_ad, use_container_width=True)

            total = len(df_c) + len(df_ag) + len(df_ad)
            st.markdown("---")

            if total == 0:
                st.warning("入稿するデータがありません。スプレッドシートにデータを入力してください。")
            else:
                st.info(f"合計 **{total}件** を入稿します（キャンペーン{len(df_c)} / 広告グループ{len(df_ag)} / 広告{len(df_ad)}）")

                if st.button("🚀 一括入稿を実行", type="primary"):
                    with st.spinner("入稿中... しばらくお待ちください"):
                        try:
                            from tiktok_api.bulk_submission import BulkSubmissionProcessor
                            from tiktok_api.sheets import GoogleSheetsManager, SHEET_CAMPAIGNS, SHEET_ADGROUPS, SHEET_ADS

                            client = bm.get_client_for_account(
                                advertiser_id=selected_account["advertiser_id"],
                                bc_name=selected_account["bc_name"],
                            )
                            processor = BulkSubmissionProcessor(client)
                            creds = dict(st.secrets["gcp_service_account"])
                            gsm = GoogleSheetsManager(
                                st.session_state["preview_ss_url"], creds
                            )

                            # --- キャンペーン ---
                            st.write("📁 キャンペーンを作成中...")
                            c_results, campaign_name_to_id = processor.process_campaigns(df_c)
                            gsm.write_results(SHEET_CAMPAIGNS, [r.to_dict() for r in c_results])

                            # --- 広告グループ ---
                            st.write("📂 広告グループを作成中...")
                            ag_results, adgroup_name_to_id = processor.process_adgroups(df_ag, campaign_name_to_id)
                            gsm.write_results(SHEET_ADGROUPS, [r.to_dict() for r in ag_results])

                            # --- 広告 ---
                            st.write("📄 広告を作成中...")
                            ad_results = processor.process_ads(df_ad, adgroup_name_to_id)
                            gsm.write_results(SHEET_ADS, [r.to_dict() for r in ad_results])

                            client.close()

                            # --- 結果集計 ---
                            all_results = c_results + ag_results + ad_results
                            ok = [r for r in all_results if r.status == "success"]
                            skipped = [r for r in all_results if r.status == "skipped"]
                            errors = [r for r in all_results if r.status == "error"]

                            if errors:
                                st.warning(f"⚠️ 入稿完了（エラーあり）: 成功{len(ok)}件 / スキップ{len(skipped)}件 / エラー{len(errors)}件")
                            else:
                                st.success(f"✅ 入稿完了！ 成功{len(ok)}件 / スキップ{len(skipped)}件")

                            # 結果テーブル
                            import pandas as pd
                            result_df = pd.DataFrame([{
                                "種別": {"campaign": "キャンペーン", "adgroup": "広告グループ", "ad": "広告"}.get(r.entity_type, r.entity_type),
                                "名前": r.name,
                                "ステータス": {"success": "✅ 成功", "error": "❌ エラー", "skipped": "⏭️ スキップ"}.get(r.status, r.status),
                                "作成ID": r.created_id,
                                "エラー": r.error,
                            } for r in all_results])
                            st.dataframe(result_df, use_container_width=True)

                            # Slack通知
                            if slack_webhook:
                                try:
                                    from tiktok_api.slack_notifier import SlackNotifier
                                    notifier = SlackNotifier(slack_webhook)
                                    c_ok = sum(1 for r in c_results if r.status == "success")
                                    ag_ok = sum(1 for r in ag_results if r.status == "success")
                                    ad_ok = sum(1 for r in ad_results if r.status == "success")
                                    notifier.send_submission_summary(
                                        account_name=selected_account.get("name", selected_account["advertiser_id"]),
                                        campaign_count=c_ok,
                                        adgroup_count=ag_ok,
                                        ad_count=ad_ok,
                                        error_count=len(errors),
                                    )
                                    st.info("📨 Slack通知送信済み")
                                except Exception as slack_err:
                                    st.warning(f"Slack通知失敗: {slack_err}")

                        except Exception as e:
                            st.error(f"入稿エラー: {e}")
                            st.code(traceback.format_exc())

    # ===== APIフィールド変更監視 =====
    with tab_monitor:
        st.subheader("TikTok APIフィールド変更監視")
        st.info(
            "広告アカウントのキャンペーン・広告グループ・広告のAPIレスポンスフィールドを記録し、"
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
                    snap_rows = []
                    for k, v in snapshot_info.items():
                        snap_rows.append({
                            "キー": k,
                            "フィールド数": v["field_count"],
                            "最終更新": v["updated_at"],
                        })
                    import pandas as pd
                    st.dataframe(pd.DataFrame(snap_rows), use_container_width=True)
                else:
                    st.info("スナップショットはまだありません。「チェック実行」で初回スナップショットを保存します。")

                if st.button("🔍 フィールドチェック実行", type="primary"):
                    with st.spinner("APIチェック中..."):
                        try:
                            client_mon = bm.get_client_for_account(
                                advertiser_id=account_mon["advertiser_id"],
                                bc_name=account_mon["bc_name"],
                            )
                            bc_name_mon = account_mon["bc_name"]
                            acc_name_mon = account_mon.get("name", account_mon["advertiser_id"])

                            results_mon = monitor.run_full_check(
                                client=client_mon,
                                bc_name=bc_name_mon,
                                account_name=acc_name_mon,
                                slack_webhook=slack_webhook_mon or None,
                            )
                            client_mon.close()

                            all_changes = [c for changes in results_mon.values() for c in changes]

                            if all_changes:
                                st.warning(f"⚠️ {len(all_changes)}件のフィールド変更を検知しました！")
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
