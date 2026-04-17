"""
TikTok Marketing API - 広告グループ管理（CRUD + 複製）
"""

from __future__ import annotations
from typing import Optional
from loguru import logger

from .client import TikTokClient


class AdGroupManager:
    """広告グループ管理クラス"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id

    # -------------------------------------------------------
    # 取得
    # -------------------------------------------------------

    def list(
        self,
        campaign_ids: Optional[list[str]] = None,
        adgroup_ids: Optional[list[str]] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """広告グループ一覧取得"""
        filtering = {}
        if campaign_ids:
            filtering["campaign_ids"] = campaign_ids
        if adgroup_ids:
            filtering["adgroup_ids"] = adgroup_ids
        if status:
            filtering["primary_status"] = status

        params = {"advertiser_id": self.advertiser_id}
        if filtering:
            params["filtering"] = filtering

        items = self.client.get_all("/adgroup/get/", params=params)
        logger.info(f"広告グループ取得: {len(items)}件")
        return items

    def get(self, adgroup_id: str) -> dict:
        """単一広告グループ取得"""
        items = self.list(adgroup_ids=[adgroup_id])
        if not items:
            raise ValueError(f"広告グループ {adgroup_id} が見つかりません")
        return items[0]

    def list_by_campaign(self, campaign_id: str) -> list[dict]:
        """キャンペーン配下の広告グループを全件取得"""
        return self.list(campaign_ids=[campaign_id])

    # -------------------------------------------------------
    # 作成
    # -------------------------------------------------------

    def create(self, payload: dict) -> str:
        """
        広告グループ作成
        Returns: adgroup_id
        """
        body = {"advertiser_id": self.advertiser_id, **payload}
        data = self.client.post("/adgroup/create/", body=body)
        adgroup_id = str(data.get("adgroup_id", ""))
        logger.success(f"✅ 広告グループ作成: {payload.get('adgroup_name')} (ID: {adgroup_id})")
        return adgroup_id

    # -------------------------------------------------------
    # 更新
    # -------------------------------------------------------

    def update(self, adgroup_id: str, payload: dict) -> bool:
        """広告グループ更新"""
        body = {
            "advertiser_id": self.advertiser_id,
            "adgroup_id": adgroup_id,
            **payload,
        }
        self.client.post("/adgroup/update/", body=body)
        logger.success(f"✅ 広告グループ更新: {adgroup_id}")
        return True

    def update_status(self, adgroup_ids: list[str], status: str) -> bool:
        """
        広告グループステータス一括変更
        status: ENABLE / DISABLE / DELETE
        """
        body = {
            "advertiser_id": self.advertiser_id,
            "adgroup_ids": adgroup_ids,
            "opt_status": status,
        }
        self.client.post("/adgroup/status/update/", body=body)
        logger.success(f"✅ 広告グループステータス変更: {len(adgroup_ids)}件 → {status}")
        return True

    # -------------------------------------------------------
    # 複製
    # -------------------------------------------------------

    def duplicate(
        self,
        adgroup_id: str,
        campaign_id: str,
        name_suffix: str = "_複製",
        override: Optional[dict] = None,
        status_after: str = "DISABLE",
    ) -> str:
        """
        広告グループを複製する
        campaign_id: 複製先のキャンペーンID（同じキャンペーンへの複製も可）
        Returns: 新しいadgroup_id
        """
        source = self.get(adgroup_id)

        # 複製に不要なフィールドを除外
        exclude_keys = {"adgroup_id", "campaign_id", "advertiser_id", "create_time", "modify_time", "status"}
        new_payload = {k: v for k, v in source.items() if k not in exclude_keys and v is not None}

        new_payload["campaign_id"] = campaign_id
        new_payload["adgroup_name"] = source["adgroup_name"] + name_suffix

        # 上書き設定を適用
        if override:
            new_payload.update(override)

        new_id = self.create(new_payload)

        if status_after:
            self.update_status([new_id], status_after)

        logger.success(f"✅ 広告グループ複製完了: {adgroup_id} → {new_id}")
        return new_id
