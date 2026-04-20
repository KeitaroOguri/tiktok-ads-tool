"""
TikTok広告 自動運用エンジン - CPA基準による広告グループON/OFF

ルール:
  floor(消化額 / tCPA目標) > CV数 のとき → 停止
  停止済みグループに遅れてCVが入り上記条件を満たさなくなったとき → 再開
"""

from __future__ import annotations
import json
import math
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from .client import TikTokClient
from .adgroup import AdGroupManager
from .reporting import ReportingManager
from .slack_notifier import SlackNotifier

JST = timezone(timedelta(hours=9))

RULES_PATH = Path(__file__).parent.parent / "config" / "auto_rules.json"
LOGS_PATH = Path(__file__).parent.parent / "config" / "auto_logs.json"
ACCOUNTS_PATH = Path(__file__).parent.parent / "config" / "accounts.yaml"

MAX_LOGS = 300


# ------------------------------------------------------------------
# JSON永続化ヘルパー
# ------------------------------------------------------------------

def _load_rules() -> dict:
    if RULES_PATH.exists():
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return {"rules": []}


def _save_rules(data: dict) -> None:
    RULES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_logs() -> list[dict]:
    if LOGS_PATH.exists():
        return json.loads(LOGS_PATH.read_text(encoding="utf-8")).get("logs", [])
    return []


def _save_logs(logs: list[dict]) -> None:
    LOGS_PATH.write_text(
        json.dumps({"logs": logs[-MAX_LOGS:]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ------------------------------------------------------------------
# ルール CRUD
# ------------------------------------------------------------------

def get_rules() -> list[dict]:
    return _load_rules().get("rules", [])


def get_rule(rule_id: str) -> Optional[dict]:
    return next((r for r in get_rules() if r["id"] == rule_id), None)


def create_rule(
    name: str,
    advertiser_id: str,
    account_name: str,
    tcpa_target: float,
    interval_minutes: int = 15,
    target_adgroup_ids: Optional[list[str]] = None,
    campaign_ids: Optional[list[str]] = None,
    slack_webhook_url: str = "",
) -> dict:
    data = _load_rules()
    rule: dict = {
        "id": str(uuid.uuid4()),
        "name": name,
        "enabled": False,
        "advertiser_id": advertiser_id,
        "account_name": account_name,
        "tcpa_target": tcpa_target,
        "interval_minutes": interval_minutes,
        "target_adgroup_ids": target_adgroup_ids or [],
        "campaign_ids": campaign_ids or [],
        "slack_webhook_url": slack_webhook_url,
        "created_at": datetime.now(JST).isoformat(),
        "last_run_at": None,
        "last_run_summary": None,
        # ルールが停止させた広告グループIDを記録（手動停止との区別用）
        "_rule_stopped_ids": [],
        # 日次リセット管理（評価は1日単位）
        "_last_reset_date": None,
        # トークン期限切れ警告の最終送信日時（連続通知防止）
        "_token_warn_sent_at": None,
    }
    data["rules"].append(rule)
    _save_rules(data)
    logger.info(f"ルール作成: {name}")
    return rule


def update_rule(rule_id: str, **kwargs) -> bool:
    data = _load_rules()
    for rule in data["rules"]:
        if rule["id"] == rule_id:
            rule.update(kwargs)
            _save_rules(data)
            return True
    return False


def delete_rule(rule_id: str) -> bool:
    data = _load_rules()
    before = len(data["rules"])
    data["rules"] = [r for r in data["rules"] if r["id"] != rule_id]
    if len(data["rules"]) < before:
        _save_rules(data)
        return True
    return False


def get_logs(limit: int = 50) -> list[dict]:
    logs = _load_logs()
    return list(reversed(logs))[:limit]


# ------------------------------------------------------------------
# CPA評価ロジック
# ------------------------------------------------------------------

def evaluate_cpa(spend: float, conversions: int, tcpa_target: float) -> str:
    """
    CPA基準でアクションを返す
    Returns: 'DISABLE' | 'ENABLE' | 'NO_CHANGE'

    ルール: tCPA × (CV数+1) を消化しても次のCVがなければ停止
           = floor(消化額 / tCPA) > CV数 のとき停止
    """
    if spend <= 0 or tcpa_target <= 0:
        return "NO_CHANGE"

    if conversions == 0:
        # 1CVも取れていないのにtCPA分消化 → 停止
        return "DISABLE" if spend >= tcpa_target else "NO_CHANGE"

    required_cvs = math.floor(spend / tcpa_target)
    if required_cvs > conversions:
        return "DISABLE"
    # CV数が基準を満たしている → 再開候補（現状がDISABLEなら再開）
    return "ENABLE"


def _build_reason(spend: float, conversions: int, tcpa_target: float, action: str) -> str:
    if action == "DISABLE":
        required = math.floor(spend / tcpa_target) if tcpa_target > 0 else 0
        return f"消化額{spend:,.0f}円 / {conversions}CV → {required}CV必要なため停止"
    if action == "ENABLE":
        cpa = spend / conversions if conversions > 0 else 0
        return f"消化額{spend:,.0f}円 / {conversions}CV (CPA {cpa:,.0f}円) → 基準内のため再開"
    return "変更なし"


# ------------------------------------------------------------------
# アカウント情報
# ------------------------------------------------------------------

def _get_access_token(advertiser_id: str) -> Optional[str]:
    """
    accounts.yaml から advertiser_id に対応する access_token を返す。
    期限切れ間近の場合は refresh_token で自動更新する。
    refresh_token が空の場合は期限切れでも生トークンを返し、
    呼び出し元でAPIエラーとして検知させる。
    """
    if not ACCOUNTS_PATH.exists():
        return None
    config = yaml.safe_load(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    for bc in config.get("business_centers", []):
        for acc in bc.get("ad_accounts", []):
            if str(acc.get("advertiser_id")) != str(advertiser_id):
                continue
            bc_name = bc.get("name", "")
            refresh_token = bc.get("refresh_token", "")
            # refresh_token がある場合は TikTokAuth 経由で有効期限を自動チェック
            if refresh_token:
                try:
                    from .auth import TikTokAuth
                    auth = TikTokAuth()
                    return auth.get_valid_token(bc_name)
                except Exception as e:
                    logger.warning(f"トークン自動更新失敗 ({bc_name}): {e} → 生トークンで試行")
            return bc.get("access_token")
    return None


def check_token_status(advertiser_id: str) -> dict:
    """
    advertiser_id に対応するトークンの有効期限状態を返す
    Returns: {"ok": bool, "expires_at": str, "message": str}
    """
    if not ACCOUNTS_PATH.exists():
        return {"ok": False, "expires_at": None, "message": "accounts.yaml が見つかりません"}
    config = yaml.safe_load(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    for bc in config.get("business_centers", []):
        for acc in bc.get("ad_accounts", []):
            if str(acc.get("advertiser_id")) != str(advertiser_id):
                continue
            expires_at_str = bc.get("token_expires_at", "")
            has_refresh = bool(bc.get("refresh_token", ""))
            if not expires_at_str:
                return {"ok": True, "expires_at": None, "message": "期限不明（常時有効の可能性）"}
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                now = datetime.now()
                if now >= expires_at:
                    msg = "期限切れ — app.py から再認証が必要です"
                    if has_refresh:
                        msg = "期限切れ（自動更新を試みます）"
                    return {"ok": False, "expires_at": expires_at_str, "message": msg}
                remaining = expires_at - now
                hours = int(remaining.total_seconds() // 3600)
                msg = f"有効（残り約{hours}時間）"
                if has_refresh:
                    msg += " ※期限切れ時は自動更新"
                return {"ok": True, "expires_at": expires_at_str, "message": msg}
            except Exception:
                return {"ok": True, "expires_at": expires_at_str, "message": "期限解析エラー"}
    return {"ok": False, "expires_at": None, "message": "アカウントが見つかりません"}


def get_all_ad_accounts() -> list[dict]:
    """全広告アカウントのリストを返す [{advertiser_id, name, bc_name}]"""
    if not ACCOUNTS_PATH.exists():
        return []
    config = yaml.safe_load(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    accounts = []
    for bc in config.get("business_centers", []):
        for acc in bc.get("ad_accounts", []):
            accounts.append({
                "advertiser_id": str(acc.get("advertiser_id", "")),
                "name": acc.get("name", ""),
                "bc_name": bc.get("name", ""),
            })
    return accounts


# ------------------------------------------------------------------
# ルール実行
# ------------------------------------------------------------------
# トークン期限切れ事前通知
# ------------------------------------------------------------------

def _notify_token_expiry_if_needed(rule: dict, now: datetime) -> None:
    """
    トークン残り24時間以内なら Slack に警告通知する。
    直近12時間以内に通知済みの場合はスキップ（連続通知防止）。
    """
    if not rule.get("slack_webhook_url"):
        return

    status = check_token_status(rule["advertiser_id"])
    if status["ok"] or not status.get("expires_at"):
        return  # 有効または期限不明なら何もしない

    try:
        expires_at = datetime.fromisoformat(status["expires_at"])
        # タイムゾーンなしの場合はJSTとして扱う
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=JST)
        remaining = expires_at - now
        remaining_hours = remaining.total_seconds() / 3600
    except Exception:
        return

    if remaining_hours > 24:
        return  # まだ余裕あり

    # 直近12時間以内に通知済みならスキップ
    last_warn_str = rule.get("_token_warn_sent_at")
    if last_warn_str:
        try:
            last_warn = datetime.fromisoformat(last_warn_str)
            if last_warn.tzinfo is None:
                last_warn = last_warn.replace(tzinfo=JST)
            if (now - last_warn).total_seconds() < 12 * 3600:
                return
        except Exception:
            pass

    # 通知送信
    if remaining_hours <= 0:
        msg = (
            f"🔴 *トークン期限切れ* [{rule['account_name']}]\n"
            f"すでに期限切れです。`app.py` の BC・アカウント管理から再認証してください。"
        )
    else:
        expire_jst = expires_at.astimezone(JST).strftime("%m/%d %H:%M")
        msg = (
            f"⚠️ *トークン期限切れまで{remaining_hours:.0f}時間* [{rule['account_name']}]\n"
            f"期限: {expire_jst} JST\n"
            f"`app.py` の BC・アカウント管理から再認証してください。"
        )

    try:
        SlackNotifier(rule["slack_webhook_url"]).send(text=msg)
        update_rule(rule["id"], _token_warn_sent_at=now.isoformat())
        logger.warning(f"トークン期限切れ警告通知送信 [{rule['account_name']}]: 残り{remaining_hours:.0f}時間")
    except Exception as e:
        logger.error(f"トークン期限切れ警告通知失敗: {e}")


# ------------------------------------------------------------------

def run_rule(rule: dict, access_token: str) -> dict:
    """
    単一ルールを実行してON/OFFを適用する
    Returns: 実行ログdict
    """
    now = datetime.now(JST)

    # トークン期限切れ24時間前に Slack 通知
    _notify_token_expiry_if_needed(rule, now)

    client = TikTokClient(access_token=access_token, advertiser_id=rule["advertiser_id"])

    log_entry: dict = {
        "timestamp": now.isoformat(),
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "account_name": rule["account_name"],
        "tcpa_target": rule["tcpa_target"],
        "results": [],
        "summary": "",
        "error": None,
    }

    try:
        reporting = ReportingManager(client)
        adgroup_mgr = AdGroupManager(client)

        today_str = now.strftime("%Y-%m-%d")
        last_reset_date = rule.get("_last_reset_date")
        rule_stopped_ids: list[str] = list(rule.get("_rule_stopped_ids", []))

        # ---- 日次リセット ----
        # 評価は1日単位。日付が変わったら内部状態をリセットして当日の評価を開始する。
        # 停止グループの再開は別ルールで管理するため自動再開はしない。
        if last_reset_date != today_str:
            logger.info(
                f"[{rule['name']}] 日次リセット ({last_reset_date} → {today_str}): "
                f"評価状態をリセット（再開は行わない）"
            )
            rule_stopped_ids = []
            update_rule(rule["id"], _rule_stopped_ids=[], _last_reset_date=today_str)

        # ---- 本日の統計取得（当日データのみで評価）----
        stats = reporting.get_adgroup_stats_today(
            adgroup_ids=rule["target_adgroup_ids"] or None,
            campaign_ids=rule["campaign_ids"] or None,
        )

        # 広告グループ一覧（現在のステータス確認）
        adgroups = adgroup_mgr.list(
            adgroup_ids=rule["target_adgroup_ids"] or None,
            campaign_ids=rule["campaign_ids"] or None,
        )
        disable_ids: list[str] = []
        enable_ids: list[str] = []
        results: list[dict] = []

        for ag in adgroups:
            ag_id = str(ag.get("adgroup_id", ""))
            ag_name = ag.get("adgroup_name", ag_id)
            # operation_status が実際のON/OFFを示す
            current_status = ag.get("operation_status", "")

            stat = stats.get(ag_id, {"spend": 0.0, "conversions": 0})
            spend = stat["spend"]
            conversions = stat["conversions"]

            desired = evaluate_cpa(spend, conversions, rule["tcpa_target"])

            # アクション決定
            # - DISABLE: 現在ENABLEのもののみ停止
            # - ENABLE: ルールが停止させたもののみ再開（手動停止は除外）
            if desired == "DISABLE" and current_status == "ENABLE":
                action = "DISABLE"
                disable_ids.append(ag_id)
            elif desired == "ENABLE" and ag_id in rule_stopped_ids:
                action = "ENABLE"
                enable_ids.append(ag_id)
            else:
                action = "NO_CHANGE"

            results.append({
                "adgroup_id": ag_id,
                "adgroup_name": ag_name,
                "spend": spend,
                "conversions": conversions,
                "current_status": current_status,
                "action": action,
                "reason": _build_reason(spend, conversions, rule["tcpa_target"], action),
            })

        # ステータス変更実行（Smart Plus など非対応は自動スキップ）
        succeeded_disable: list[str] = []
        succeeded_enable: list[str] = []
        skipped_disable: list[str] = []
        skipped_enable: list[str] = []

        if disable_ids:
            succeeded_disable = adgroup_mgr.update_status(disable_ids, "DISABLE")
            skipped_disable = [i for i in disable_ids if i not in succeeded_disable]
        if enable_ids:
            succeeded_enable = adgroup_mgr.update_status(enable_ids, "ENABLE")
            skipped_enable = [i for i in enable_ids if i not in succeeded_enable]

        # スキップされた広告グループの action を更新
        for r in results:
            if r["adgroup_id"] in skipped_disable or r["adgroup_id"] in skipped_enable:
                r["action"] = "SKIPPED"
                r["reason"] = "Smart Plus専用エンドポイントも失敗のためスキップ"

        # rule_stopped_ids を更新（実際に変更できたIDのみ反映）
        rule_stopped_ids = [i for i in rule_stopped_ids if i not in succeeded_enable]
        rule_stopped_ids.extend(succeeded_disable)

        skipped_count = len(skipped_disable) + len(skipped_enable)
        no_change_count = len(results) - len(succeeded_disable) - len(succeeded_enable) - skipped_count
        summary = (
            f"停止: {len(succeeded_disable)}件 / "
            f"再開: {len(succeeded_enable)}件 / "
            f"変更なし: {no_change_count}件"
            + (f" / スキップ(SmartPlus): {skipped_count}件" if skipped_count else "")
        )
        log_entry["results"] = results
        log_entry["summary"] = summary

        # Slack通知（実際に変更があった場合のみ）
        if rule.get("slack_webhook_url") and (succeeded_disable or succeeded_enable or skipped_count):
            _send_slack(rule, log_entry)

        logger.success(f"✅ ルール実行完了 [{rule['name']}]: {summary}")

    except Exception as e:
        err_str = str(e)
        # トークン期限切れを分かりやすく表示
        if "40100" in err_str or "40101" in err_str or "アクセストークン" in err_str:
            summary = "エラー: アクセストークン期限切れ — app.py の BC・アカウント管理から再認証してください"
        else:
            summary = f"エラー: {e}"
        log_entry["summary"] = summary
        log_entry["error"] = err_str
        rule_stopped_ids = list(rule.get("_rule_stopped_ids", []))
        logger.error(f"ルール実行エラー [{rule['name']}]: {e}")
        # Slackにもエラー通知
        if rule.get("slack_webhook_url"):
            try:
                SlackNotifier(rule["slack_webhook_url"]).send(
                    text=f"❌ 自動運用エラー [{rule['name']}]: {summary}"
                )
            except Exception:
                pass

    finally:
        client.close()

    # ログ保存
    logs = _load_logs()
    logs.append(log_entry)
    _save_logs(logs)

    # ルール状態を更新
    update_rule(
        rule["id"],
        last_run_at=now.isoformat(),
        last_run_summary=log_entry["summary"],
        _rule_stopped_ids=rule_stopped_ids,
        _last_reset_date=today_str,
    )

    return log_entry


def run_rule_by_id(rule_id: str) -> Optional[dict]:
    """IDでルールを取得して実行"""
    rule = get_rule(rule_id)
    if not rule:
        logger.error(f"ルールが見つかりません: {rule_id}")
        return None

    access_token = _get_access_token(rule["advertiser_id"])
    if not access_token:
        logger.error(f"access_token取得失敗: advertiser_id={rule['advertiser_id']}")
        return None

    return run_rule(rule, access_token)


def run_all_enabled_rules() -> list[dict]:
    """有効な全ルールを実行（スケジューラーから呼び出す）"""
    rules = [r for r in get_rules() if r.get("enabled")]
    results = []
    for rule in rules:
        access_token = _get_access_token(rule["advertiser_id"])
        if not access_token:
            logger.warning(f"スキップ [{rule['name']}]: access_token なし")
            continue
        result = run_rule(rule, access_token)
        results.append(result)
    return results


# ------------------------------------------------------------------
# Slack通知
# ------------------------------------------------------------------

def _send_slack(rule: dict, log_entry: dict) -> None:
    try:
        notifier = SlackNotifier(rule["slack_webhook_url"])
        results = log_entry["results"]

        stopped = [r for r in results if r["action"] == "DISABLE"]
        resumed = [r for r in results if r["action"] == "ENABLE"]
        skipped = [r for r in results if r["action"] == "SKIPPED"]

        lines: list[str] = [f"*tCPA目標: {rule['tcpa_target']:,}円*\n"]
        if stopped:
            lines.append("🛑 *停止した広告グループ*")
            for r in stopped:
                lines.append(f"  • {r['adgroup_name']}: {r['reason']}")
        if resumed:
            lines.append("▶️ *再開した広告グループ*")
            for r in resumed:
                lines.append(f"  • {r['adgroup_name']}: {r['reason']}")
        if skipped:
            lines.append("⚠️ *スキップ（Smart Plus・API非対応）*")
            for r in skipped:
                lines.append(f"  • {r['adgroup_name']}")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"⚡ 自動運用 - {rule['name']}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*アカウント:*\n{rule['account_name']}"},
                    {"type": "mrkdwn", "text": f"*結果:*\n{log_entry['summary']}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)},
            },
        ]
        notifier.send(
            text=f"⚡ 自動運用 [{rule['name']}]: {log_entry['summary']}",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Slack通知失敗: {e}")
