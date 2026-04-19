"""
TikTok Marketing API - 広告グループ統計レポート取得
"""

from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger

from .client import TikTokClient

JST = timezone(timedelta(hours=9))


class ReportingManager:
    """広告グループレポート取得クラス"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.advertiser_id = client.advertiser_id

    def get_adgroup_stats_today(
        self,
        adgroup_ids: Optional[list[str]] = None,
        campaign_ids: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        """
        本日の広告グループごとの消化額・CVを取得
        Returns: {adgroup_id: {"spend": float, "conversions": int}}
        """
        today = datetime.now(JST).strftime("%Y-%m-%d")
        return self.get_adgroup_stats(today, today, adgroup_ids, campaign_ids)

    def get_adgroup_stats(
        self,
        start_date: str,
        end_date: str,
        adgroup_ids: Optional[list[str]] = None,
        campaign_ids: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        """
        指定期間の広告グループごとの消化額・CVを取得
        Returns: {adgroup_id: {"spend": float, "conversions": int}}
        """
        filtering = {}
        if adgroup_ids:
            filtering["adgroup_ids"] = adgroup_ids
        if campaign_ids:
            filtering["campaign_ids"] = campaign_ids

        params = {
            "advertiser_id": self.advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_ADGROUP",
            "dimensions": json.dumps(["adgroup_id"]),
            "metrics": json.dumps(["spend", "conversion"]),
            "start_date": start_date,
            "end_date": end_date,
            "page_size": 100,
        }
        if filtering:
            params["filtering"] = json.dumps(filtering)

        all_rows = []
        page = 1
        while True:
            params["page"] = page
            data = self.client.get("/reports/integrated/get/", params=params)
            rows = data.get("list", [])
            all_rows.extend(rows)
            page_info = data.get("page_info", {})
            if page >= page_info.get("total_page", 1):
                break
            page += 1

        result: dict[str, dict] = {}
        for row in all_rows:
            dims = row.get("dimensions", {})
            metrics = row.get("metrics", {})
            adgroup_id = str(dims.get("adgroup_id", ""))
            if not adgroup_id:
                continue
            result[adgroup_id] = {
                "spend": float(metrics.get("spend", 0) or 0),
                "conversions": int(float(metrics.get("conversion", 0) or 0)),
            }

        logger.info(f"レポート取得: {len(result)}件の広告グループ統計")
        return result
