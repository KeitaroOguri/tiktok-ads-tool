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
        st.info("**Step 2**\n\nExcelテンプレートに入稿データを記入")
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
# 一括入稿（準備中）
# -------------------------------------------------------
elif page == "📤 一括入稿":
    st.title("📤 一括入稿")
    st.info("🚧 このページは次のフェーズで実装予定です")

    st.markdown("""
    **実装予定の機能:**
    - Excelテンプレートのダウンロード
    - キャンペーン〜広告の一括作成
    - 動画ファイルの一括アップロード
    - 入稿結果レポート出力
    """)

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
