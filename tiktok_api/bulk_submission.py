"""
一括入稿プロセッサー（統合シート対応）
各行が「広告」1件に対応。キャンペーン/広告グループは名前で重複排除して作成。
"""

from __future__ import annotations
from dataclasses import dataclass
from loguru import logger
import pandas as pd

from .campaign import CampaignManager
from .adgroup import AdGroupManager
from .ad import AdManager
from .client import TikTokClient


# -------------------------------------------------------
# 日本語 → TikTok API 値マッピング
# -------------------------------------------------------

OBJECTIVE_MAP = {
    "トラフィック":       "TRAFFIC",
    "リーチ":            "REACH",
    "動画視聴":          "VIDEO_VIEWS",
    "コンバージョン":     "CONVERSIONS",
    "アプリインストール": "APP_INSTALLS",
    "リード獲得":        "LEAD_GENERATION",
    "フォロー":          "FOLLOWERS",
}

BUDGET_MODE_MAP = {
    "無制限": "BUDGET_MODE_INFINITE",
    "日予算": "BUDGET_MODE_DAILY",
    "総予算": "BUDGET_MODE_TOTAL",
}

PLACEMENT_TYPE_MAP = {
    "自動": "PLACEMENT_TYPE_AUTOMATIC",
    "手動": "PLACEMENT_TYPE_NORMAL",
}

SCHEDULE_TYPE_MAP = {
    "開始日から": "SCHEDULE_FROM_NOW",
    "期間指定":   "SCHEDULE_START_END",
}

OPTIMIZATION_GOAL_MAP = {
    "クリック":       "CLICK",
    "リーチ":        "REACH",
    "コンバージョン": "CONVERT",
    "動画再生":      "VIDEO_PLAY",
    "フォロー":      "FOLLOW",
    "インプレッション": "SHOW",
}

BID_TYPE_MAP = {
    "自動入札": "BID_TYPE_NO_BID",
    "カスタム": "BID_TYPE_CUSTOM",
}

GENDER_MAP = {
    "すべて": "GENDER_UNLIMITED",
    "男性":   "GENDER_MALE",
    "女性":   "GENDER_FEMALE",
}

CTA_MAP = {
    "詳しくはこちら":       "LEARN_MORE",
    "今すぐ購入":           "SHOP_NOW",
    "アプリをダウンロード": "DOWNLOAD",
    "今すぐ申し込む":       "APPLY_NOW",
    "今すぐ予約":           "BOOK_NOW",
    "お問い合わせ":         "CONTACT_US",
    "今すぐ登録":           "SIGN_UP",
    "今すぐ視聴":           "WATCH_NOW",
    "今すぐプレイ":         "PLAY_GAME",
    "詳細を見る":           "VIEW_MORE",
    "今すぐ注文":           "ORDER_NOW",
    "今すぐ入手":           "GET_NOW",
}


# -------------------------------------------------------
# ユーティリティ
# -------------------------------------------------------

def _s(row: pd.Series, key: str) -> str:
    """行から文字列を取得（strip済み）"""
    return str(row.get(key, "")).strip()


def _f(row: pd.Series, key: str) -> float | None:
    """行から数値を取得。空/変換失敗はNone"""
    try:
        v = str(row.get(key, "")).strip()
        return float(v) if v else None
    except (ValueError, TypeError):
        return None


def _csv(row: pd.Series, key: str) -> list[str]:
    """カンマ区切り文字列をリストに変換"""
    raw = str(row.get(key, "")).strip()
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else []


def _map(mapping: dict, raw: str, default: str = "") -> str:
    """マッピング変換。マップにない値はそのまま返す"""
    if not raw:
        return default
    return mapping.get(raw, raw) or default


# -------------------------------------------------------
# 結果データクラス
# -------------------------------------------------------

@dataclass
class UnifiedResult:
    row_index: int          # 1始まりのデータ行番号
    status: str = ""        # success / error / skipped
    campaign_id: str = ""
    adgroup_id: str = ""
    ad_id: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "row_index": self.row_index,
            "status": self.status,
            "campaign_id": self.campaign_id,
            "adgroup_id": self.adgroup_id,
            "ad_id": self.ad_id,
            "error": self.error,
        }


# -------------------------------------------------------
# ペイロードビルダー
# -------------------------------------------------------

def _build_campaign_payload(row: pd.Series) -> dict:
    name        = _s(row, "キャンペーン名")
    objective   = _map(OBJECTIVE_MAP,   _s(row, "目標タイプ"))
    budget_mode = _map(BUDGET_MODE_MAP, _s(row, "キャンペーン予算タイプ"), "BUDGET_MODE_INFINITE")
    budget      = _f(row, "キャンペーン予算")

    payload: dict = {
        "campaign_name": name,
        "objective_type": objective,
        "budget_mode": budget_mode,
    }
    if budget and budget > 0:
        payload["budget"] = budget
    return payload


def _build_adgroup_payload(row: pd.Series, campaign_id: str) -> dict:
    name         = _s(row, "広告グループ名")
    placement    = _map(PLACEMENT_TYPE_MAP, _s(row, "配置タイプ"),              "PLACEMENT_TYPE_AUTOMATIC")
    budget_mode  = _map(BUDGET_MODE_MAP,    _s(row, "広告グループ予算タイプ"),   "BUDGET_MODE_INFINITE")
    schedule     = _map(SCHEDULE_TYPE_MAP,  _s(row, "スケジュール"),             "SCHEDULE_FROM_NOW")
    opt_goal     = _map(OPTIMIZATION_GOAL_MAP, _s(row, "最適化目標"))
    bid_type     = _map(BID_TYPE_MAP,       _s(row, "入札タイプ"),               "BID_TYPE_NO_BID")
    gender       = _map(GENDER_MAP,         _s(row, "性別"),                     "GENDER_UNLIMITED")

    payload: dict = {
        "adgroup_name": name,
        "campaign_id": campaign_id,
        "placement_type": placement,
        "budget_mode": budget_mode,
        "schedule_type": schedule,
        "bid_type": bid_type,
    }

    if opt_goal:
        payload["optimization_goal"] = opt_goal

    budget = _f(row, "広告グループ予算")
    if budget and budget > 0:
        payload["budget"] = budget

    bid_price = _f(row, "入札価格")
    if bid_price and bid_price > 0:
        payload["bid_price"] = bid_price

    start = _s(row, "開始日時")
    if start:
        payload["start_time"] = start

    end = _s(row, "終了日時")
    if end:
        payload["end_time"] = end

    locations = _csv(row, "ターゲット地域")
    if locations:
        payload["location_ids"] = locations

    ages = _csv(row, "年齢層")
    if ages:
        payload["age"] = ages

    if gender:
        payload["gender"] = gender

    return payload


def _build_ad_payload(row: pd.Series, adgroup_id: str) -> dict:
    name       = _s(row, "広告名")
    ad_format  = _s(row, "広告フォーマット") or "SINGLE_VIDEO"
    video_id   = _s(row, "動画素材ID")
    image_id   = _s(row, "サムネイル素材ID")
    ad_text    = _s(row, "広告テキスト")
    cta        = _map(CTA_MAP, _s(row, "CTA"))
    url        = _s(row, "ランディングURL")
    disp_name  = _s(row, "表示名")

    payload: dict = {
        "adgroup_id": adgroup_id,
        "ad_name": name,
        "ad_format": ad_format,
    }
    if video_id:
        payload["video_id"] = video_id
    if image_id:
        payload["image_ids"] = [image_id]
    if ad_text:
        payload["ad_text"] = ad_text
    if cta:
        payload["call_to_action_type"] = cta
    if url:
        payload["landing_page_url"] = url
    if disp_name:
        payload["display_name"] = disp_name

    return payload


# -------------------------------------------------------
# プロセッサー本体
# -------------------------------------------------------

class BulkSubmissionProcessor:
    """統合シートのデータを TikTok API へ一括入稿"""

    def __init__(self, client: TikTokClient):
        self.client = client
        self.cm  = CampaignManager(client)
        self.agm = AdGroupManager(client)
        self.am  = AdManager(client)

    def process_unified(self, df: pd.DataFrame) -> list[UnifiedResult]:
        """
        統合シートの全行を処理する。

        - キャンペーン: 同じ「キャンペーン名」は初回のみ作成（キャッシュ）
        - 広告グループ: 同じ「(キャンペーン名, 広告グループ名)」は初回のみ作成
        - 広告: 全行で1件ずつ作成
        - 「キャンペーンID」「広告グループID」「広告ID」に既存IDがあればスキップ

        Returns: [UnifiedResult] （行ごと）
        """
        results: list[UnifiedResult] = []

        # キャッシュ
        campaign_cache: dict[str, str] = {}         # camp_name → campaign_id
        adgroup_cache: dict[tuple, str] = {}         # (camp_name, ag_name) → adgroup_id

        for i, row in df.iterrows():
            row_result = UnifiedResult(row_index=int(i) + 1)

            camp_name = _s(row, "キャンペーン名")
            ag_name   = _s(row, "広告グループ名")
            ad_name   = _s(row, "広告名")

            # 完全空行はスキップ
            if not camp_name and not ag_name and not ad_name:
                continue

            # ── キャンペーン ────────────────────────
            if camp_name:
                # 既存IDが書いてあればキャッシュに登録してスキップ
                existing_camp_id = _s(row, "キャンペーンID")
                if existing_camp_id:
                    campaign_cache[camp_name] = existing_camp_id
                    row_result.campaign_id = existing_camp_id
                elif camp_name in campaign_cache:
                    row_result.campaign_id = campaign_cache[camp_name]
                else:
                    try:
                        payload = _build_campaign_payload(row)
                        camp_id = self.cm.create(payload)
                        campaign_cache[camp_name] = camp_id
                        row_result.campaign_id = camp_id
                    except Exception as e:
                        row_result.status = "error"
                        row_result.error = f"キャンペーン作成失敗: {e}"
                        results.append(row_result)
                        continue

            # ── 広告グループ ─────────────────────────
            if ag_name:
                ag_key = (camp_name, ag_name)
                existing_ag_id = _s(row, "広告グループID")
                if existing_ag_id:
                    adgroup_cache[ag_key] = existing_ag_id
                    row_result.adgroup_id = existing_ag_id
                elif ag_key in adgroup_cache:
                    row_result.adgroup_id = adgroup_cache[ag_key]
                else:
                    try:
                        if not row_result.campaign_id:
                            raise ValueError("キャンペーンIDが取得できていません")
                        payload = _build_adgroup_payload(row, row_result.campaign_id)
                        ag_id = self.agm.create(payload)
                        adgroup_cache[ag_key] = ag_id
                        row_result.adgroup_id = ag_id
                    except Exception as e:
                        row_result.status = "error"
                        row_result.error = f"広告グループ作成失敗: {e}"
                        results.append(row_result)
                        continue

            # ── 広告 ─────────────────────────────────
            if ad_name:
                existing_ad_id = _s(row, "広告ID")
                if existing_ad_id:
                    row_result.ad_id = existing_ad_id
                    row_result.status = "skipped"
                else:
                    try:
                        if not row_result.adgroup_id:
                            raise ValueError("広告グループIDが取得できていません")
                        payload = _build_ad_payload(row, row_result.adgroup_id)
                        ad_id = self.am.create(payload)
                        row_result.ad_id = ad_id
                        row_result.status = "success"
                    except Exception as e:
                        row_result.status = "error"
                        row_result.error = f"広告作成失敗: {e}"

            results.append(row_result)

        success  = sum(1 for r in results if r.status == "success")
        skipped  = sum(1 for r in results if r.status == "skipped")
        errors   = sum(1 for r in results if r.status == "error")
        logger.info(
            f"一括入稿完了: 成功{success} / スキップ{skipped} / エラー{errors} / 合計{len(results)}件"
        )
        return results
