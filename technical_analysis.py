"""
技術分析模組
計算 RSI、MACD、布林帶、均線等指標，並產生買賣訊號
"""
import pandas as pd
import numpy as np


# ── 指標計算 ──────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    return upper, ma, lower


def calc_ma(close: pd.Series, periods: list[int] = [5, 10, 20, 60]) -> dict[str, pd.Series]:
    return {f"MA{p}": close.rolling(p).mean() for p in periods}


def calc_kd(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 9) -> tuple[pd.Series, pd.Series]:
    """
    計算 KD 隨機指標（台灣慣用 9 日參數）
    RSV = (收盤 - N日最低) / (N日最高 - N日最低) × 100
    K   = 前K × 2/3 + RSV × 1/3   （初始值 50）
    D   = 前D × 2/3 + K  × 1/3   （初始值 50）
    """
    lowest  = low.rolling(period).min()
    highest = high.rolling(period).max()
    denom   = (highest - lowest).replace(0, float("nan"))
    rsv     = ((close - lowest) / denom * 100).fillna(50)

    k_vals, d_vals = [50.0], [50.0]
    for r in rsv.iloc[1:]:
        k = k_vals[-1] * 2 / 3 + float(r) / 3
        d = d_vals[-1] * 2 / 3 + k / 3
        k_vals.append(k)
        d_vals.append(d)

    return (
        pd.Series(k_vals, index=rsv.index, name="K"),
        pd.Series(d_vals, index=rsv.index, name="D"),
    )


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在 DataFrame 上附加所有技術指標欄位"""
    df = df.copy()
    close = df["Close"]

    df["RSI"] = calc_rsi(close)

    macd, signal, hist = calc_macd(close)
    df["MACD"] = macd
    df["MACD_Signal"] = signal
    df["MACD_Hist"] = hist

    df["BB_Upper"], df["BB_Mid"], df["BB_Lower"] = calc_bollinger(close)

    for name, series in calc_ma(close).items():
        df[name] = series

    df["K"], df["D"] = calc_kd(df["High"], df["Low"], close)

    # 量比（今日成交量 / 5日均量）
    df["Vol_Ratio"] = df["Volume"] / df["Volume"].rolling(5).mean()

    return df


# ── 訊號判斷 ──────────────────────────────────────────────

def get_signal(df: pd.DataFrame, inst_data: dict | None = None) -> dict:
    """
    分析最新一筆資料，回傳訊號字典：
    signal: "被錯殺" | "考慮買進" | "注意退場" | "觀望"
    reasons: list[str]
    score: int  （技術面 + 法人面加總）
    inst_data: 由 institutional_fetcher.get_all_institutional_data() 取得的個股字典
    """
    if df is None or len(df) < 30:
        return {"signal": "資料不足", "reasons": [], "score": 0}

    df = add_all_indicators(df)
    row = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    reasons = []

    rsi = row.get("RSI")
    macd = row.get("MACD")
    macd_sig = row.get("MACD_Signal")
    prev_macd = prev.get("MACD")
    prev_macd_sig = prev.get("MACD_Signal")
    close = row["Close"]
    bb_lower = row.get("BB_Lower")
    bb_upper = row.get("BB_Upper")
    ma5 = row.get("MA5")
    ma20 = row.get("MA20")
    prev_ma5 = prev.get("MA5")
    prev_ma20 = prev.get("MA20")
    vol_ratio = row.get("Vol_Ratio", 1)

    # RSI 判斷
    if rsi is not None:
        if rsi < 30:
            score += 30
            reasons.append(f"RSI={rsi:.1f}（超賣區 <30）")
        elif rsi < 40:
            score += 15
            reasons.append(f"RSI={rsi:.1f}（偏低）")
        elif rsi > 70:
            score -= 30
            reasons.append(f"RSI={rsi:.1f}（超買區 >70）")
        elif rsi > 60:
            score -= 10
            reasons.append(f"RSI={rsi:.1f}（偏高）")

    # MACD 黃金/死亡交叉
    if all(v is not None for v in [macd, macd_sig, prev_macd, prev_macd_sig]):
        if prev_macd < prev_macd_sig and macd > macd_sig:
            score += 25
            reasons.append("MACD 黃金交叉（看多訊號）")
        elif prev_macd > prev_macd_sig and macd < macd_sig:
            score -= 25
            reasons.append("MACD 死亡交叉（看空訊號）")
        elif macd > macd_sig:
            score += 10
            reasons.append("MACD 多頭排列")
        else:
            score -= 10
            reasons.append("MACD 空頭排列")

    # 布林帶
    if bb_lower is not None and close <= bb_lower:
        score += 20
        reasons.append("股價觸及布林帶下軌（超賣）")
    elif bb_upper is not None and close >= bb_upper:
        score -= 20
        reasons.append("股價觸及布林帶上軌（超買）")

    # 均線交叉
    if all(v is not None for v in [ma5, ma20, prev_ma5, prev_ma20]):
        if prev_ma5 < prev_ma20 and ma5 > ma20:
            score += 20
            reasons.append("MA5 向上穿越 MA20（黃金交叉）")
        elif prev_ma5 > prev_ma20 and ma5 < ma20:
            score -= 20
            reasons.append("MA5 向下穿越 MA20（死亡交叉）")

    # 量增價漲
    if vol_ratio > 1.5 and close > prev["Close"]:
        score += 15
        reasons.append(f"量增價漲（量比={vol_ratio:.1f}x）")
    elif vol_ratio > 1.5 and close < prev["Close"]:
        score -= 15
        reasons.append(f"量增價跌（量比={vol_ratio:.1f}x，賣壓大）")

    # 三大法人 / 融資融券 / 借券附加評分
    if inst_data:
        inst_score, inst_reasons = get_institutional_score(inst_data)
        score += inst_score
        reasons.extend(inst_reasons)

    # 決定訊號標籤
    if score >= 50:
        signal = "被錯殺"
    elif score >= 20:
        signal = "考慮買進"
    elif score <= -40:
        signal = "注意退場"
    elif score <= -15:
        signal = "偏空觀望"
    else:
        signal = "觀望"

    return {
        "signal": signal,
        "score": score,
        "reasons": reasons,
        "rsi": rsi,
        "close": close,
        "ma5": ma5,
        "ma20": ma20,
    }


def get_institutional_score(inst_data: dict) -> tuple[int, list[str]]:
    """
    依三大法人、融資融券、借券計算附加評分。
    inst_data 各欄位單位皆為「張」。

    評分邏輯：
    - 三大法人淨買超 ≥ 1000 張 → +20；≥ 100 張 → +10
    - 三大法人淨賣超 ≥ 1000 張 → −20；≥ 100 張 → −10
    - 融券餘額 ≥ 500 張 → −10（空頭壓力）
    - 借券賣出 ≥ 500 張 → −20；≥ 100 張 → −10（機構做空）
    - 借券餘額 ≥ 1000 張 → −10（做空部位大）
    """
    score = 0
    reasons = []

    # 三大法人淨買超
    inst_net = inst_data.get("institutional_net")
    if inst_net is not None:
        if inst_net >= 1000:
            score += 20
            reasons.append(f"三大法人大量買超 {inst_net:,} 張")
        elif inst_net >= 100:
            score += 10
            reasons.append(f"三大法人買超 {inst_net:,} 張")
        elif inst_net <= -1000:
            score -= 20
            reasons.append(f"三大法人大量賣超 {abs(inst_net):,} 張")
        elif inst_net <= -100:
            score -= 10
            reasons.append(f"三大法人賣超 {abs(inst_net):,} 張")

    # 融券餘額（空頭壓力）
    short_bal = inst_data.get("short_balance")
    if short_bal is not None and short_bal >= 500:
        score -= 10
        reasons.append(f"融券餘額 {short_bal:,} 張（空頭壓力）")

    # 借券賣出（機構做空）
    lending_sell = inst_data.get("lending_sell")
    if lending_sell is not None:
        if lending_sell >= 500:
            score -= 20
            reasons.append(f"借券賣出 {lending_sell:,} 張（機構大量做空）")
        elif lending_sell >= 100:
            score -= 10
            reasons.append(f"借券賣出 {lending_sell:,} 張")

    # 借券餘額（做空部位）
    lending_bal = inst_data.get("lending_balance")
    if lending_bal is not None and lending_bal >= 1000:
        score -= 10
        reasons.append(f"借券餘額 {lending_bal:,} 張（做空部位大）")

    return score, reasons


def get_short_term_signal(df: pd.DataFrame, n_days: int = 5,
                          inst_hist: "pd.DataFrame | None" = None) -> dict:
    """
    短線強弱評分（適用 5/10/15/30 日視窗）。
    不依賴 RSI14 / MACD26 / 布林通道 20 等長期指標，
    改用動能、量能、MA5、KD、N日新高低、法人連續方向。

    分數對應：
      ≥  50 → 🔥 強勢多頭
      25~49 → 🟢 短期偏多
     -24~24 → ⚪ 盤整觀望
    -25~-49 → 🟠 短期偏空
      ≤ -50 → 🔴 弱勢空頭
    """
    min_rows = max(n_days + 5, 15)          # 至少需要的資料列數
    if df is None or len(df) < min_rows:
        return {"signal": "資料不足", "reasons": [], "score": 0,
                "return_pct": None, "close": None, "ma5": None, "k_val": None}

    df = add_all_indicators(df)
    window = df.iloc[-n_days:]              # 分析視窗
    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    score   = 0
    reasons = []

    close     = float(latest["Close"])
    open_n    = float(window.iloc[0]["Open"])
    high_n    = float(window["High"].max())
    low_n     = float(window["Low"].min())
    ma5       = latest.get("MA5")
    prev_ma5  = prev.get("MA5")
    k_val     = latest.get("K")
    d_val     = latest.get("D")
    prev_k    = prev.get("K")
    prev_d    = prev.get("D")
    vol_ratio = latest.get("Vol_Ratio", 1.0)

    # ── 1. 動能：N 日累積漲跌幅 ──────────────────────────────
    ret_pct = (close - open_n) / open_n * 100 if open_n else 0
    if ret_pct >= 8:
        score += 30; reasons.append(f"{n_days}日漲幅 {ret_pct:.1f}%（強勢動能）")
    elif ret_pct >= 5:
        score += 20; reasons.append(f"{n_days}日漲幅 {ret_pct:.1f}%")
    elif ret_pct >= 3:
        score += 10; reasons.append(f"{n_days}日漲幅 {ret_pct:.1f}%")
    elif ret_pct <= -8:
        score -= 30; reasons.append(f"{n_days}日跌幅 {ret_pct:.1f}%（弱勢下跌）")
    elif ret_pct <= -5:
        score -= 20; reasons.append(f"{n_days}日跌幅 {ret_pct:.1f}%")
    elif ret_pct <= -3:
        score -= 10; reasons.append(f"{n_days}日跌幅 {ret_pct:.1f}%")

    # ── 2. 量能：量比 + 漲跌方向 ────────────────────────────
    price_up = close >= float(prev["Close"])
    if vol_ratio >= 1.5:
        if price_up:
            score += 25; reasons.append(f"放量上漲（量比 {vol_ratio:.1f}x）")
        else:
            score -= 25; reasons.append(f"放量下跌（量比 {vol_ratio:.1f}x，賣壓大）")
    elif vol_ratio < 0.7:
        if not price_up:
            score -= 10; reasons.append(f"縮量下跌（量比 {vol_ratio:.1f}x）")

    # ── 3. MA5 趨勢 ──────────────────────────────────────────
    if ma5 is not None and prev_ma5 is not None:
        ma5_rising = ma5 > prev_ma5
        if close > ma5:
            if ma5_rising:
                score += 20; reasons.append("收盤 > MA5 且 MA5 上升")
            else:
                score += 5;  reasons.append("收盤 > MA5（MA5 持平偏弱）")
        else:
            if not ma5_rising:
                score -= 20; reasons.append("收盤 < MA5 且 MA5 下降")
            else:
                score -= 5;  reasons.append("收盤 < MA5（MA5 仍上升）")

    # ── 4. N 日新高／新低突破 ───────────────────────────────
    if close >= high_n:
        score += 15; reasons.append(f"創 {n_days} 日新高")
    elif close <= low_n:
        score -= 15; reasons.append(f"創 {n_days} 日新低")
    elif close >= high_n * 0.97:
        score += 5;  reasons.append(f"接近 {n_days} 日高點（{close/high_n*100:.0f}%）")
    elif close <= low_n * 1.03:
        score -= 5;  reasons.append(f"接近 {n_days} 日低點（{close/low_n*100:.0f}%）")

    # ── 5. KD 位置 + 交叉 ───────────────────────────────────
    if k_val is not None:
        if k_val < 20:
            score += 15; reasons.append(f"K={k_val:.0f}（超賣區）")
        elif k_val > 80:
            score -= 10; reasons.append(f"K={k_val:.0f}（超買區）")
        if prev_k is not None and prev_d is not None and d_val is not None:
            if prev_k < prev_d and k_val > d_val:
                score += 15; reasons.append("KD 黃金交叉（近期）")
            elif prev_k > prev_d and k_val < d_val:
                score -= 15; reasons.append("KD 死亡交叉（近期）")

    # ── 6. 三大法人連續買賣超（需 inst_hist）───────────────
    if inst_hist is not None and not inst_hist.empty:
        recent = inst_hist.tail(n_days)
        net_series = recent.get("institutional_net", recent.get("foreign_net"))
        if net_series is not None:
            consecutive_buy  = 0
            consecutive_sell = 0
            for v in reversed(net_series.tolist()):
                if v > 0:
                    if consecutive_sell > 0: break
                    consecutive_buy += 1
                elif v < 0:
                    if consecutive_buy > 0: break
                    consecutive_sell += 1
                else:
                    break
            if consecutive_buy >= 3:
                score += 20; reasons.append(f"三大法人連續 {consecutive_buy} 日買超")
            elif consecutive_buy == 2:
                score += 10; reasons.append("三大法人連續 2 日買超")
            if consecutive_sell >= 3:
                score -= 20; reasons.append(f"三大法人連續 {consecutive_sell} 日賣超")
            elif consecutive_sell == 2:
                score -= 10; reasons.append("三大法人連續 2 日賣超")

    # ── 訊號標籤 ─────────────────────────────────────────────
    if score >= 50:
        signal = "強勢多頭"
    elif score >= 25:
        signal = "短期偏多"
    elif score <= -50:
        signal = "弱勢空頭"
    elif score <= -25:
        signal = "短期偏空"
    else:
        signal = "盤整觀望"

    return {
        "signal":     signal,
        "score":      score,
        "reasons":    reasons,
        "return_pct": round(ret_pct, 2),
        "close":      close,
        "ma5":        round(ma5, 2) if ma5 else None,
        "k_val":      round(k_val, 1) if k_val else None,
    }


def get_sector_strength(stock_signals: dict[str, dict], sector_map: dict[str, list[str]]) -> dict[str, float]:
    """計算各類股平均分數（類股輪動）"""
    sector_scores = {}
    for sector, tickers in sector_map.items():
        scores = [stock_signals[t]["score"] for t in tickers if t in stock_signals]
        sector_scores[sector] = round(sum(scores) / len(scores), 1) if scores else 0
    return sector_scores
