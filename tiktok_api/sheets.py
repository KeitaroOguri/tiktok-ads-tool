"""
Google Sheets連携 - 一括入稿データの読み書き
"""

from __future__ import annotations
from typing import Optional
from loguru import logger
import pandas as pd


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# シート名
SHEET_CAMPAIGNS = "キャンペーン"
SHEET_ADGROUPS = "広告グループ"
SHEET_ADS = "広告"

# 列定義
CAMPAIGN_COLUMNS = [
    "キャンペーン名",
    "目標タイプ",       # REACH / TRAFFIC / VIDEO_VIEWS / CONVERSIONS / APP_INSTALLS
    "予算タイプ",       # 無制限 / 日予算 / 総予算
    "予算",
    "ステータス",       # ← 入稿結果が書き戻される
    "作成済みID",
    "エラー内容",
]

ADGROUP_COLUMNS = [
    "キャンペーン名",   # 紐付けるキャンペーン名（または作成済みIDをそのまま入力可）
    "広告グループ名",
    "配置タイプ",       # 自動 / 手動
    "予算タイプ",       # 無制限 / 日予算 / 総予算
    "日予算",
    "スケジュール",     # 開始日から / 期間指定
    "開始日時",         # YYYY-MM-DD HH:MM:SS
    "終了日時",
    "最適化目標",       # クリック / リーチ / コンバージョン / 動画再生
    "入札タイプ",       # 自動入札 / カスタム
    "入札価格",
    "ターゲット地域",   # 地域IDをカンマ区切り
    "年齢層",           # AGE_13_17,AGE_18_24 等カンマ区切り
    "性別",             # すべて / 男性 / 女性
    "ステータス",
    "作成済みID",
    "エラー内容",
]

AD_COLUMNS = [
    "広告グループ名",   # 紐付ける広告グループ名
    "広告名",
    "広告フォーマット", # SINGLE_VIDEO / IMAGE 等
    "動画素材ID",       # TikTok上の video_id
    "サムネイル素材ID", # image_id
    "広告テキスト",
    "CTA",              # 詳しくはこちら / 今すぐ購入 等
    "ランディングURL",
    "表示名",
    "ステータス",
    "作成済みID",
    "エラー内容",
]


class GoogleSheetsManager:
    """Google Sheets連携マネージャー"""

    def __init__(self, spreadsheet_url: str, credentials_dict: dict):
        self.spreadsheet_url = spreadsheet_url
        self.credentials_dict = credentials_dict
        self._gc = None
        self._spreadsheet = None

    # -------------------------------------------------------
    # 接続
    # -------------------------------------------------------

    def _get_client(self):
        if self._gc is None:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
            except ImportError:
                raise ImportError(
                    "gspread と google-auth が必要です: pip install gspread google-auth"
                )
            creds = Credentials.from_service_account_info(
                self.credentials_dict, scopes=SCOPES
            )
            self._gc = gspread.authorize(creds)
        return self._gc

    def _get_spreadsheet(self):
        if self._spreadsheet is None:
            gc = self._get_client()
            self._spreadsheet = gc.open_by_url(self.spreadsheet_url)
        return self._spreadsheet

    def _get_or_create_worksheet(self, name: str, headers: list[str]):
        ss = self._get_spreadsheet()
        try:
            return ss.worksheet(name)
        except Exception:
            ws = ss.add_worksheet(title=name, rows=1000, cols=len(headers) + 2)
            ws.append_row(headers)
            logger.info(f"シート作成: {name}")
            return ws

    # -------------------------------------------------------
    # テンプレート初期化
    # -------------------------------------------------------

    def initialize_template(self):
        """3つのシートをテンプレートとして作成"""
        self._get_or_create_worksheet(SHEET_CAMPAIGNS, CAMPAIGN_COLUMNS)
        self._get_or_create_worksheet(SHEET_ADGROUPS, ADGROUP_COLUMNS)
        self._get_or_create_worksheet(SHEET_ADS, AD_COLUMNS)
        logger.success("✅ テンプレートシート作成完了")

    # -------------------------------------------------------
    # 読み込み
    # -------------------------------------------------------

    def _read_sheet(self, sheet_name: str) -> pd.DataFrame:
        ss = self._get_spreadsheet()
        ws = ss.worksheet(sheet_name)
        records = ws.get_all_records()
        return pd.DataFrame(records) if records else pd.DataFrame()

    def read_campaigns(self) -> pd.DataFrame:
        df = self._read_sheet(SHEET_CAMPAIGNS)
        logger.info(f"キャンペーン読み込み: {len(df)}行")
        return df

    def read_adgroups(self) -> pd.DataFrame:
        df = self._read_sheet(SHEET_ADGROUPS)
        logger.info(f"広告グループ読み込み: {len(df)}行")
        return df

    def read_ads(self) -> pd.DataFrame:
        df = self._read_sheet(SHEET_ADS)
        logger.info(f"広告読み込み: {len(df)}行")
        return df

    # -------------------------------------------------------
    # 結果書き戻し
    # -------------------------------------------------------

    def write_results(self, sheet_name: str, results: list[dict]):
        """
        入稿結果をシートに書き戻す
        results: [{"row_index": int (1始まり), "status": str, "created_id": str, "error": str}]
        """
        if not results:
            return

        ss = self._get_spreadsheet()
        ws = ss.worksheet(sheet_name)
        headers = ws.row_values(1)

        def col_idx(name: str) -> Optional[int]:
            try:
                return headers.index(name) + 1
            except ValueError:
                return None

        status_col = col_idx("ステータス")
        id_col = col_idx("作成済みID")
        err_col = col_idx("エラー内容")

        if not status_col:
            logger.warning(f"「ステータス」列が見つかりません: {sheet_name}")
            return

        import gspread
        cell_updates = []
        for r in results:
            row = r["row_index"] + 1  # ヘッダー行分 +1
            if status_col:
                cell_updates.append(
                    gspread.Cell(row, status_col, r.get("status", ""))
                )
            if id_col:
                cell_updates.append(
                    gspread.Cell(row, id_col, r.get("created_id", ""))
                )
            if err_col:
                cell_updates.append(
                    gspread.Cell(row, err_col, r.get("error", ""))
                )

        ws.update_cells(cell_updates)
        logger.success(f"✅ シート書き戻し完了: {sheet_name} ({len(results)}行)")
