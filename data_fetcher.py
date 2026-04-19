"""
台股資料抓取模組
使用 yfinance，台股代號格式：2330.TW
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta


# 常用台股清單（可自行擴充）
DEFAULT_STOCKS = {
    "半導體": ["2330.TW", "2303.TW", "2308.TW", "2454.TW", "3711.TW"],
    "金融": ["2882.TW", "2881.TW", "2886.TW", "2884.TW", "2891.TW"],
    "電子": ["2317.TW", "2354.TW", "2382.TW", "2357.TW", "3045.TW"],
    "傳產": ["1301.TW", "1303.TW", "2002.TW", "1402.TW", "2207.TW"],
    "生技": ["4711.TW", "6547.TW", "4743.TW", "1786.TW", "6446.TW"],
}

STOCK_NAMES = {
    "2330.TW": "台積電", "2303.TW": "聯電", "2308.TW": "台達電",
    "2454.TW": "聯發科", "3711.TW": "日月光投控", "2882.TW": "國泰金",
    "2881.TW": "富邦金", "2886.TW": "兆豐金", "2884.TW": "玉山金",
    "2891.TW": "中信金", "2317.TW": "鴻海", "2354.TW": "鴻準",
    "2382.TW": "廣達", "2357.TW": "華碩", "3045.TW": "台灣大",
    "1301.TW": "台塑", "1303.TW": "南亞", "2002.TW": "中鋼",
    "1402.TW": "遠東新", "2207.TW": "和泰車", "4711.TW": "中裕",
    "6547.TW": "高端疫苗", "4743.TW": "合世生醫", "1786.TW": "科妍",
    "6446.TW": "藥華藥",
}


def get_stock_data(ticker: str, period: str = "3mo") -> pd.DataFrame | None:
    """
    抓取單一股票歷史資料
    period: 1mo, 3mo, 6mo, 1y
    """
    import logging
    import contextlib
    import io
    try:
        stock = yf.Ticker(ticker)
        # 抑制 yfinance 的 "possibly delisted" stderr 輸出
        with contextlib.redirect_stderr(io.StringIO()):
            df = stock.history(period=period)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        return df
    except Exception as e:
        print(f"[ERROR] 抓取 {ticker} 失敗: {e}")
        return None


def get_multiple_stocks(tickers: list[str], period: str = "3mo") -> dict[str, pd.DataFrame]:
    """批次抓取多支股票資料"""
    result = {}
    for ticker in tickers:
        df = get_stock_data(ticker, period)
        if df is not None:
            result[ticker] = df
    return result


def get_all_default_stocks(period: str = "3mo") -> dict[str, pd.DataFrame]:
    """抓取所有預設清單股票"""
    all_tickers = [t for tickers in DEFAULT_STOCKS.values() for t in tickers]
    return get_multiple_stocks(all_tickers, period)


def get_stock_info(ticker: str) -> dict:
    """取得股票基本資訊"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "名稱": STOCK_NAMES.get(ticker, info.get("longName", ticker)),
            "產業": info.get("industry", "N/A"),
            "市值": info.get("marketCap", 0),
            "本益比": info.get("trailingPE", None),
            "股價淨值比": info.get("priceToBook", None),
        }
    except Exception:
        return {"名稱": STOCK_NAMES.get(ticker, ticker)}


def get_display_name(ticker: str) -> str:
    """回傳顯示名稱，例如 '台積電 (2330)'"""
    code = ticker.replace(".TW", "")
    name = STOCK_NAMES.get(ticker, ticker)
    return f"{name} ({code})"
