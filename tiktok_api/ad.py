"""
TikTok Marketing API - 広告管理（CRUD + 複製）
"""

from __future__ import annotations
from typing import Optional
from loguru import logger

from .client import TikTokClient


class AdManager:
    """広告管理クラス"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id

    # -------------------------------------------------------
    # 取得
    # -------------------------------------------------------

    def list(
        self,
        adgroup_ids: Optional[list[str]] = None,
        ad_ids: Optional[list[str]] = None,
        campaign_ids: Optional[list[str]] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """広告一覧取得"""
        filtering = {}
        if adgroup_ids:
            filtering["adgroup_ids"] = adgroup_ids
        if ad_ids:
            filtering["ad_ids"] = ad_ids
        if campaign_ids:
            filtering["campaign_ids"] = campaign_ids
        if status:
            filtering["primary_status"] = status

        params = {"advertiser_id": self.advertiser_id}
        if filtering:
            params["filtering"] = filtering

        items = self.client.get_all("/ad/get/", params=params)
        logger.info(f"広告取得: {len(items)}件")
        return items

    def get(self, ad_id: str) -> dict:
        """単一広告取得"""
        items = self.list(ad_ids=[ad_id])
        if not items:
            raise ValueError(f"広告 {ad_id} が見つかりません")
        return items[0]

    def list_by_adgroup(self, adgroup_id: str) -> list[dict]:
        """広告グループ配下の広告を全件取得"""
        return self.list(adgroup_ids=[adgroup_id])

    # -------------------------------------------------------
    # 作成
    # -------------------------------------------------------

    def create(self, payload: dict) -> str:
        """
        広告作成
        Returns: ad_id
        """
        body = {"advertiser_id": self.advertiser_id, **payload}
        data = self.client.post("/ad/create/", body=body)
        ad_id = str(data.get("ad_id", ""))
        logger.success(f"✅ 広告作成: {payload.get('ad_name')} (ID: {ad_id})")
        return ad_id

    def create_bulk(self, payloads: list[dict]) -> list[str]:
        """
        広告を一括作成
        Returns: [ad_id, ...]
        """
        ad_ids = []
        for i, payload in enumerate(payloads):
            try:
                ad_id = self.create(payload)
                ad_ids.append(ad_id)
            except Exception as e:
                logger.error(f"広告作成失敗 ({i+1}/{len(payloads)}): {e}")
                ad_ids.append("")
        logger.info(f"一括作成完了: 成功 {len([x for x in ad_ids if x])}/{len(payloads)}件")
        return ad_ids

    # -------------------------------------------------------
    # 更新
    # -------------------------------------------------------

    def update(self, ad_id: str, payload: dict) -> bool:
        """広告更新"""
        body = {
            "advertiser_id": self.advertiser_id,
            "ad_id": ad_id,
            **payload,
        }
        self.client.post("/ad/update/", body=body)
        logger.success(f"✅ 広告更新: {ad_id}")
        return True

    def update_status(self, ad_ids: list[str], status: str) -> bool:
        """
        広告ステータス一括変更
        status: ENABLE / DISABLE / DELETE
        """
        body = {
            "advertiser_id": self.advertiser_id,
            "ad_ids": ad_ids,
            "opt_status": status,
        }
        self.client.post("/ad/status/update/", body=body)
        logger.success(f"✅ 広告ステータス変更: {len(ad_ids)}件 → {status}")
        return True

    # -------------------------------------------------------
    # 複製
    # -------------------------------------------------------

    def duplicate(
        self,
        ad_id: str,
        adgroup_id: str,
        name_suffix: str = "_複製",
        override: Optional[dict] = None,
        status_after: str = "DISABLE",
    ) -> str:
        """
        広告を複製する
        adgroup_id: 複製先の広告グループID（同一グループへの複製も可）
        Returns: 新しいad_id
        """
        source = self.get(ad_id)

        # 複製に不要なフィールドを除外
        exclude_keys = {
            "ad_id", "adgroup_id", "campaign_id", "advertiser_id",
            "create_time", "modify_time", "status", "opt_status"
        }
        new_payload = {k: v for k, v in source.items() if k not in exclude_keys and v is not None}

        new_payload["adgroup_id"] = adgroup_id
        new_payload["ad_name"] = source["ad_name"] + name_suffix

        # 上書き設定を適用
        if override:
            new_payload.update(override)

        new_id = self.create(new_payload)

        if status_after:
            self.update_status([new_id], status_after)

        logger.success(f"✅ 広告複製完了: {ad_id} → {new_id}")
        return new_id
