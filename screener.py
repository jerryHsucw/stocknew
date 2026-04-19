"""
選股篩選模組
整合資料抓取 + 技術分析，批次產出選股清單
"""
from data_fetcher import get_multiple_stocks, DEFAULT_STOCKS, get_display_name, STOCK_NAMES
from technical_analysis import get_signal, get_sector_strength, add_all_indicators, get_short_term_signal
from market_fetcher import get_top_stocks_by_volume, get_sector_from_code
from etf_fetcher import get_etf_tickers
from institutional_fetcher import get_all_institutional_data, fetch_institutional_history, fetch_institutional_history_all
import pandas as pd


def _inst_row(inst_data: dict) -> dict:
    """將個股法人資料轉為 DataFrame 欄位（皆以張為單位）"""
    return {
        "三大法人(張)": inst_data.get("institutional_net", 0),
        "外資(張)":     inst_data.get("foreign_net", 0),
        "投信(張)":     inst_data.get("trust_net", 0),
        "自營商(張)":   inst_data.get("dealer_net", 0),
        "融資餘額(張)": inst_data.get("margin_balance", 0),
        "融券餘額(張)": inst_data.get("short_balance", 0),
        "借券餘額(張)": inst_data.get("lending_balance", 0),
        "借券賣出(張)": inst_data.get("lending_sell", 0),
    }


def run_screener(custom_tickers: list[str] | None = None, period: str = "3mo") -> pd.DataFrame:
    """
    對預設（或自訂）清單執行全面掃描
    回傳 DataFrame，每列代表一支股票的分析結果
    """
    if custom_tickers:
        tickers = custom_tickers
    else:
        tickers = [t for tickers in DEFAULT_STOCKS.values() for t in tickers]

    stock_data = get_multiple_stocks(tickers, period=period)
    inst_all = get_all_institutional_data()

    # 建立 ticker → 類股 的對應表（用 DEFAULT_STOCKS 原本的分類）
    ticker_to_sector = {}
    for sector, sector_tickers in DEFAULT_STOCKS.items():
        for t in sector_tickers:
            ticker_to_sector[t] = sector

    rows = []
    for ticker, df in stock_data.items():
        code = ticker.replace(".TW", "")
        inst_data = inst_all.get(code, {})
        sig = get_signal(df, inst_data=inst_data)
        rows.append({
            "代號": code,
            "名稱": STOCK_NAMES.get(ticker, ticker),
            "訊號": sig["signal"],
            "評分": sig["score"],
            "收盤價": round(sig.get("close", 0), 2),
            "RSI": round(sig["rsi"], 1) if sig.get("rsi") else None,
            "MA5": round(sig.get("ma5", 0), 2) if sig.get("ma5") else None,
            "MA20": round(sig.get("ma20", 0), 2) if sig.get("ma20") else None,
            "原因": "、".join(sig["reasons"]),
            "_ticker": ticker,
            "_sector": ticker_to_sector.get(ticker, "其他"),
            **_inst_row(inst_data),
        })

    df_result = pd.DataFrame(rows)
    if df_result.empty:
        return df_result

    df_result = df_result.sort_values("評分", ascending=False).reset_index(drop=True)
    return df_result


def run_market_screener(top_n: int = 150, period: str = "3mo") -> tuple[pd.DataFrame, str]:
    """
    從證交所抓全市場，取成交量前 top_n 大進行掃描
    回傳 (結果 DataFrame, 狀態訊息)
    """
    stock_list = get_top_stocks_by_volume(top_n)
    if not stock_list:
        return pd.DataFrame(), "無法取得證交所資料，請確認網路或改用精選清單"

    tickers = [s["ticker"] for s in stock_list]
    name_map = {s["ticker"]: s["name"] for s in stock_list}

    stock_data = get_multiple_stocks(tickers, period=period)
    inst_all = get_all_institutional_data()

    rows = []
    for ticker, df in stock_data.items():
        code = ticker.replace(".TW", "")
        inst_data = inst_all.get(code, {})
        sig = get_signal(df, inst_data=inst_data)
        rows.append({
            "代號": code,
            "名稱": name_map.get(ticker, code),
            "訊號": sig["signal"],
            "評分": sig["score"],
            "收盤價": round(sig.get("close", 0), 2),
            "RSI": round(sig["rsi"], 1) if sig.get("rsi") else None,
            "MA5": round(sig.get("ma5", 0), 2) if sig.get("ma5") else None,
            "MA20": round(sig.get("ma20", 0), 2) if sig.get("ma20") else None,
            "原因": "、".join(sig["reasons"]),
            "_ticker": ticker,
            "_sector": get_sector_from_code(code),
            **_inst_row(inst_data),
        })

    df_result = pd.DataFrame(rows)
    if df_result.empty:
        return df_result, "掃描結果為空"

    df_result = df_result.sort_values("評分", ascending=False).reset_index(drop=True)
    status = f"已掃描成交量前 {top_n} 大上市股票，成功取得 {len(df_result)} 支資料"
    return df_result, status


def filter_by_signal(df: pd.DataFrame, signal_type: str) -> pd.DataFrame:
    """
    signal_type: "被錯殺" | "考慮買進" | "注意退場" | "偏空觀望"
    """
    return df[df["訊號"] == signal_type].copy()


def get_sector_summary(df: pd.DataFrame) -> pd.DataFrame:
    """計算各類股平均評分（排除資料不足的股票）"""
    df = df.copy()

    # 優先用 _sector 欄位（全市場模式），否則用預設清單對應
    if "_sector" not in df.columns:
        ticker_to_sector = {}
        for sector, tickers in DEFAULT_STOCKS.items():
            for t in tickers:
                ticker_to_sector[t] = sector
        df["_sector"] = df["_ticker"].map(ticker_to_sector).fillna("其他")

    df["類股"] = df["_sector"]

    # 排除資料不足，避免 0 分影響平均
    valid_df = df[df["訊號"] != "資料不足"]

    sector_df = (
        valid_df.groupby("類股")["評分"]
        .mean()
        .round(1)
        .reset_index()
        .rename(columns={"評分": "平均評分"})
        .sort_values("平均評分", ascending=False)
    )
    return sector_df


def get_top_picks(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """評分最高的前 N 支（考慮買進）"""
    return df[df["評分"] > 0].head(top_n)


def get_exit_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """退場候選（評分最低）"""
    return df[df["評分"] < -15].tail(10)


def run_short_term_screener(
    n_days: int = 5,
    scan_mode: str = "精選",   # "精選" | "ETF" | "全市場"
    top_n: int = 150,
) -> tuple[pd.DataFrame, str]:
    """
    近期強弱掃描：以短線評分規則分析近 n_days 個交易日的多空強弱。
    資料下載期間固定 1mo（確保 MA5、KD9 可正常計算）。
    同時抓取三大法人歷史，判斷連續買賣超天數。
    """
    # ── 取得股票清單 ────────────────────────────────────────
    if scan_mode == "ETF":
        tickers, msg, name_map = get_etf_tickers()
        if not tickers:
            return pd.DataFrame(), "無法取得ETF成分股資料"
    elif scan_mode == "全市場":
        stock_list = get_top_stocks_by_volume(top_n)
        if not stock_list:
            return pd.DataFrame(), "無法取得證交所資料"
        tickers  = [s["ticker"] for s in stock_list]
        name_map = {s["ticker"].replace(".TW", ""): s["name"] for s in stock_list}
        msg = f"全市場前 {top_n} 大（依成交量）"
    else:
        tickers  = [t for ts in DEFAULT_STOCKS.values() for t in ts]
        name_map = {t.replace(".TW", ""): STOCK_NAMES.get(t, t) for t in tickers}
        msg = "精選清單（25支）"

    # ── 下載價格資料 ─────────────────────────────────────────
    stock_data = get_multiple_stocks(tickers, period="3mo")

    # ── 批次抓取法人歷史（n_days 次 API，非 n_stocks × n_days）──
    inst_hist_map = fetch_institutional_history_all(n_days=n_days + 5)

    # ── 單日法人資料（今日買賣超顯示用）────────────────────
    inst_today = get_all_institutional_data()

    rows = []
    for ticker, df in stock_data.items():
        code = ticker.replace(".TW", "")

        inst_hist = inst_hist_map.get(code, pd.DataFrame())
        sig = get_short_term_signal(df, n_days=n_days, inst_hist=inst_hist)

        today_inst = inst_today.get(code, {})
        rows.append({
            "代號":          code,
            "名稱":          name_map.get(code, code),
            "訊號":          sig["signal"],
            "評分":          sig["score"],
            "收盤價":        sig.get("close"),
            f"{n_days}日漲跌(%)": sig.get("return_pct"),
            "MA5":           sig.get("ma5"),
            "K值":           sig.get("k_val"),
            "原因":          "、".join(sig["reasons"]),
            "_ticker":       ticker,
            "_sector":       get_sector_from_code(code),
            "三大法人今日(張)": today_inst.get("institutional_net", None),
            "外資今日(張)":   today_inst.get("foreign_net", None),
            "投信今日(張)":   today_inst.get("trust_net", None),
            "自營商今日(張)": today_inst.get("dealer_net", None),
        })

    df_result = pd.DataFrame(rows)
    if df_result.empty:
        return df_result, "掃描結果為空"

    df_result = df_result.sort_values("評分", ascending=False).reset_index(drop=True)
    status = f"{msg}，近 {n_days} 交易日強弱分析，共 {len(df_result)} 支"
    return df_result, status


def run_etf_screener(period: str = "3mo") -> tuple[pd.DataFrame, str]:
    """
    整合前5大ETF成分股掃描
    回傳 (結果 DataFrame, 狀態訊息)
    """
    tickers, msg, name_map = get_etf_tickers()
    if not tickers:
        return pd.DataFrame(), "無法取得ETF成分股資料"

    stock_data = get_multiple_stocks(tickers, period=period)
    inst_all = get_all_institutional_data()

    rows = []
    for ticker, df in stock_data.items():
        code = ticker.replace(".TW", "")
        inst_data = inst_all.get(code, {})
        sig = get_signal(df, inst_data=inst_data)
        rows.append({
            "代號": code,
            "名稱": name_map.get(code, code),
            "訊號": sig["signal"],
            "評分": sig["score"],
            "收盤價": round(sig.get("close", 0), 2),
            "RSI": round(sig["rsi"], 1) if sig.get("rsi") else None,
            "MA5": round(sig.get("ma5", 0), 2) if sig.get("ma5") else None,
            "MA20": round(sig.get("ma20", 0), 2) if sig.get("ma20") else None,
            "原因": "、".join(sig["reasons"]),
            "_ticker": ticker,
            "_sector": get_sector_from_code(code),
            **_inst_row(inst_data),
        })

    df_result = pd.DataFrame(rows)
    if df_result.empty:
        return df_result, "掃描結果為空"

    df_result = df_result.sort_values("評分", ascending=False).reset_index(drop=True)
    return df_result, f"{msg}，成功分析 {len(df_result)} 支"
