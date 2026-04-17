"""
TikTok Marketing API - キャンペーン管理（CRUD + 複製）
"""

from __future__ import annotations
from typing import Optional
from loguru import logger

from .client import TikTokClient


class CampaignManager:
    """キャンペーン管理クラス"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id

    # -------------------------------------------------------
    # 取得
    # -------------------------------------------------------

    def list(
        self,
        campaign_ids: Optional[list[str]] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """キャンペーン一覧取得"""
        params = {"advertiser_id": self.advertiser_id}
        if campaign_ids:
            params["filtering"] = {"campaign_ids": campaign_ids}
        if status:
            params["filtering"] = {**params.get("filtering", {}), "primary_status": status}

        items = self.client.get_all("/campaign/get/", params=params)
        logger.info(f"キャンペーン取得: {len(items)}件")
        return items

    def get(self, campaign_id: str) -> dict:
        """単一キャンペーン取得"""
        items = self.list(campaign_ids=[campaign_id])
        if not items:
            raise ValueError(f"キャンペーン {campaign_id} が見つかりません")
        return items[0]

    # -------------------------------------------------------
    # 作成
    # -------------------------------------------------------

    def create(self, payload: dict) -> str:
        """
        キャンペーン作成
        Returns: campaign_id
        """
        body = {"advertiser_id": self.advertiser_id, **payload}
        data = self.client.post("/campaign/create/", body=body)
        campaign_id = str(data.get("campaign_id", ""))
        logger.success(f"✅ キャンペーン作成: {payload.get('campaign_name')} (ID: {campaign_id})")
        return campaign_id

    # -------------------------------------------------------
    # 更新
    # -------------------------------------------------------

    def update(self, campaign_id: str, payload: dict) -> bool:
        """キャンペーン更新"""
        body = {
            "advertiser_id": self.advertiser_id,
            "campaign_id": campaign_id,
            **payload,
        }
        self.client.post("/campaign/update/", body=body)
        logger.success(f"✅ キャンペーン更新: {campaign_id}")
        return True

    def update_status(self, campaign_ids: list[str], status: str) -> bool:
        """
        キャンペーンステータス一括変更
        status: ENABLE / DISABLE / DELETE
        """
        body = {
            "advertiser_id": self.advertiser_id,
            "campaign_ids": campaign_ids,
            "opt_status": status,
        }
        self.client.post("/campaign/status/update/", body=body)
        logger.success(f"✅ キャンペーンステータス変更: {len(campaign_ids)}件 → {status}")
        return True

    # -------------------------------------------------------
    # 複製
    # -------------------------------------------------------

    def duplicate(
        self,
        campaign_id: str,
        name_suffix: str = "_複製",
        override: Optional[dict] = None,
        status_after: str = "DISABLE",
    ) -> str:
        """
        キャンペーンを複製する（広告グループ・広告は別途DuplicateManagerで処理）
        Returns: 新しいcampaign_id
        """
        source = self.get(campaign_id)

        new_payload = {
            "campaign_name": source["campaign_name"] + name_suffix,
            "objective_type": source["objective_type"],
            "budget_mode": source["budget_mode"],
            "budget": source.get("budget", 0),
        }

        # 上書き設定を適用
        if override:
            new_payload.update(override)

        new_id = self.create(new_payload)

        # 複製後のステータス設定
        if status_after:
            self.update_status([new_id], status_after)

        logger.success(f"✅ キャンペーン複製完了: {campaign_id} → {new_id}")
        return new_id
