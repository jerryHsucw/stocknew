"""
三大法人、融資融券、借券資料擷取模組
資料來源：台灣證券交易所公開 API

注意：主力（分點）買賣資料無官方 API，需第三方來源，本模組不提供。
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── 日期工具 ──────────────────────────────────────────────────

def _get_recent_trading_date() -> str:
    """取得最近交易日（YYYYMMDD），跳過週末"""
    for days_back in range(0, 8):
        date = datetime.today() - timedelta(days=days_back)
        if date.weekday() >= 5:
            continue
        return date.strftime("%Y%m%d")
    return datetime.today().strftime("%Y%m%d")


def _get_weekday_dates(n: int) -> list[str]:
    """取得最近 n 個工作日日期字串（最新在前，跳過週末）"""
    dates = []
    d = datetime.today()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return dates


def _clean_num(val) -> int:
    """轉換含逗號或 '--' 的字串為整數"""
    try:
        return int(float(str(val).replace(",", "").replace("--", "0").strip()))
    except Exception:
        return 0


# ── 原始資料抓取 ──────────────────────────────────────────────

def fetch_institutional(date_str: str | None = None) -> pd.DataFrame | None:
    """
    抓取三大法人買賣超（T86），欄位單位：股（÷1000 = 張）
    """
    if date_str is None:
        date_str = _get_recent_trading_date()
    url = (
        f"https://www.twse.com.tw/fund/T86"
        f"?response=json&date={date_str}&selectType=ALLBUT0999"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return None
        return pd.DataFrame(data["data"], columns=data.get("fields", []))
    except Exception as e:
        print(f"[WARN] 三大法人 {date_str} 失敗: {e}")
        return None


def fetch_margin(date_str: str | None = None) -> pd.DataFrame | None:
    """
    抓取融資融券（MI_MARGN）。
    回應格式為 {"tables":[彙總表, 個股表, ...]}, 個股表欄位重名，
    本函式重新命名欄位後回傳個股 DataFrame。
    """
    if date_str is None:
        date_str = _get_recent_trading_date()
    url = (
        f"https://www.twse.com.tw/exchangeReport/MI_MARGN"
        f"?response=json&date={date_str}&selectType=ALL"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK":
            return None
        # 回應格式：{"tables": [summary_table, per_stock_table, ...]}
        for table in data.get("tables", []):
            fields = table.get("fields", [])
            rows   = table.get("data", [])
            if not rows or "代號" not in fields:
                continue
            # 欄位順序固定：代號, 名稱, [融資×6], [融券×6], 資券互抵, 註記
            named = [
                "代號", "名稱",
                "融資買進", "融資賣出", "融資現金償還", "融資前日餘額", "融資餘額", "融資限額",
                "融券買進", "融券賣出", "融券券償還", "融券前日餘額", "融券餘額", "融券限額",
                "資券互抵", "註記",
            ]
            cols = named[: len(fields)]
            return pd.DataFrame(rows, columns=cols)
        return None
    except Exception as e:
        print(f"[WARN] 融資融券 {date_str} 失敗: {e}")
        return None


def fetch_lending(date_str: str | None = None) -> pd.DataFrame | None:
    """抓取借券賣出餘額（TWT93U），欄位單位：股（÷1000 = 張）"""
    if date_str is None:
        date_str = _get_recent_trading_date()
    url = (
        f"https://www.twse.com.tw/exchangeReport/TWT93U"
        f"?response=json&date={date_str}"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return None
        return pd.DataFrame(data["data"], columns=data.get("fields", []))
    except Exception as e:
        print(f"[WARN] 借券 {date_str} 失敗: {e}")
        return None


# ── 單日個股解析（供歷史批次使用） ────────────────────────────

def _parse_t86_for_stock(df: pd.DataFrame, code: str) -> dict | None:
    """從 T86 DataFrame 提取特定股票資料（單位：張）"""
    code_col = next((c for c in df.columns if "代號" in c or c == "代號"), None)
    if not code_col:
        return None
    mask = df[code_col].astype(str).str.strip() == code
    if not mask.any():
        return None
    row = df[mask].iloc[0]

    foreign_col        = next((c for c in df.columns if "外陸資" in c and "買賣超" in c and "外資自營商" not in c), None)
    foreign_dealer_col = next((c for c in df.columns if "外資自營商" in c and "買賣超" in c), None)
    trust_col          = next((c for c in df.columns if "投信" in c and "買賣超" in c), None)
    dealer_total_col   = next((c for c in df.columns if c.strip() == "自營商買賣超股數"), None)
    dealer_self_col    = next((c for c in df.columns if "自營商" in c and "買賣超" in c and "自行買賣" in c and "外資" not in c), None)
    dealer_hedge_col   = next((c for c in df.columns if "自營商" in c and "買賣超" in c and "避險" in c), None)
    total_col          = next((c for c in df.columns if "三大法人" in c and "買賣超" in c), None)

    foreign_net = (
        (_clean_num(row[foreign_col])        if foreign_col        else 0) +
        (_clean_num(row[foreign_dealer_col]) if foreign_dealer_col else 0)
    )
    if dealer_total_col:
        dealer_net = _clean_num(row[dealer_total_col])
    else:
        dealer_net = (
            (_clean_num(row[dealer_self_col])  if dealer_self_col  else 0) +
            (_clean_num(row[dealer_hedge_col]) if dealer_hedge_col else 0)
        )
    return {
        "foreign_net":        foreign_net // 1000,
        "trust_net":          (_clean_num(row[trust_col]) // 1000) if trust_col else 0,
        "dealer_net":         dealer_net // 1000,
        "institutional_net":  (_clean_num(row[total_col]) // 1000) if total_col else 0,
    }


def _parse_margin_for_stock(df: pd.DataFrame, code: str) -> dict | None:
    """從已重命名欄位的 MI_MARGN DataFrame 提取特定股票資料（單位：張）"""
    if "代號" not in df.columns:
        return None
    mask = df["代號"].astype(str).str.strip() == code
    if not mask.any():
        return None
    row = df[mask].iloc[0]
    return {
        "margin_buy":     _clean_num(row.get("融資買進", 0)),
        "margin_sell":    _clean_num(row.get("融資賣出", 0)),
        "margin_balance": _clean_num(row.get("融資餘額", 0)),
        "short_sell":     _clean_num(row.get("融券賣出", 0)),
        "short_buy":      _clean_num(row.get("融券買進", 0)),
        "short_balance":  _clean_num(row.get("融券餘額", 0)),
    }


# ── 歷史多日批次（平行抓取） ──────────────────────────────────

def fetch_institutional_history(code: str, n_days: int = 30) -> pd.DataFrame:
    """
    取得特定股票近 n_days 個交易日的三大法人資料。
    以最多 3 條執行緒平行抓取，避免對 TWSE 造成過大請求壓力。
    回傳 DataFrame（index=日期，欄位：foreign_net, trust_net, dealer_net, institutional_net）
    """
    date_list = _get_weekday_dates(n_days + 15)

    def fetch_one(date_str):
        df = fetch_institutional(date_str)
        if df is None or df.empty:
            return date_str, None
        return date_str, _parse_t86_for_stock(df, code)

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, d): d for d in date_list}
        for future in as_completed(futures):
            date_str, data = future.result()
            if data is not None:
                results[date_str] = data

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame.from_dict(results, orient="index")
    df_out.index = pd.to_datetime(df_out.index, format="%Y%m%d")
    return df_out.sort_index().tail(n_days)


def fetch_margin_history(code: str, n_days: int = 30) -> pd.DataFrame:
    """
    取得特定股票近 n_days 個交易日的融資融券資料。
    回傳 DataFrame（index=日期，欄位：margin_buy/sell/balance, short_sell/buy/balance）
    """
    date_list = _get_weekday_dates(n_days + 15)

    def fetch_one(date_str):
        df = fetch_margin(date_str)
        if df is None or df.empty:
            return date_str, None
        return date_str, _parse_margin_for_stock(df, code)

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, d): d for d in date_list}
        for future in as_completed(futures):
            date_str, data = future.result()
            if data is not None:
                results[date_str] = data

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame.from_dict(results, orient="index")
    df_out.index = pd.to_datetime(df_out.index, format="%Y%m%d")
    return df_out.sort_index().tail(n_days)


# ── 批次：所有股票多日歷史（供近期強弱掃描使用） ─────────

def _parse_t86_all_stocks(df: pd.DataFrame) -> dict[str, dict]:
    """
    一次解析整張 T86 DataFrame，回傳所有 4 位數股票代號的當日法人資料。
    比對各股逐一呼叫效率高出數十倍。
    """
    code_col = next((c for c in df.columns if "代號" in c or "代碼" in c), None)
    if not code_col:
        return {}

    foreign_col        = next((c for c in df.columns if "外陸資" in c and "買賣超" in c and "外資自營商" not in c), None)
    foreign_dealer_col = next((c for c in df.columns if "外資自營商" in c and "買賣超" in c), None)
    trust_col          = next((c for c in df.columns if "投信" in c and "買賣超" in c), None)
    dealer_total_col   = next((c for c in df.columns if c.strip() == "自營商買賣超股數"), None)
    dealer_self_col    = next((c for c in df.columns if "自營商" in c and "買賣超" in c and "自行買賣" in c and "外資" not in c), None)
    dealer_hedge_col   = next((c for c in df.columns if "自營商" in c and "買賣超" in c and "避險" in c), None)
    total_col          = next((c for c in df.columns if "三大法人" in c and "買賣超" in c), None)

    result = {}
    for _, row in df.iterrows():
        code = str(row[code_col]).strip()
        if not code.isdigit() or len(code) != 4:
            continue
        foreign_net = (
            (_clean_num(row[foreign_col])        if foreign_col        else 0) +
            (_clean_num(row[foreign_dealer_col]) if foreign_dealer_col else 0)
        )
        dealer_net = (
            _clean_num(row[dealer_total_col]) if dealer_total_col else
            ((_clean_num(row[dealer_self_col])  if dealer_self_col  else 0) +
             (_clean_num(row[dealer_hedge_col]) if dealer_hedge_col else 0))
        )
        result[code] = {
            "foreign_net":       round(foreign_net / 1000),
            "trust_net":         round(_clean_num(row[trust_col]) / 1000) if trust_col else 0,
            "dealer_net":        round(dealer_net / 1000),
            "institutional_net": round(_clean_num(row[total_col]) / 1000) if total_col else 0,
        }
    return result


def fetch_institutional_history_all(n_days: int = 10) -> dict[str, pd.DataFrame]:
    """
    批次抓取所有股票近 n_days 個交易日的三大法人歷史。
    每個日期只呼叫一次 T86 API（共 n_days 次），
    遠比逐股呼叫（n_stocks × n_days 次）有效率。
    回傳 {code: DataFrame(index=日期, columns=[foreign_net, trust_net, dealer_net, institutional_net])}
    """
    date_list = _get_weekday_dates(n_days + 10)

    def fetch_one(date_str):
        df = fetch_institutional(date_str)
        if df is None or df.empty:
            return date_str, {}
        return date_str, _parse_t86_all_stocks(df)

    date_results: dict[str, dict[str, dict]] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, d): d for d in date_list}
        for future in as_completed(futures):
            date_str, parsed = future.result()
            if parsed:
                date_results[date_str] = parsed

    if not date_results:
        return {}

    # 收集所有出現的股票代號，建立 per-stock DataFrame
    all_codes: set[str] = set()
    for parsed in date_results.values():
        all_codes.update(parsed.keys())

    result: dict[str, pd.DataFrame] = {}
    for code in all_codes:
        daily = {
            d: data[code]
            for d, data in date_results.items()
            if code in data
        }
        if not daily:
            continue
        df_out = pd.DataFrame.from_dict(daily, orient="index")
        df_out.index = pd.to_datetime(df_out.index, format="%Y%m%d")
        result[code] = df_out.sort_index().tail(n_days)

    print(f"[INFO] 批次法人歷史完成：{len(date_results)} 個交易日，{len(result)} 支股票")
    return result


# ── 單日全市場整合（供掃描模式使用） ─────────────────────────

def get_all_institutional_data() -> dict[str, dict]:
    """
    整合三大法人、融資融券、借券，回傳各股資料字典。
    {
      "2330": {
        "institutional_net", "foreign_net", "trust_net", "dealer_net",  # 單位：張
        "margin_balance", "short_balance",                               # 單位：張
        "lending_balance", "lending_sell",                               # 單位：張
      }
    }
    """
    date_str = _get_recent_trading_date()
    result: dict[str, dict] = {}

    def ensure(code: str):
        if code not in result:
            result[code] = {}

    # ── 三大法人（T86） ────────────────────────────────────
    df_inst = fetch_institutional(date_str)
    if df_inst is not None and not df_inst.empty:
        print(f"[INFO] 三大法人欄位: {df_inst.columns.tolist()}")
        code_col = next((c for c in df_inst.columns if "代號" in c or "代碼" in c), None)

        foreign_col        = next((c for c in df_inst.columns if "外陸資" in c and "買賣超" in c and "外資自營商" not in c), None)
        foreign_dealer_col = next((c for c in df_inst.columns if "外資自營商" in c and "買賣超" in c), None)
        trust_col          = next((c for c in df_inst.columns if "投信" in c and "買賣超" in c), None)
        dealer_total_col   = next((c for c in df_inst.columns if c.strip() == "自營商買賣超股數"), None)
        dealer_self_col    = next((c for c in df_inst.columns if "自營商" in c and "買賣超" in c and "自行買賣" in c and "外資" not in c), None)
        dealer_hedge_col   = next((c for c in df_inst.columns if "自營商" in c and "買賣超" in c and "避險" in c), None)
        total_col          = next((c for c in df_inst.columns if "三大法人" in c and "買賣超" in c), None)

        if code_col:
            for _, row in df_inst.iterrows():
                code = str(row[code_col]).strip()
                if not code.isdigit() or len(code) != 4:
                    continue
                ensure(code)
                foreign_net = (
                    (_clean_num(row[foreign_col])        if foreign_col        else 0) +
                    (_clean_num(row[foreign_dealer_col]) if foreign_dealer_col else 0)
                )
                result[code]["foreign_net"] = foreign_net // 1000
                if trust_col:
                    result[code]["trust_net"] = _clean_num(row[trust_col]) // 1000
                if dealer_total_col:
                    dealer_net = _clean_num(row[dealer_total_col])
                else:
                    dealer_net = (
                        (_clean_num(row[dealer_self_col])  if dealer_self_col  else 0) +
                        (_clean_num(row[dealer_hedge_col]) if dealer_hedge_col else 0)
                    )
                result[code]["dealer_net"] = dealer_net // 1000
                if total_col:
                    result[code]["institutional_net"] = _clean_num(row[total_col]) // 1000

    # ── 融資融券（MI_MARGN） ───────────────────────────────
    df_margin = fetch_margin(date_str)
    if df_margin is not None and not df_margin.empty:
        print(f"[INFO] 融資融券欄位: {df_margin.columns.tolist()}")
        code_col = "代號" if "代號" in df_margin.columns else None
        if code_col:
            for _, row in df_margin.iterrows():
                code = str(row[code_col]).strip()
                if not code.isdigit() or len(code) != 4:
                    continue
                ensure(code)
                result[code]["margin_balance"] = _clean_num(row.get("融資餘額", 0))
                result[code]["short_balance"]  = _clean_num(row.get("融券餘額", 0))

    # ── 借券（TWT93U） ─────────────────────────────────────
    df_lending = fetch_lending(date_str)
    if df_lending is not None and not df_lending.empty:
        cols = df_lending.columns.tolist()
        print(f"[INFO] 借券欄位: {cols}")
        code_col         = next((c for c in cols if "代號" in c or c == "代號"), None)
        lending_bal_col  = next((c for c in cols if c.strip() == "今日餘額"), None)
        lending_sell_col = next((c for c in cols if c.strip() == "當日賣出"), None)

        if code_col:
            for _, row in df_lending.iterrows():
                code = str(row[code_col]).strip()
                if not code.isdigit() or len(code) != 4:
                    continue
                ensure(code)
                if lending_bal_col:
                    result[code]["lending_balance"] = _clean_num(row[lending_bal_col]) // 1000
                if lending_sell_col:
                    result[code]["lending_sell"] = _clean_num(row[lending_sell_col]) // 1000

    print(f"[INFO] 法人資料整合完成，共 {len(result)} 筆")
    return result
