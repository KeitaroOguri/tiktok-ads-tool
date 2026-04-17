"""
TikTok Marketing API - 複製オーケストレーター
キャンペーン/広告グループ/広告の階層複製を統括管理
"""

from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from .client import TikTokClient
from .campaign import CampaignManager
from .adgroup import AdGroupManager
from .ad import AdManager
from .creative import CreativeManager


@dataclass
class DuplicateResult:
    """複製結果サマリー"""
    source_type: str          # campaign / adgroup / ad
    source_id: str
    new_id: str
    success: bool
    error: str = ""
    children: list = field(default_factory=list)

    def summary(self) -> dict:
        total = self._count(self)
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "new_id": self.new_id,
            "success": self.success,
            "total_campaigns": total["campaign"],
            "total_adgroups": total["adgroup"],
            "total_ads": total["ad"],
            "error": self.error,
        }

    def _count(self, node) -> dict:
        counts = {"campaign": 0, "adgroup": 0, "ad": 0}
        if node.success:
            counts[node.source_type] = counts.get(node.source_type, 0) + 1
        for child in node.children:
            child_counts = self._count(child)
            for k in counts:
                counts[k] += child_counts.get(k, 0)
        return counts


class DuplicateManager:
    """
    階層複製を統括するオーケストレーター
    キャンペーン → 広告グループ → 広告 を再帰的に複製
    """

    def __init__(self, client: TikTokClient, dest_client: Optional[TikTokClient] = None):
        """
        client: 複製元のTikTokClient
        dest_client: 複製先のTikTokClient（別アカウントへの複製時に指定）
                     Noneの場合は同一アカウント内で複製
        """
        self.src_client = client
        self.dst_client = dest_client or client

        self.src_campaign = CampaignManager(self.src_client)
        self.src_adgroup = AdGroupManager(self.src_client)
        self.src_ad = AdManager(self.src_client)

        self.dst_campaign = CampaignManager(self.dst_client)
        self.dst_adgroup = AdGroupManager(self.dst_client)
        self.dst_ad = AdManager(self.dst_client)
        self.dst_creative = CreativeManager(self.dst_client)

        self._is_cross_account = (
            self.src_client.advertiser_id != self.dst_client.advertiser_id
        )

    # -------------------------------------------------------
    # キャンペーン複製（階層丸ごと）
    # -------------------------------------------------------

    def duplicate_campaign(
        self,
        campaign_id: str,
        name_suffix: str = "_複製",
        include_adgroups: bool = True,
        include_ads: bool = True,
        override: Optional[dict] = None,
        status_after: str = "DISABLE",
    ) -> DuplicateResult:
        """
        キャンペーンを複製
        include_adgroups=True: 配下の広告グループも複製
        include_ads=True: 広告グループ配下の広告も複製
        """
        logger.info(f"=== キャンペーン複製開始: {campaign_id} ===")

        try:
            new_campaign_id = self.dst_campaign.duplicate(
                campaign_id=campaign_id,
                name_suffix=name_suffix,
                override=override,
                status_after=status_after,
            )
        except Exception as e:
            logger.error(f"❌ キャンペーン複製失敗: {e}")
            return DuplicateResult("campaign", campaign_id, "", False, str(e))

        result = DuplicateResult("campaign", campaign_id, new_campaign_id, True)

        if include_adgroups:
            adgroups = self.src_adgroup.list_by_campaign(campaign_id)
            logger.info(f"配下の広告グループ: {len(adgroups)}件を複製")

            for adgroup in adgroups:
                adgroup_result = self._duplicate_adgroup_internal(
                    adgroup_id=adgroup["adgroup_id"],
                    dest_campaign_id=new_campaign_id,
                    name_suffix=name_suffix,
                    include_ads=include_ads,
                    override=None,
                    status_after=status_after,
                )
                result.children.append(adgroup_result)

        summary = result.summary()
        logger.success(
            f"✅ キャンペーン複製完了: "
            f"広告グループ {summary['total_adgroups']}件, "
            f"広告 {summary['total_ads']}件"
        )
        return result

    # -------------------------------------------------------
    # 広告グループ複製
    # -------------------------------------------------------

    def duplicate_adgroup(
        self,
        adgroup_id: str,
        dest_campaign_id: str,
        name_suffix: str = "_複製",
        include_ads: bool = True,
        override: Optional[dict] = None,
        status_after: str = "DISABLE",
    ) -> DuplicateResult:
        """
        広告グループを複製
        dest_campaign_id: 複製先キャンペーンID
        include_ads=True: 配下の広告も複製
        """
        logger.info(f"=== 広告グループ複製開始: {adgroup_id} ===")
        return self._duplicate_adgroup_internal(
            adgroup_id, dest_campaign_id, name_suffix, include_ads, override, status_after
        )

    def _duplicate_adgroup_internal(
        self,
        adgroup_id: str,
        dest_campaign_id: str,
        name_suffix: str,
        include_ads: bool,
        override: Optional[dict],
        status_after: str,
    ) -> DuplicateResult:
        try:
            new_adgroup_id = self.dst_adgroup.duplicate(
                adgroup_id=adgroup_id,
                campaign_id=dest_campaign_id,
                name_suffix=name_suffix,
                override=override,
                status_after=status_after,
            )
        except Exception as e:
            logger.error(f"❌ 広告グループ複製失敗 {adgroup_id}: {e}")
            return DuplicateResult("adgroup", adgroup_id, "", False, str(e))

        result = DuplicateResult("adgroup", adgroup_id, new_adgroup_id, True)

        if include_ads:
            ads = self.src_ad.list_by_adgroup(adgroup_id)
            logger.info(f"  配下の広告: {len(ads)}件を複製")

            for ad in ads:
                ad_result = self._duplicate_ad_internal(
                    ad_id=ad["ad_id"],
                    dest_adgroup_id=new_adgroup_id,
                    name_suffix=name_suffix,
                    override=None,
                    status_after=status_after,
                )
                result.children.append(ad_result)

        return result

    # -------------------------------------------------------
    # 広告複製
    # -------------------------------------------------------

    def duplicate_ad(
        self,
        ad_id: str,
        dest_adgroup_id: str,
        name_suffix: str = "_複製",
        override: Optional[dict] = None,
        status_after: str = "DISABLE",
    ) -> DuplicateResult:
        """
        広告を複製
        dest_adgroup_id: 複製先広告グループID（別アカウントへも可）
        """
        logger.info(f"=== 広告複製開始: {ad_id} ===")
        return self._duplicate_ad_internal(
            ad_id, dest_adgroup_id, name_suffix, override, status_after
        )

    def _duplicate_ad_internal(
        self,
        ad_id: str,
        dest_adgroup_id: str,
        name_suffix: str,
        override: Optional[dict],
        status_after: str,
    ) -> DuplicateResult:
        try:
            # 別アカウントへの複製時はクリエイティブを再アップロード
            if self._is_cross_account:
                new_ad_id = self._duplicate_ad_cross_account(
                    ad_id, dest_adgroup_id, name_suffix, override, status_after
                )
            else:
                new_ad_id = self.dst_ad.duplicate(
                    ad_id=ad_id,
                    adgroup_id=dest_adgroup_id,
                    name_suffix=name_suffix,
                    override=override,
                    status_after=status_after,
                )
        except Exception as e:
            logger.error(f"❌ 広告複製失敗 {ad_id}: {e}")
            return DuplicateResult("ad", ad_id, "", False, str(e))

        return DuplicateResult("ad", ad_id, new_ad_id, True)

    def _duplicate_ad_cross_account(
        self,
        ad_id: str,
        dest_adgroup_id: str,
        name_suffix: str,
        override: Optional[dict],
        status_after: str,
    ) -> str:
        """
        別アカウントへの広告複製
        動画IDはアカウントに紐づくため、URLから再アップロードが必要
        """
        source = self.src_ad.get(ad_id)
        exclude_keys = {
            "ad_id", "adgroup_id", "campaign_id", "advertiser_id",
            "create_time", "modify_time", "status", "opt_status"
        }
        new_payload = {k: v for k, v in source.items() if k not in exclude_keys and v is not None}
        new_payload["adgroup_id"] = dest_adgroup_id
        new_payload["ad_name"] = source["ad_name"] + name_suffix

        # 動画を別アカウントに再アップロード
        video_id = source.get("video_id")
        if video_id:
            video_infos = CreativeManager(self.src_client).get_video_info([video_id])
            if video_infos and video_infos[0].get("video_url"):
                video_url = video_infos[0]["video_url"]
                new_video = self.dst_creative.upload_video_by_url(
                    url=video_url,
                    video_name=f"{video_infos[0].get('video_name', video_id)}{name_suffix}",
                )
                new_payload["video_id"] = new_video.get("video_id", "")
                logger.info(f"  動画再アップロード完了: {video_id} → {new_payload['video_id']}")

        if override:
            new_payload.update(override)

        new_id = self.dst_ad.create(new_payload)
        if status_after:
            self.dst_ad.update_status([new_id], status_after)

        return new_id
