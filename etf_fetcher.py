"""
抓取台灣前5大ETF成分股，合併去重後作為掃描標的
來源：玩股網 (wantgoo.com)
支援本機與雲端（非台灣IP皆可存取）
"""
import requests
from bs4 import BeautifulSoup
import time

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 前5大ETF
TOP_ETFs = {
    "0050": "元大台灣50",
    "0056": "元大高股息",
    "00878": "國泰永續高股息",
    "00929": "復華台灣科技優息",
    "00940": "元大台灣價值高息",
}

# ── 備用清單（網路抓取失敗時使用）─────────────────────────
# 整合5檔ETF的主要已知成分股（約120支）
FALLBACK_STOCKS = {
    # 0050 台灣50
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科",
    "2882": "富邦金", "2881": "國泰金", "2308": "台達電",
    "3008": "大立光", "3711": "日月光投控", "2303": "聯電",
    "2412": "中華電", "2357": "華碩", "2382": "廣達",
    "2886": "兆豐金", "2884": "玉山金", "2891": "中信金",
    "1301": "台塑", "1303": "南亞", "1326": "台化",
    "2207": "和泰車", "3045": "台灣大", "4904": "遠傳",
    "2912": "統一超", "1216": "統一", "2395": "研華",
    "2379": "瑞昱", "2327": "國巨", "4938": "和碩",
    "3034": "聯詠", "2408": "南亞科", "2301": "光寶科",
    "2344": "華邦電", "2353": "宏碁", "3231": "緯創",
    "2615": "萬海", "2609": "陽明", "2603": "長榮",
    "6505": "台塑化", "5880": "合庫金", "2890": "永豐金",
    "2883": "開發金", "2880": "華南金", "2885": "元大金",
    "2892": "第一金", "2002": "中鋼", "5871": "中租控股",
    "2354": "鴻準", "2376": "技嘉", "3017": "奇鋐",
    "6669": "緯穎", "2049": "上銀", "1590": "亞德客",
    # 0056 高股息額外成分
    "2006": "東和鋼鐵", "9910": "豐泰", "8046": "南電",
    "6415": "矽力-KY", "3703": "欣奇", "2404": "漢唐",
    "1537": "廣隆", "6271": "同欣電", "3189": "景碩",
    "2368": "金像電", "2059": "川湖", "1264": "德麥",
    # 00878 國泰永續高股息額外成分
    "2454": "聯發科", "3037": "欣興", "2345": "智邦",
    "3044": "健鼎", "4919": "新唐", "6770": "力積電",
    "2337": "旺宏", "3081": "聯亞", "2358": "廷鑫",
    "6214": "精誠", "3711": "日月光投控", "2385": "群光",
    # 00929 復華科技優息額外成分
    "2356": "英業達", "3673": "TPK", "2360": "致茂",
    "2383": "台光電", "3052": "夆典", "6472": "保瑞",
    "3661": "世芯-KY", "6488": "環球晶", "3533": "嘉澤",
    # 00940 元大價值高息額外成分
    "1101": "台泥", "1102": "亞泥", "1402": "遠東新",
    "2542": "興富發", "5269": "祥碩", "6176": "瑞儀",
    "2474": "可成", "3711": "日月光投控", "2337": "旺宏",
}


def fetch_etf_constituents(etf_code: str) -> dict[str, str]:
    """
    抓取單一ETF成分股
    回傳 {股票代號: 股票名稱}
    """
    url = f"https://www.wantgoo.com/stock/etf/{etf_code}/constituent"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        stocks = {}
        # 找所有股票連結（格式：/stock/2330/...）
        for a in soup.find_all("a", href=True):
            href = a["href"]
            parts = href.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "stock":
                code = parts[1]
                if code.isdigit() and len(code) == 4:
                    name = a.get_text(strip=True)
                    if name and not name.isdigit():
                        stocks[code] = name

        return stocks
    except Exception as e:
        print(f"[WARN] 抓取 {etf_code} 成分股失敗: {e}")
        return {}


def get_all_etf_stocks() -> tuple[dict[str, str], str]:
    """
    抓取所有5檔ETF成分股，合併去重
    回傳 ({代號: 名稱}, 狀態訊息)
    """
    all_stocks = {}
    success_etfs = []

    for etf_code, etf_name in TOP_ETFs.items():
        stocks = fetch_etf_constituents(etf_code)
        if stocks:
            new_count = len([k for k in stocks if k not in all_stocks])
            all_stocks.update(stocks)
            success_etfs.append(f"{etf_name}({len(stocks)}支)")
            print(f"[INFO] {etf_name}: {len(stocks)} 支，新增 {new_count} 支")
        time.sleep(0.5)  # 避免太快被擋

    if all_stocks:
        msg = f"已整合 {', '.join(success_etfs)}，共 {len(all_stocks)} 支不重複個股"
        return all_stocks, msg
    else:
        # 使用備用清單
        print("[INFO] 使用備用清單")
        msg = f"使用備用清單，共 {len(FALLBACK_STOCKS)} 支"
        return FALLBACK_STOCKS, msg


def get_etf_tickers() -> tuple[list[str], str]:
    """
    回傳 yfinance 格式的 ticker 清單
    ([" 2330.TW", ...], 狀態訊息)
    """
    stocks, msg = get_all_etf_stocks()
    tickers = [f"{code}.TW" for code in stocks.keys()]
    return tickers, msg, stocks
