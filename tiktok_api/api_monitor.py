"""
TikTok APIフィールド変更監視
レスポンスのフィールドセットをスナップショットと比較し、変化があればSlack通知する
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from loguru import logger

from .client import TikTokClient

SNAPSHOT_PATH = "config/api_field_snapshot.json"


class APIFieldMonitor:
    """TikTok APIレスポンスフィールドの変更を監視"""

    def __init__(self, snapshot_path: str = SNAPSHOT_PATH):
        self.snapshot_path = snapshot_path
        self._snapshot: dict = self._load()

    # -------------------------------------------------------
    # スナップショット管理
    # -------------------------------------------------------

    def _load(self) -> dict:
        if os.path.exists(self.snapshot_path):
            try:
                with open(self.snapshot_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"スナップショット読み込み失敗: {e}")
        return {}

    def _save(self):
        os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
        with open(self.snapshot_path, "w", encoding="utf-8") as f:
            json.dump(self._snapshot, f, ensure_ascii=False, indent=2)

    def get_snapshot_info(self) -> dict:
        """現在のスナップショット情報を返す"""
        return {
            key: {
                "field_count": len(val.get("fields", [])),
                "updated_at": val.get("updated_at", ""),
            }
            for key, val in self._snapshot.items()
        }

    # -------------------------------------------------------
    # フィールド比較
    # -------------------------------------------------------

    def _extract_fields(self, items: list[dict]) -> set[str]:
        fields: set[str] = set()
        for item in items:
            fields.update(item.keys())
        return fields

    def _compare_and_update(
        self,
        key: str,
        current_fields: set[str],
        entity_type: str,
    ) -> list[dict]:
        """スナップショットと比較して変更リストを返す"""
        if key not in self._snapshot:
            # 初回登録
            self._snapshot[key] = {
                "fields": sorted(current_fields),
                "updated_at": datetime.now().isoformat(),
            }
            self._save()
            logger.info(f"初回スナップショット保存: {key} ({len(current_fields)}フィールド)")
            return []

        prev_fields = set(self._snapshot[key].get("fields", []))
        changes: list[dict] = []

        added = current_fields - prev_fields
        removed = prev_fields - current_fields

        for f in sorted(added):
            changes.append({
                "type": "追加",
                "field": f,
                "entity": entity_type,
                "detail": "新しいフィールドが追加されました",
            })
            logger.warning(f"⚠️ フィールド追加 [{entity_type}]: {f}")

        for f in sorted(removed):
            changes.append({
                "type": "削除",
                "field": f,
                "entity": entity_type,
                "detail": "フィールドが削除されました",
            })
            logger.warning(f"⚠️ フィールド削除 [{entity_type}]: {f}")

        if changes:
            self._snapshot[key] = {
                "fields": sorted(current_fields),
                "updated_at": datetime.now().isoformat(),
            }
            self._save()

        return changes

    # -------------------------------------------------------
    # 各エンティティのチェック
    # -------------------------------------------------------

    def check_campaigns(
        self, client: TikTokClient, bc_name: str, account_name: str
    ) -> list[dict]:
        try:
            from .campaign import CampaignManager
            items = CampaignManager(client).list()
            if not items:
                return []
            fields = self._extract_fields(items)
            key = f"{bc_name}|{account_name}|campaign"
            return self._compare_and_update(key, fields, "campaign")
        except Exception as e:
            logger.error(f"キャンペーンフィールドチェックエラー: {e}")
            return []

    def check_adgroups(
        self, client: TikTokClient, bc_name: str, account_name: str
    ) -> list[dict]:
        try:
            from .adgroup import AdGroupManager
            items = AdGroupManager(client).list()
            if not items:
                return []
            fields = self._extract_fields(items)
            key = f"{bc_name}|{account_name}|adgroup"
            return self._compare_and_update(key, fields, "adgroup")
        except Exception as e:
            logger.error(f"広告グループフィールドチェックエラー: {e}")
            return []

    def check_ads(
        self, client: TikTokClient, bc_name: str, account_name: str
    ) -> list[dict]:
        try:
            from .ad import AdManager
            items = AdManager(client).list()
            if not items:
                return []
            fields = self._extract_fields(items)
            key = f"{bc_name}|{account_name}|ad"
            return self._compare_and_update(key, fields, "ad")
        except Exception as e:
            logger.error(f"広告フィールドチェックエラー: {e}")
            return []

    # -------------------------------------------------------
    # 一括チェック
    # -------------------------------------------------------

    def run_full_check(
        self,
        client: TikTokClient,
        bc_name: str,
        account_name: str,
        slack_webhook: str | None = None,
    ) -> dict[str, list[dict]]:
        """
        全エンティティを一括チェック。変更があればSlack通知。
        Returns: {"campaign": [...], "adgroup": [...], "ad": [...]}
        """
        results = {
            "campaign": self.check_campaigns(client, bc_name, account_name),
            "adgroup": self.check_adgroups(client, bc_name, account_name),
            "ad": self.check_ads(client, bc_name, account_name),
        }

        all_changes = [c for changes in results.values() for c in changes]

        if all_changes:
            logger.warning(f"フィールド変更検知: {len(all_changes)}件 ({bc_name} / {account_name})")
            if slack_webhook:
                from .slack_notifier import SlackNotifier
                SlackNotifier(slack_webhook).send_api_change_alert(
                    bc_name, account_name, all_changes
                )
        else:
            logger.info(f"フィールド変更なし: {bc_name} / {account_name}")

        return results
