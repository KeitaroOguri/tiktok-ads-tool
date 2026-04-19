"""
TikTok広告 自動運用マネージャー
CPA基準による広告グループの自動ON/OFFツール
"""

from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta

import streamlit as st
from loguru import logger

from tiktok_api.auto_operator import (
    get_rules,
    get_rule,
    create_rule,
    update_rule,
    delete_rule,
    get_logs,
    run_rule_by_id,
    get_all_ad_accounts,
    evaluate_cpa,
    check_token_status,
)
from tiktok_api.adgroup import AdGroupManager
from tiktok_api.client import TikTokClient
from tiktok_api.auto_operator import _get_access_token

JST = timezone(timedelta(hours=9))

st.set_page_config(
    page_title="TikTok 自動運用マネージャー",
    page_icon="⚡",
    layout="wide",
)


# ------------------------------------------------------------------
# スケジューラー（アプリ全体でシングルトン）
# ------------------------------------------------------------------

@st.cache_resource
def _get_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    sched = BackgroundScheduler(timezone="Asia/Tokyo")
    sched.start()
    logger.info("APScheduler 起動")
    return sched


def _sync_scheduler(sched) -> None:
    """ルール設定とスケジューラーを同期する"""
    from tiktok_api.auto_operator import run_rule_by_id
    rules = get_rules()
    current_job_ids = {job.id for job in sched.get_jobs()}
    desired_job_ids: set[str] = set()

    for rule in rules:
        job_id = f"auto_rule_{rule['id']}"
        desired_job_ids.add(job_id)

        if rule.get("enabled"):
            existing = sched.get_job(job_id)
            if existing:
                # インターバルが変わっていれば更新
                try:
                    current_mins = existing.trigger.interval.total_seconds() / 60
                    if abs(current_mins - rule["interval_minutes"]) > 0.1:
                        sched.reschedule_job(
                            job_id,
                            trigger="interval",
                            minutes=rule["interval_minutes"],
                        )
                except Exception:
                    pass
            else:
                sched.add_job(
                    run_rule_by_id,
                    trigger="interval",
                    minutes=rule["interval_minutes"],
                    args=[rule["id"]],
                    id=job_id,
                    replace_existing=True,
                )
        else:
            if job_id in current_job_ids:
                sched.remove_job(job_id)

    # 削除されたルールのジョブを除去
    for job_id in current_job_ids:
        if job_id.startswith("auto_rule_") and job_id not in desired_job_ids:
            sched.remove_job(job_id)


def _get_next_run(sched, rule_id: str) -> str:
    job = sched.get_job(f"auto_rule_{rule_id}")
    if job and job.next_run_time:
        next_run = job.next_run_time.astimezone(JST)
        return next_run.strftime("%H:%M:%S")
    return "—"


# ------------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------------

def _format_dt(iso_str: str | None) -> str:
    if not iso_str:
        return "未実行"
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(JST)
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return iso_str


def _status_badge(enabled: bool) -> str:
    return "🟢 稼働中" if enabled else "⚪ 停止中"


def _action_badge(action: str) -> str:
    return {"DISABLE": "🛑 停止", "ENABLE": "▶️ 再開", "NO_CHANGE": "➖ 変更なし"}.get(action, action)


# ------------------------------------------------------------------
# ページ: ルール一覧
# ------------------------------------------------------------------

def page_rule_list(sched) -> None:
    st.header("ルール一覧")

    rules = get_rules()
    if not rules:
        st.info("ルールがまだありません。「ルール作成」タブから追加してください。")
        return

    for rule in rules:
        rule_id = rule["id"]
        enabled = rule.get("enabled", False)

        with st.container(border=True):
            col_title, col_badge, col_toggle, col_run, col_del = st.columns(
                [4, 2, 2, 2, 1]
            )

            with col_title:
                st.markdown(f"**{rule['name']}**")
                st.caption(
                    f"アカウント: {rule['account_name']}　"
                    f"tCPA: {rule['tcpa_target']:,}円　"
                    f"間隔: {rule['interval_minutes']}分"
                )
                st.caption(
                    f"最終実行: {_format_dt(rule.get('last_run_at'))}　"
                    f"次回: {_get_next_run(sched, rule_id)}　"
                    f"結果: {rule.get('last_run_summary') or '—'}"
                )
                # トークン有効期限チェック
                token_status = check_token_status(rule["advertiser_id"])
                if not token_status["ok"]:
                    st.warning(f"⚠️ トークン: {token_status['message']}")

            with col_badge:
                st.markdown(f"<br>{_status_badge(enabled)}", unsafe_allow_html=True)

            with col_toggle:
                btn_label = "⏸ 停止" if enabled else "▶️ 起動"
                if st.button(btn_label, key=f"toggle_{rule_id}"):
                    update_rule(rule_id, enabled=not enabled)
                    _sync_scheduler(sched)
                    st.rerun()

            with col_run:
                if st.button("⚡ 今すぐ実行", key=f"run_{rule_id}"):
                    with st.spinner("実行中..."):
                        result = run_rule_by_id(rule_id)
                    if result and not result.get("error"):
                        st.success(result["summary"])
                    elif result:
                        st.error(result["summary"])
                    st.rerun()

            with col_del:
                if st.button("🗑", key=f"del_{rule_id}", help="ルールを削除"):
                    _sync_scheduler(sched)  # ジョブ削除
                    delete_rule(rule_id)
                    _sync_scheduler(sched)
                    st.rerun()


# ------------------------------------------------------------------
# ページ: ルール作成
# ------------------------------------------------------------------

def page_create_rule(sched) -> None:
    st.header("ルール作成")

    accounts = get_all_ad_accounts()
    if not accounts:
        st.warning("広告アカウントが見つかりません。入稿ツールでBCを認証してください。")
        return

    account_options = {
        f"{a['bc_name']} / {a['name']} ({a['advertiser_id']})": a
        for a in accounts
    }

    with st.form("create_rule_form"):
        st.subheader("基本設定")
        col1, col2 = st.columns(2)
        with col1:
            rule_name = st.text_input("ルール名", placeholder="例: クライアントA CPA自動管理")
            selected_account_label = st.selectbox("対象アカウント", list(account_options.keys()))
        with col2:
            tcpa_target = st.number_input(
                "tCPA目標（円）",
                min_value=1,
                value=7000,
                step=500,
                help="この金額を消化するごとに1CV必要。未達なら広告グループを停止します。",
            )
            interval_minutes = st.selectbox(
                "チェック間隔",
                [15, 30, 60],
                format_func=lambda x: f"{x}分ごと",
            )

        st.subheader("対象絞り込み（任意）")
        st.caption("空欄の場合はアカウント内の全広告グループが対象になります。")
        col3, col4 = st.columns(2)
        with col3:
            campaign_ids_input = st.text_area(
                "対象キャンペーンID（1行1ID）",
                placeholder="空欄 = 全キャンペーン",
                height=100,
            )
        with col4:
            adgroup_ids_input = st.text_area(
                "対象広告グループID（1行1ID）",
                placeholder="空欄 = 全広告グループ",
                height=100,
            )

        st.subheader("通知設定")
        slack_webhook = st.text_input(
            "Slack Webhook URL（任意）",
            placeholder="https://hooks.slack.com/services/...",
        )

        submitted = st.form_submit_button("ルールを作成", type="primary")

        if submitted:
            if not rule_name:
                st.error("ルール名を入力してください")
            else:
                account = account_options[selected_account_label]
                campaign_ids = [
                    c.strip() for c in campaign_ids_input.splitlines() if c.strip()
                ]
                adgroup_ids = [
                    a.strip() for a in adgroup_ids_input.splitlines() if a.strip()
                ]

                create_rule(
                    name=rule_name,
                    advertiser_id=account["advertiser_id"],
                    account_name=account["name"],
                    tcpa_target=float(tcpa_target),
                    interval_minutes=int(interval_minutes),
                    target_adgroup_ids=adgroup_ids or [],
                    campaign_ids=campaign_ids or [],
                    slack_webhook_url=slack_webhook,
                )
                st.success(f"✅ ルール「{rule_name}」を作成しました。ルール一覧からONにして起動してください。")
                st.rerun()

    # CPA判定シミュレーター
    st.divider()
    st.subheader("CPA判定シミュレーター")
    st.caption("ルールの動作を確認できます。")
    sim_col1, sim_col2, sim_col3 = st.columns(3)
    with sim_col1:
        sim_spend = st.number_input("消化額（円）", min_value=0, value=14000, step=1000, key="sim_spend")
    with sim_col2:
        sim_cv = st.number_input("CV数", min_value=0, value=1, step=1, key="sim_cv")
    with sim_col3:
        sim_tcpa = st.number_input("tCPA目標（円）", min_value=1, value=7000, step=500, key="sim_tcpa")

    if sim_spend > 0:
        import math
        action = evaluate_cpa(sim_spend, int(sim_cv), float(sim_tcpa))
        required = math.floor(sim_spend / sim_tcpa) if sim_tcpa > 0 else 0
        cpa_now = sim_spend / sim_cv if sim_cv > 0 else None

        if action == "DISABLE":
            st.error(
                f"🛑 **停止** — 消化額 {sim_spend:,}円 に対し {required}CV 必要ですが {sim_cv}CV のみ"
            )
        elif action == "ENABLE":
            cpa_str = f"（現在CPA {cpa_now:,.0f}円）" if cpa_now else ""
            st.success(f"▶️ **配信継続/再開** — {required}CV 以上達成 {cpa_str}")
        else:
            st.info(f"➖ **変更なし** — まだ {sim_tcpa:,}円 未消化のため判定対象外")


# ------------------------------------------------------------------
# ページ: 実行ログ
# ------------------------------------------------------------------

def page_logs() -> None:
    st.header("実行ログ")

    logs = get_logs(limit=100)
    if not logs:
        st.info("実行ログはまだありません。")
        return

    col_filter1, col_filter2 = st.columns([3, 1])
    with col_filter2:
        only_changes = st.checkbox("変更あり のみ表示", value=False)

    if only_changes:
        logs = [
            lg for lg in logs
            if any(r.get("action") in ("DISABLE", "ENABLE") for r in lg.get("results", []))
        ]

    for log in logs:
        ts = _format_dt(log.get("timestamp"))
        rule_name = log.get("rule_name", "")
        summary = log.get("summary", "")
        has_error = bool(log.get("error"))

        icon = "❌" if has_error else (
            "⚡" if "停止: 0件 / 再開: 0件" not in summary else "➖"
        )

        label = f"{icon} {ts}　{rule_name}　{summary}"
        with st.expander(label, expanded=False):
            if has_error:
                st.error(f"エラー: {log['error']}")

            results = log.get("results", [])
            if results:
                import pandas as pd
                rows = []
                for r in results:
                    rows.append({
                        "広告グループ": r.get("adgroup_name", r.get("adgroup_id", "")),
                        "消化額": f"{r.get('spend', 0):,.0f}円",
                        "CV数": r.get("conversions", 0),
                        "ステータス": r.get("current_status", ""),
                        "アクション": _action_badge(r.get("action", "")),
                        "理由": r.get("reason", ""),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------
# ページ: アカウント管理
# ------------------------------------------------------------------

def page_account_management() -> None:
    st.header("アカウント管理")

    try:
        from tiktok_api.auth import TikTokAuth
        from tiktok_api.business import BusinessManager
        auth = TikTokAuth()
        bm = BusinessManager(auth)
    except Exception as e:
        st.error(f"初期化エラー: {e}")
        return

    tab1, tab2 = st.tabs(["BC登録・認証", "アカウント一覧"])

    with tab1:
        st.subheader("ビジネスセンターを追加")
        with st.form("add_bc_form"):
            bc_id = st.text_input("ビジネスセンターID", placeholder="例: 7000000000000000001")
            bc_name = st.text_input("BC名（管理用）", placeholder="例: クライアントA")
            if st.form_submit_button("BCを登録", type="primary"):
                if not bc_id or not bc_name:
                    st.error("BC IDとBC名を入力してください")
                else:
                    try:
                        auth.add_business_center(bc_id=bc_id, bc_name=bc_name)
                        st.success(f"✅ {bc_name} を登録しました")
                        st.rerun()
                    except Exception as e:
                        st.error(f"エラー: {e}")

        st.divider()
        st.subheader("OAuth認証")
        st.info(
            "認証URLを開いてTikTokで承認 → リダイレクト先URLの `auth_code=` の値をコピーして貼り付けてください"
        )

        try:
            bcs = auth.list_business_centers()
            if not bcs:
                st.warning("BCが登録されていません。上から追加してください。")
            else:
                for bc in bcs:
                    name = bc.get("name", "")
                    has_token = bool(bc.get("access_token"))
                    expires_at = bc.get("token_expires_at", "")
                    status_label = "✅ 認証済み" if has_token else "❌ 未認証"
                    if has_token and expires_at:
                        try:
                            exp = datetime.fromisoformat(expires_at)
                            if exp.tzinfo is None:
                                from datetime import timezone as tz_
                                exp = exp.replace(tzinfo=JST)
                            remaining_h = (exp - datetime.now(JST)).total_seconds() / 3600
                            if remaining_h < 0:
                                status_label = "⚠️ 期限切れ"
                            elif remaining_h < 24:
                                status_label = f"⚠️ 残り{remaining_h:.0f}時間"
                        except Exception:
                            pass

                    with st.expander(f"{name}　{status_label}"):
                        auth_url = auth.get_auth_url(state=name)
                        st.markdown(f"[👉 TikTokで認証する]({auth_url})")
                        with st.form(f"token_form_{name}"):
                            auth_code = st.text_input("auth_code", placeholder="URLから取得したコード")
                            if st.form_submit_button("トークンを取得"):
                                if auth_code:
                                    try:
                                        token_data = auth._exchange_code_for_token(auth_code.strip())
                                        auth._save_token(name, token_data)
                                        st.success("✅ 認証完了")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"失敗: {e}")
        except Exception as e:
            st.error(f"エラー: {e}")

    with tab2:
        st.subheader("広告アカウント一覧")
        try:
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
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("「APIから取得」ボタンで広告アカウントを取得してください")

                st.divider()
                st.subheader("手動でアカウントを追加")
                st.caption("APIで取得できないアカウントを手動で登録できます。")
                with st.form("manual_add_account"):
                    c1, c2, c3 = st.columns([3, 3, 1])
                    with c1:
                        m_id = st.text_input("広告アカウントID", placeholder="例: 7412345678901234567")
                    with c2:
                        m_name = st.text_input("アカウント名（管理用）", placeholder="例: クライアントA")
                    with c3:
                        m_cur = st.selectbox("通貨", ["JPY", "USD"])
                    if st.form_submit_button("追加", type="primary"):
                        if not m_id or not m_name:
                            st.error("IDと名前を入力してください")
                        else:
                            try:
                                added = bm.add_ad_account_manually(
                                    bc_name=selected_bc,
                                    advertiser_id=m_id.strip(),
                                    account_name=m_name.strip(),
                                    currency=m_cur,
                                )
                                if added:
                                    st.success(f"✅ {m_name} を追加しました")
                                    st.rerun()
                                else:
                                    st.warning("このアカウントIDは既に登録されています")
                            except Exception as e:
                                st.error(f"失敗: {e}")
        except Exception as e:
            st.error(f"エラー: {e}")


# ------------------------------------------------------------------
# ページ: 設定
# ------------------------------------------------------------------

def page_settings(sched) -> None:
    st.header("設定")

    # スケジューラーの状態
    st.subheader("スケジューラー状態")
    jobs = sched.get_jobs()
    if jobs:
        st.success(f"🟢 スケジューラー稼働中 — {len(jobs)}件のジョブが登録されています")
        rows = []
        for job in jobs:
            next_run = (
                job.next_run_time.astimezone(JST).strftime("%m/%d %H:%M:%S")
                if job.next_run_time
                else "—"
            )
            rows.append({"ジョブID": job.id, "次回実行": next_run})
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("稼働中のジョブはありません。ルール一覧からルールをONにしてください。")

    st.divider()
    st.subheader("ルールの手動同期")
    st.caption("スケジューラーのジョブとルール設定を強制的に同期します。")
    if st.button("🔄 今すぐ同期"):
        _sync_scheduler(sched)
        st.success("同期完了")
        st.rerun()


# ------------------------------------------------------------------
# メインレイアウト
# ------------------------------------------------------------------

def _check_password() -> bool:
    """環境変数 APP_PASSWORD が設定されている場合のみパスワード認証を行う"""
    password = os.environ.get("APP_PASSWORD", "")
    if not password:
        return True  # 未設定なら認証スキップ（ローカル開発用）

    if st.session_state.get("authenticated"):
        return True

    st.title("⚡ TikTok 自動運用マネージャー")
    with st.form("login_form"):
        entered = st.text_input("パスワード", type="password")
        if st.form_submit_button("ログイン", type="primary"):
            if entered == password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("パスワードが違います")
    return False


def main():
    if not _check_password():
        return

    sched = _get_scheduler()
    _sync_scheduler(sched)  # ページロードごとに同期

    # サイドバー
    st.sidebar.title("⚡ 自動運用マネージャー")
    st.sidebar.markdown("---")

    # スケジューラー状態をサイドバーに表示
    rules = get_rules()
    active_rules = [r for r in rules if r.get("enabled")]
    if active_rules:
        st.sidebar.success(f"🟢 {len(active_rules)}件稼働中")
    else:
        st.sidebar.info("⚪ 稼働中のルールなし")

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "現在時刻: " + datetime.now(JST).strftime("%m/%d %H:%M:%S")
    )

    page = st.sidebar.radio(
        "メニュー",
        ["📋 ルール一覧", "➕ ルール作成", "📊 実行ログ", "🔑 アカウント管理", "⚙️ 設定"],
    )

    if page == "📋 ルール一覧":
        page_rule_list(sched)
    elif page == "➕ ルール作成":
        page_create_rule(sched)
    elif page == "📊 実行ログ":
        page_logs()
    elif page == "🔑 アカウント管理":
        page_account_management()
    elif page == "⚙️ 設定":
        page_settings(sched)


if __name__ == "__main__":
    main()
else:
    main()
