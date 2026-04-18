"""
Google Sheets連携 - 統合シート（キャンペーン/広告グループ/広告 を1シートで管理）
"""

from __future__ import annotations
from typing import Optional
from loguru import logger
import pandas as pd


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_NAME = "入稿データ"

# -------------------------------------------------------
# セクション別ヘッダー色
# -------------------------------------------------------
SECTION_COLORS = {
    "campaign": {"red": 0.67, "green": 0.84, "blue": 0.90},  # 水色
    "adgroup":  {"red": 0.72, "green": 0.88, "blue": 0.70},  # 緑
    "ad":       {"red": 1.00, "green": 0.90, "blue": 0.60},  # 黄
    "result":   {"red": 0.85, "green": 0.85, "blue": 0.85},  # グレー
}

SECTION_LABELS = {
    "campaign": "📁 キャンペーン",
    "adgroup":  "📂 広告グループ",
    "ad":       "📄 広告",
    "result":   "📊 結果（自動入力）",
}

# -------------------------------------------------------
# 統合シートの列定義
# options があれば → プルダウン、なければ → テキスト入力
# -------------------------------------------------------
UNIFIED_COLUMNS: list[dict] = [
    # ── キャンペーン ──────────────────────────────
    {
        "name": "キャンペーン名",
        "section": "campaign",
        "width": 180,
    },
    {
        "name": "目標タイプ",
        "section": "campaign",
        "width": 160,
        "options": [
            "トラフィック", "リーチ", "動画視聴", "コンバージョン",
            "アプリインストール", "リード獲得", "フォロー",
        ],
    },
    {
        "name": "キャンペーン予算タイプ",
        "section": "campaign",
        "width": 160,
        "options": ["無制限", "日予算", "総予算"],
    },
    {
        "name": "キャンペーン予算",
        "section": "campaign",
        "width": 130,
        "note": "予算タイプが「無制限」の場合は空欄でOK",
    },

    # ── 広告グループ ──────────────────────────────
    {
        "name": "広告グループ名",
        "section": "adgroup",
        "width": 180,
    },
    {
        "name": "配置タイプ",
        "section": "adgroup",
        "width": 120,
        "options": ["自動", "手動"],
    },
    {
        "name": "広告グループ予算タイプ",
        "section": "adgroup",
        "width": 160,
        "options": ["無制限", "日予算", "総予算"],
    },
    {
        "name": "広告グループ予算",
        "section": "adgroup",
        "width": 130,
    },
    {
        "name": "スケジュール",
        "section": "adgroup",
        "width": 130,
        "options": ["開始日から", "期間指定"],
    },
    {
        "name": "開始日時",
        "section": "adgroup",
        "width": 160,
        "note": "形式: 2024-07-01 00:00:00\n「期間指定」を選んだ場合に必須",
    },
    {
        "name": "終了日時",
        "section": "adgroup",
        "width": 160,
        "note": "形式: 2024-07-31 23:59:59\n「期間指定」を選んだ場合のみ入力",
    },
    {
        "name": "最適化目標",
        "section": "adgroup",
        "width": 140,
        "options": [
            "クリック", "リーチ", "コンバージョン",
            "動画再生", "フォロー", "インプレッション",
        ],
    },
    {
        "name": "入札タイプ",
        "section": "adgroup",
        "width": 120,
        "options": ["自動入札", "カスタム"],
    },
    {
        "name": "入札価格",
        "section": "adgroup",
        "width": 100,
        "note": "入札タイプが「カスタム」の場合のみ入力",
    },
    {
        "name": "性別",
        "section": "adgroup",
        "width": 100,
        "options": ["すべて", "男性", "女性"],
    },
    {
        "name": "年齢層",
        "section": "adgroup",
        "width": 200,
        "note": (
            "対象年齢をカンマ区切りで入力\n"
            "選択肢: AGE_13_17, AGE_18_24, AGE_25_34,\n"
            "AGE_35_44, AGE_45_54, AGE_55_100\n"
            "例: AGE_18_24,AGE_25_34\n"
            "空欄 = すべての年齢"
        ),
    },

    # ── 広告 ──────────────────────────────────────
    {
        "name": "広告名",
        "section": "ad",
        "width": 180,
    },
    {
        "name": "広告フォーマット",
        "section": "ad",
        "width": 140,
        "options": ["SINGLE_VIDEO", "IMAGE", "SPARK_ADS"],
    },
    {
        "name": "動画素材ID",
        "section": "ad",
        "width": 160,
        "note": "TikTok広告管理画面の「クリエイティブ」にあるvideo_id",
    },
    {
        "name": "サムネイル素材ID",
        "section": "ad",
        "width": 160,
        "note": "カバー画像のimage_id（省略可）",
    },
    {
        "name": "広告テキスト",
        "section": "ad",
        "width": 220,
    },
    {
        "name": "CTA",
        "section": "ad",
        "width": 160,
        "options": [
            "詳しくはこちら", "今すぐ購入", "アプリをダウンロード",
            "今すぐ申し込む", "今すぐ予約", "お問い合わせ",
            "今すぐ登録", "今すぐ視聴", "今すぐプレイ",
            "詳細を見る", "今すぐ注文", "今すぐ入手",
        ],
    },
    {
        "name": "ランディングURL",
        "section": "ad",
        "width": 220,
    },
    {
        "name": "表示名",
        "section": "ad",
        "width": 140,
        "note": "ブランド名や広告主名",
    },

    # ── 結果（自動入力） ──────────────────────────
    {
        "name": "ステータス",
        "section": "result",
        "width": 110,
    },
    {
        "name": "キャンペーンID",
        "section": "result",
        "width": 160,
    },
    {
        "name": "広告グループID",
        "section": "result",
        "width": 160,
    },
    {
        "name": "広告ID",
        "section": "result",
        "width": 160,
    },
    {
        "name": "エラー内容",
        "section": "result",
        "width": 240,
    },
]

# 列名一覧（シート読み込み時の参照用）
COLUMN_NAMES = [c["name"] for c in UNIFIED_COLUMNS]

# 結果列インデックス（0始まり）
_result_col_names = ["ステータス", "キャンペーンID", "広告グループID", "広告ID", "エラー内容"]


class GoogleSheetsManager:
    """Google Sheets 統合シート管理"""

    def __init__(self, spreadsheet_url: str, credentials_dict: dict):
        self.spreadsheet_url = spreadsheet_url
        self.credentials_dict = credentials_dict
        self._gc = None
        self._ss = None

    # -------------------------------------------------------
    # 接続
    # -------------------------------------------------------

    def _client(self):
        if self._gc is None:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
            except ImportError:
                raise ImportError("pip install gspread google-auth が必要です")
            creds = Credentials.from_service_account_info(
                self.credentials_dict, scopes=SCOPES
            )
            self._gc = gspread.authorize(creds)
        return self._gc

    def _spreadsheet(self):
        if self._ss is None:
            self._ss = self._client().open_by_url(self.spreadsheet_url)
        return self._ss

    def _worksheet(self, create: bool = False):
        ss = self._spreadsheet()
        try:
            return ss.worksheet(SHEET_NAME)
        except Exception:
            if create:
                ws = ss.add_worksheet(
                    title=SHEET_NAME,
                    rows=1000,
                    cols=len(UNIFIED_COLUMNS) + 2,
                )
                return ws
            raise

    # -------------------------------------------------------
    # テンプレート初期化
    # -------------------------------------------------------

    def initialize_template(self):
        """
        統合シートを作成（既存は上書き）し、
        ヘッダー色・プルダウン・列幅・セルメモを一括設定する
        """
        ss = self._spreadsheet()

        # シートが既にあれば削除して再作成
        try:
            existing = ss.worksheet(SHEET_NAME)
            # 全データをクリアして再利用
            existing.clear()
            ws = existing
            logger.info(f"既存シートをクリア: {SHEET_NAME}")
        except Exception:
            ws = ss.add_worksheet(
                title=SHEET_NAME,
                rows=1000,
                cols=len(UNIFIED_COLUMNS) + 2,
            )
            logger.info(f"シート作成: {SHEET_NAME}")

        # ── 1. ヘッダー行を書き込む ──
        ws.append_row(COLUMN_NAMES, value_input_option="RAW")

        # ── 2. Google Sheets API で一括フォーマット ──
        sheet_id = ws.id
        requests = []

        for col_idx, col_def in enumerate(UNIFIED_COLUMNS):
            section = col_def["section"]
            color = SECTION_COLORS[section]

            # ヘッダーセルの背景色・太字
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color,
                            "textFormat": {"bold": True, "fontSize": 10},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                }
            })

            # データ行の背景色（薄め）
            data_color = {k: 0.95 + v * 0.05 for k, v in color.items()}  # 薄い版
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": data_color,
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor)",
                }
            })

            # プルダウン設定
            if col_def.get("options"):
                requests.append({
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": v}
                                    for v in col_def["options"]
                                ],
                            },
                            "showCustomUi": True,
                            "strict": False,
                        },
                    }
                })

            # 列幅
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": col_idx,
                        "endIndex": col_idx + 1,
                    },
                    "properties": {"pixelSize": col_def.get("width", 140)},
                    "fields": "pixelSize",
                }
            })

        # ヘッダー行を固定（スクロールしても見える）
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        # ── 一括実行 ──
        ss.batch_update({"requests": requests})

        # ── 3. セルメモを追加（note があるもの） ──
        notes = {}
        for col_idx, col_def in enumerate(UNIFIED_COLUMNS):
            if col_def.get("note"):
                import gspread.utils as gu
                cell_a1 = gu.rowcol_to_a1(1, col_idx + 1)
                notes[cell_a1] = col_def["note"]

        if notes:
            for cell_a1, note in notes.items():
                ws.update_note(cell_a1, note)

        logger.success(f"✅ テンプレートシート初期化完了: {SHEET_NAME}")

    # -------------------------------------------------------
    # 読み込み
    # -------------------------------------------------------

    def read_data(self) -> pd.DataFrame:
        """統合シートを DataFrame として読み込む"""
        ws = self._worksheet()
        records = ws.get_all_records(expected_headers=COLUMN_NAMES)
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=COLUMN_NAMES)
        # 空行（全列が空文字）を除外
        non_empty = df.apply(
            lambda row: row.astype(str).str.strip().any(), axis=1
        )
        df = df[non_empty].reset_index(drop=True)
        logger.info(f"データ読み込み: {len(df)}行")
        return df

    # -------------------------------------------------------
    # 結果書き戻し
    # -------------------------------------------------------

    def write_results(self, results: list[dict]):
        """
        入稿結果をシートに書き戻す

        results: [
          {
            "row_index": int,  # 1始まり（データ行番号、ヘッダーを除く）
            "status": str,
            "campaign_id": str,
            "adgroup_id": str,
            "ad_id": str,
            "error": str,
          }
        ]
        """
        if not results:
            return

        import gspread

        ws = self._worksheet()
        headers = ws.row_values(1)

        def col_of(name: str) -> Optional[int]:
            try:
                return headers.index(name) + 1
            except ValueError:
                return None

        col_status   = col_of("ステータス")
        col_camp_id  = col_of("キャンペーンID")
        col_ag_id    = col_of("広告グループID")
        col_ad_id    = col_of("広告ID")
        col_err      = col_of("エラー内容")

        cells: list[gspread.Cell] = []
        for r in results:
            sheet_row = r["row_index"] + 1  # +1 はヘッダー行分
            if col_status:
                cells.append(gspread.Cell(sheet_row, col_status, r.get("status", "")))
            if col_camp_id:
                cells.append(gspread.Cell(sheet_row, col_camp_id, r.get("campaign_id", "")))
            if col_ag_id:
                cells.append(gspread.Cell(sheet_row, col_ag_id, r.get("adgroup_id", "")))
            if col_ad_id:
                cells.append(gspread.Cell(sheet_row, col_ad_id, r.get("ad_id", "")))
            if col_err:
                cells.append(gspread.Cell(sheet_row, col_err, r.get("error", "")))

        if cells:
            ws.update_cells(cells, value_input_option="RAW")
            logger.success(f"✅ 結果書き戻し完了: {len(results)}行")
