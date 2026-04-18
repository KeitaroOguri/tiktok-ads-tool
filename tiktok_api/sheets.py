"""
Google Sheets連携 - 統合シート（TikTokエクスポート形式準拠）

列名はTikTok広告管理画面のエクスポートExcelと同じ日本語名を使用。
→ エクスポートしたExcelをそのままコピーして貼り付けることができる。
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
    "adgroup":  "📂 広告グループ（広告セット）",
    "ad":       "📄 広告",
    "result":   "📊 結果（自動入力）",
}

# -------------------------------------------------------
# 統合シートの列定義（TikTokエクスポート形式準拠）
# options があれば → プルダウン、なければ → テキスト入力
# -------------------------------------------------------
UNIFIED_COLUMNS: list[dict] = [

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 【キャンペーン】
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "キャンペーン名",
        "section": "campaign",
        "width": 220,
    },
    {
        "name": "目的",
        "section": "campaign",
        "width": 160,
        "options": [
            "Sales", "Traffic", "Reach", "Video Views",
            "App Installs", "Lead Generation", "Followers",
        ],
        "note": "TikTok広告管理の目的\nSales=コンバージョン / Traffic=トラフィック\nVideo Views=動画視聴 / App Installs=アプリインストール",
    },
    {
        "name": "キャンペーン予算タイプ",
        "section": "campaign",
        "width": 160,
        "options": ["Daily", "Lifetime", "No Limit"],
        "note": "Daily=日予算 / Lifetime=総予算 / No Limit=無制限",
    },
    {
        "name": "キャンペーン予算",
        "section": "campaign",
        "width": 130,
        "note": "予算タイプが「No Limit」の場合は空欄でOK（単位: 円）",
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 【広告グループ（広告セット）】
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "広告セット名",
        "section": "adgroup",
        "width": 220,
    },
    {
        "name": "プレースメントタイプ",
        "section": "adgroup",
        "width": 160,
        "options": ["Automatic", "Select"],
        "note": "Automatic=自動配置 / Select=手動配置",
    },
    {
        "name": "プレースメント",
        "section": "adgroup",
        "width": 160,
        "note": "プレースメントタイプがSelectのときのみ入力\n例: TikTok, Pangle",
    },
    {
        "name": "TikTok ピクセル ID",
        "section": "adgroup",
        "width": 180,
        "note": "コンバージョン追跡用ピクセルID\n例: CVCI6QJC77UDL07BVQP0",
    },
    {
        "name": "ピクセルイベント",
        "section": "adgroup",
        "width": 130,
        "note": "ピクセルのイベントコード（数値）\n例: 96 (CompletePayment)",
    },
    {
        "name": "ユーザーリスト設定ID",
        "section": "adgroup",
        "width": 180,
        "note": "カスタムオーディエンスID（カンマ区切りで複数可）",
    },
    {
        "name": "ユーザーリスト除外ID",
        "section": "adgroup",
        "width": 180,
        "note": "除外オーディエンスID（カンマ区切りで複数可）",
    },
    {
        "name": "ロケーション",
        "section": "adgroup",
        "width": 200,
        "note": (
            "地域IDをカンマ区切りで入力（Lプレフィックスは不要）\n"
            "例: 1865694,1864226,...\n"
            "空欄 = 日本（7709）が自動セットされます"
        ),
    },
    {
        "name": "性別",
        "section": "adgroup",
        "width": 100,
        "options": ["All", "Male", "Female"],
        "note": "All=すべて / Male=男性 / Female=女性",
    },
    {
        "name": "年齢",
        "section": "adgroup",
        "width": 180,
        "note": (
            "年齢層をカンマ区切りで入力\n"
            "例: 18-24,25-34,35-44\n"
            "All または空欄 = すべての年齢"
        ),
    },
    {
        "name": "言語",
        "section": "adgroup",
        "width": 100,
        "note": "言語コード（例: ja=日本語, en=英語）\n空欄 = すべての言語",
    },
    {
        "name": "広告セット予算タイプ",
        "section": "adgroup",
        "width": 160,
        "options": ["Daily", "Lifetime", "No Limit", ""],
        "note": "Daily=日予算 / Lifetime=総予算 / No Limit or 空欄=無制限",
    },
    {
        "name": "広告セット予算",
        "section": "adgroup",
        "width": 130,
        "note": "広告グループレベルの予算（単位: 円）\n空欄 = キャンペーン予算に従う",
    },
    {
        "name": "開始時刻",
        "section": "adgroup",
        "width": 180,
        "note": "形式: 2024/4/1 0:00 または 2024-04-01 00:00:00\n空欄 = 入稿時刻が自動セット",
    },
    {
        "name": "終了時刻",
        "section": "adgroup",
        "width": 180,
        "note": "形式: 2024/7/31 23:59 または No Limit（空欄）\nNo Limit または空欄 = 終了なし",
    },
    {
        "name": "最適化の目標",
        "section": "adgroup",
        "width": 160,
        "options": ["Conversion", "Click", "Reach", "Video Play", "Follow", "Impression"],
        "note": "Conversion=コンバージョン / Click=クリック\nVideo Play=動画再生 / Follow=フォロー",
    },
    {
        "name": "課金イベント",
        "section": "adgroup",
        "width": 120,
        "options": ["oCPM", "CPM", "CPC", "CPV"],
        "note": "oCPM=最適化インプレッション / CPM=インプレッション\nCPC=クリック / CPV=動画再生",
    },
    {
        "name": "入札タイプ",
        "section": "adgroup",
        "width": 140,
        "options": ["Lowest Cost", "Cost Cap", "Bid Cap"],
        "note": "Lowest Cost=自動入札（入札額不要）\nCost Cap / Bid Cap=手動入札（入札額必須）",
    },
    {
        "name": "入札",
        "section": "adgroup",
        "width": 100,
        "note": "入札タイプが Cost Cap / Bid Cap のときのみ入力（単位: 円）",
    },
    {
        "name": "フリークエンシー上限",
        "section": "adgroup",
        "width": 140,
        "note": "1ユーザーへの最大表示回数\n例: 2 （2回/7日など）",
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 【広告】
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "広告名",
        "section": "ad",
        "width": 200,
    },
    {
        "name": "広告フォーマット",
        "section": "ad",
        "width": 140,
        "options": ["Single video", "Image", "Spark Ads"],
        "note": "Single video=単一動画 / Image=画像広告 / Spark Ads=スパーク広告",
    },
    {
        "name": "動画名",
        "section": "ad",
        "width": 200,
        "note": (
            "TikTokクリエイティブライブラリの動画名（参照用）\n"
            "★ 動画を新規アップロードする場合は「Google Drive動画URL」を使用してください"
        ),
    },
    {
        "name": "Google Drive動画URL",
        "section": "ad",
        "width": 260,
        "note": (
            "Google DriveのファイルURL（「動画名」で既存動画を指定しない場合に自動アップロード）\n"
            "例: https://drive.google.com/file/d/xxxxx/view\n"
            "⚠️ サービスアカウントとファイルを共有してください:\n"
            "tiktok-ads-tool@winged-vigil-371710.iam.gserviceaccount.com"
        ),
    },
    {
        "name": "テキスト",
        "section": "ad",
        "width": 260,
        "note": "広告のキャプションテキスト（絵文字OK）",
    },
    {
        "name": "CTAタイプ",
        "section": "ad",
        "width": 160,
        "options": [
            "Learn More", "Shop Now", "Download",
            "Apply Now", "Book Now", "Contact Us",
            "Sign Up", "Watch Now", "Play Game",
            "View More", "Order Now", "Get Now",
            "Dynamic",
        ],
        "note": (
            "CTA（コール・トゥ・アクション）\n"
            "Dynamic = TikTokが自動で最適なCTAを選択\n"
            "Learn More = 詳しくはこちら"
        ),
    },
    {
        "name": "Web URL",
        "section": "ad",
        "width": 280,
        "note": "ランディングページURL\n例: https://example.com/?ttclid=__CLICKID__",
    },
    {
        "name": "アイデンティティタイプ",
        "section": "ad",
        "width": 180,
        "options": ["TTBC Authorized Post", "CUSTOM_USER", "AUTH_CODE"],
        "note": (
            "TikTokアカウントのアイデンティティタイプ\n"
            "TTBC Authorized Post = BC認証済みアカウント"
        ),
    },
    {
        "name": "アイデンティティID",
        "section": "ad",
        "width": 240,
        "note": "アイデンティティのID（「id:」プレフィックスは不要）\n例: f3fcd787-c94d-5b86-a8d4-49740e624dcd",
    },
    {
        "name": "インプレッショントラッキング URL",
        "section": "ad",
        "width": 260,
        "note": "インプレッション計測用サードパーティトラッキングURL（省略可）",
    },
    {
        "name": "クリックトラッキングURL",
        "section": "ad",
        "width": 260,
        "note": "クリック計測用サードパーティトラッキングURL（省略可）",
    },

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 【結果（自動入力）】
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    {
        "name": "ステータス",
        "section": "result",
        "width": 110,
        "note": "入稿後に自動入力: success / skipped / error",
    },
    {
        "name": "キャンペーンID",
        "section": "result",
        "width": 180,
        "note": "入稿後に自動入力。既存IDを書いておくと再作成をスキップします",
    },
    {
        "name": "広告セット ID",
        "section": "result",
        "width": 180,
        "note": "入稿後に自動入力。既存IDを書いておくと再作成をスキップします",
    },
    {
        "name": "広告ID",
        "section": "result",
        "width": 180,
        "note": "入稿後に自動入力。既存IDを書いておくと再入稿をスキップします",
    },
    {
        "name": "エラー内容",
        "section": "result",
        "width": 300,
        "note": "エラーが発生した場合のメッセージ",
    },
]

# 列名一覧（シート読み込み時の参照用）
COLUMN_NAMES = [c["name"] for c in UNIFIED_COLUMNS]


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
            data_color = {k: min(1.0, 0.95 + v * 0.05) for k, v in color.items()}
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
            opts = [o for o in col_def.get("options", []) if o != ""]
            if opts:
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
                                    for v in opts
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

        # ヘッダー行を固定
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        ss.batch_update({"requests": requests})

        # ── 3. セルメモを追加 ──
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
            "video_id": str,   # Drive経由アップロード時: "動画名"列に書き戻す
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
        col_ag_id    = col_of("広告セット ID")
        col_ad_id    = col_of("広告ID")
        col_err      = col_of("エラー内容")
        col_video    = col_of("動画名")   # Drive経由アップロード時にvideo_idを書き戻す

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
            # Drive経由でアップロードしたvideo_idを「動画名」列に書き戻す
            if col_video and r.get("video_id"):
                cells.append(gspread.Cell(sheet_row, col_video, r.get("video_id", "")))

        if cells:
            ws.update_cells(cells, value_input_option="RAW")
            logger.success(f"✅ 結果書き戻し完了: {len(results)}行")
