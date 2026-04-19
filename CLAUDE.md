# CLAUDE.md

此檔案為 Claude Code（claude.ai/code）在此專案中工作時提供指引。

## 啟動應用程式

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

應用程式運行於 `http://localhost:8501`。此專案無建置步驟、測試套件或 linter 設定。

## 架構總覽

這是一個以 Streamlit 建構的台股技術分析儀表板，資料流分為三層：

**資料擷取層**
- [data_fetcher.py](data_fetcher.py) — 封裝 yfinance；定義 25 檔預設股票（`DEFAULT_STOCKS`）及中文名稱對照表（`STOCK_NAMES`）
- [market_fetcher.py](market_fetcher.py) — 查詢台灣證券交易所（TWSE）REST API 取得全市場交易資料；將股票代號對應至 16 個產業分類
- [etf_fetcher.py](etf_fetcher.py) — 爬取 wantgoo.com 取得 ETF 成分股（0050、0056、00878、00929、00940）；若爬取失敗則回退至 `FALLBACK_STOCKS`（120+ 檔快取股票）
- [news_scraper.py](news_scraper.py) — 彙整 5 個 RSS 來源（鉅亨網、Yahoo 財經、聯合報、工商時報），去除重複後對應至個股

**處理層**
- [technical_analysis.py](technical_analysis.py) — 計算 RSI（14）、MACD（12/26/9）、布林通道（20 日 ±2σ）、MA5/10/20/60 及量比；`get_signal()` 以加權方式將每檔股票評分為 -100 至 +100
- [screener.py](screener.py) — 以批次方式執行三種掃描模式：25 檔預設股票（`run_screener`）、ETF 成分股（`run_etf_screener`）、成交值前 N 名（`run_market_screener`）

**呈現層**
- [app.py](app.py) — Streamlit UI，分為兩大模式：全市場掃描與個股查詢；呈現摘要卡片、產業強弱圖、三欄訊號排版，以及附技術指標的 K 線圖

## 訊號評分

[technical_analysis.py](technical_analysis.py) 中的 `get_signal()` 輸出整數分數，並對應至五個類別：

| 分數 | 標籤 |
|------|------|
| ≥ 50 | 🟢 被錯殺 |
| 20–49 | 🔵 考慮買進 |
| -15–19 | ⚪ 觀望 |
| -40 至 -16 | 🟠 偏空觀望 |
| ≤ -40 | 🔴 注意退場 |

主要評分權重：RSI < 30 → +30、MACD 黃金交叉 → +25、觸及布林下軌 → +20、MA5 > MA20 → +20、量增價漲 → +15（空頭條件反向扣分）。

## 資料來源

- **股價：** Yahoo Finance（`yfinance`，代號加 `.TW` 後綴，例如 `2330.TW`）
- **市場清單：** TWSE REST API — 於 [market_fetcher.py](market_fetcher.py) 中自動處理週末／假日日期回退
- **ETF 持股：** 爬取 wantgoo.com，失敗時使用快取
- **新聞：** RSS feeds，無需 API 金鑰

## 重要實作說明

- 無資料庫，所有資料在每次掃描時即時擷取
- `etf_fetcher.py` 內建大量 `FALLBACK_STOCKS`，確保爬取失敗時 ETF 掃描模式仍可運作
- TWSE API 在週末回傳空資料，[market_fetcher.py](market_fetcher.py) 中的 `get_top_stocks_by_value()` 會自動向前回退查詢日期
- 產業分類（16 類）透過 [market_fetcher.py](market_fetcher.py) 中的 `get_sector_from_code()` 依股票代號前綴範圍判斷
