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
        operation_status: Optional[list[str]] = None,
    ) -> list[dict]:
        """広告グループ一覧取得"""
        import json
        # httpx がリストを ?operation_status=ENABLE&operation_status=DISABLE に展開する
        params: dict = {
            "advertiser_id": self.advertiser_id,
            "operation_status": operation_status or ["ENABLE", "DISABLE"],
        }
        filtering: dict = {}
        if campaign_ids:
            filtering["campaign_ids"] = campaign_ids
        if adgroup_ids:
            filtering["adgroup_ids"] = adgroup_ids
        if status:
            filtering["primary_status"] = status
        if filtering:
            params["filtering"] = json.dumps(filtering)

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

    def update_status(self, adgroup_ids: list[str], status: str) -> list[str]:
        """
        広告グループステータス一括変更。
        Smart Plus 非対応の場合は1件ずつ試行し、Smart Plus 専用エンドポイントを使う。
        status: ENABLE / DISABLE / DELETE
        Returns: 実際に変更できた adgroup_id のリスト
        """
        from .client import TikTokAPIError

        body = {
            "advertiser_id": self.advertiser_id,
            "adgroup_ids": adgroup_ids,
            "operation_status": status,
        }
        try:
            self.client.post("/adgroup/status/update/", body=body)
            logger.success(f"✅ 広告グループステータス変更: {len(adgroup_ids)}件 → {status}")
            return adgroup_ids
        except TikTokAPIError as e:
            # Smart Plus が混在する場合は1件ずつ試行
            if "Smart Plus" in str(e) or e.code == 40002:
                logger.warning(f"一括更新失敗（Smart Plus混在の可能性）→ 1件ずつ試行: {e}")
                succeeded = []
                for ag_id in adgroup_ids:
                    if self._update_status_single(ag_id, status):
                        succeeded.append(ag_id)
                logger.success(
                    f"✅ 広告グループステータス変更: {len(succeeded)}/{len(adgroup_ids)}件 → {status}"
                )
                return succeeded
            raise

    def _update_status_single(self, adgroup_id: str, status: str) -> bool:
        """
        1件の広告グループのステータスを変更する。
        通常エンドポイントで失敗した場合は Smart Plus 専用エンドポイントを試みる。
        Returns: True=成功 / False=スキップ
        """
        from .client import TikTokAPIError

        # ① 通常エンドポイントで試行
        try:
            self.client.post("/adgroup/status/update/", body={
                "advertiser_id": self.advertiser_id,
                "adgroup_ids": [adgroup_id],
                "operation_status": status,
            })
            return True
        except TikTokAPIError as e1:
            if "Smart Plus" not in str(e1) and e1.code != 40002:
                logger.warning(f"スキップ [{adgroup_id}]: {e1.message}")
                return False

        # ② Smart Plus 専用エンドポイントで再試行（パラメータ名の違いで複数パターン試行）
        logger.info(f"Smart Plus専用エンドポイントで再試行: {adgroup_id}")

        # 試行パターン: (adgroup_idキー, ステータスフィールド名)
        candidates = [
            {"adgroup_id": adgroup_id, "operation_status": status},         # 単数 + 新フィールド
            {"adgroup_ids": [adgroup_id], "operation_status": status},      # 複数リスト + 新フィールド
            {"adgroup_id": adgroup_id, "opt_status": status},               # 単数 + 旧フィールド
            {"adgroup_ids": [adgroup_id], "opt_status": status},            # 複数リスト + 旧フィールド
        ]

        for i, extra in enumerate(candidates):
            body = {"advertiser_id": self.advertiser_id, **extra}
            try:
                self.client.post("/smart_plus/adgroup/status/update/", body=body)
                logger.success(
                    f"✅ Smart Plus広告グループ変更成功 (パターン{i+1}): {adgroup_id} → {status}"
                )
                return True
            except TikTokAPIError as e2:
                logger.debug(
                    f"Smart Plus パターン{i+1} 失敗 [{adgroup_id}]: [{e2.code}] {e2.message}"
                )
                continue

        logger.warning(f"Smart Plus専用エンドポイント 全パターン失敗 [{adgroup_id}] → スキップ")
        return False

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
