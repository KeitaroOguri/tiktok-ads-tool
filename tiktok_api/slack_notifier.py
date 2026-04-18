"""
Slack通知 - TikTok APIフィールド変更アラートほか
"""

from __future__ import annotations
from loguru import logger
import httpx


class SlackNotifier:
    """Slack Incoming Webhook通知クラス"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, text: str, blocks: list | None = None) -> bool:
        """メッセージを送信"""
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks

        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.success(f"✅ Slack通知送信: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Slack通知失敗: {e}")
            return False

    def send_api_change_alert(
        self,
        bc_name: str,
        account_name: str,
        changes: list[dict],
    ) -> bool:
        """
        TikTok APIフィールド変更アラートを送信

        changes: [{"type": "追加"|"削除", "field": str, "entity": str, "detail": str}]
        """
        if not changes:
            return True

        entity_label = {
            "campaign": "キャンペーン",
            "adgroup": "広告グループ",
            "ad": "広告",
        }

        lines = []
        for c in changes:
            entity = entity_label.get(c.get("entity", ""), c.get("entity", ""))
            change_type = c.get("type", "")
            field = c.get("field", "")
            detail = c.get("detail", "")
            icon = "🆕" if change_type == "追加" else "❌"
            lines.append(f"{icon} [{entity}] `{field}` — {detail}")

        change_text = "\n".join(lines)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⚠️ TikTok API フィールド変更を検知しました",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*BC名:*\n{bc_name}"},
                    {"type": "mrkdwn", "text": f"*広告アカウント:*\n{account_name}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*変更内容:*\n{change_text}"},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "入稿に影響がないか確認してください。",
                    }
                ],
            },
        ]

        return self.send(
            text=f"⚠️ TikTok APIフィールド変更検知: {bc_name} / {account_name} ({len(changes)}件)",
            blocks=blocks,
        )

    def send_submission_summary(
        self,
        account_name: str,
        campaign_count: int,
        adgroup_count: int,
        ad_count: int,
        error_count: int,
    ) -> bool:
        """一括入稿完了サマリーを送信"""
        icon = "✅" if error_count == 0 else "⚠️"
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{icon} TikTok広告 一括入稿完了",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*アカウント:*\n{account_name}"},
                    {"type": "mrkdwn", "text": f"*エラー件数:*\n{error_count}件"},
                    {"type": "mrkdwn", "text": f"*キャンペーン:*\n{campaign_count}件"},
                    {"type": "mrkdwn", "text": f"*広告グループ:*\n{adgroup_count}件"},
                    {"type": "mrkdwn", "text": f"*広告:*\n{ad_count}件"},
                ],
            },
        ]
        return self.send(
            text=f"{icon} 一括入稿完了: {account_name} (キャンペーン{campaign_count}件 / エラー{error_count}件)",
            blocks=blocks,
        )
