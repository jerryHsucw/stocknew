"""
從台灣證交所公開 API 抓取全市場上市股票清單
並依成交量（成交股數）篩選出前 N 大
非交易日自動往前找最近一個交易日
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import urllib3

# 關閉 SSL 憑證警告（證交所憑證格式問題，抓公開資料無安全疑慮）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_twse_all_stocks() -> pd.DataFrame | None:
    """
    從證交所 API 抓取所有上市股票資料
    非交易日自動往前找最近 7 天內的最後一個交易日
    """
    # 往前最多找 7 天（跨越週末 + 假日）
    for days_back in range(0, 8):
        date = datetime.today() - timedelta(days=days_back)
        # 跳過週六(5)、週日(6)
        if date.weekday() >= 5:
            continue
        date_str = date.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json&date={date_str}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            resp.raise_for_status()
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("data"):
                continue
            fields = data.get("fields", [])
            rows = data.get("data", [])
            df = pd.DataFrame(rows, columns=fields)
            if days_back > 0:
                print(f"[INFO] 今日無資料，使用 {date_str} 的證交所資料（往回 {days_back} 天）")
            return df
        except Exception as e:
            print(f"[WARN] {date_str} 取得失敗: {e}")
            continue

    print("[ERROR] 找不到近期交易日資料")
    return None


def _is_common_stock(code: str) -> bool:
    """
    只保留一般個股，排除：
    - ETF：00 開頭（0050、00878、00929...）
    - 權證、特別股：含字母（2330A）
    - 非標準代號：非純數字
    保留：4位純數字且不以 00 開頭
    """
    if not code.isdigit():
        return False
    if len(code) != 4:
        return False
    if code.startswith("00"):
        return False
    return True


def get_top_stocks_by_volume(top_n: int = 150) -> list[dict]:
    """
    回傳成交量（成交股數）前 top_n 大的上市股票
    格式：[{"ticker": "2330.TW", "name": "台積電", "volume": 123456789}, ...]
    """
    df = fetch_twse_all_stocks()
    if df is None or df.empty:
        return []

    print(f"[INFO] 欄位列表：{df.columns.tolist()}")

    # 自動偵測欄位名稱（不同 API 版本欄位名稱可能略有不同）
    code_col = next((c for c in df.columns if "代號" in c or "代碼" in c), None)
    name_col = next((c for c in df.columns if "名稱" in c), None)
    volume_col = next((c for c in df.columns if "股數" in c), None)

    if not code_col or not name_col or not volume_col:
        print(f"[ERROR] 找不到對應欄位，現有欄位：{df.columns.tolist()}")
        return []

    # 清理資料
    df[code_col] = df[code_col].astype(str).str.strip()
    df[name_col] = df[name_col].astype(str).str.strip()

    # 只保留一般股票（4位數字）
    df = df[df[code_col].apply(_is_common_stock)].copy()

    # 轉換成交股數為數字（含逗號字串）
    df[volume_col] = (
        df[volume_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("--", "0", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )

    # 排序取前 N
    df = df.sort_values(volume_col, ascending=False).head(top_n)

    result = []
    for _, row in df.iterrows():
        code = row[code_col]
        result.append({
            "ticker": f"{code}.TW",
            "name": row[name_col],
            "volume": int(row[volume_col]),
        })

    return result


def get_sector_from_code(code: str) -> str:
    """
    依股票代號前綴粗略分類產業
    台灣股票代號慣例：
      1xxx = 水泥/食品/紡織/化工/鋼鐵
      2xxx = 電機/電子/金融
      3xxx = 電子
      4xxx = 生技醫療
      5xxx = 航運
      6xxx = 半導體/電子零組件
      8xxx = 其他電子
      9xxx = 其他/通路
    """
    if not code:
        return "其他"
    prefix = code[:2]
    mapping = {
        "11": "水泥", "12": "食品", "13": "紡織", "14": "化工",
        "15": "化工", "16": "玻璃", "17": "造紙", "18": "鋼鐵",
        "19": "橡膠", "20": "汽車",
        "21": "電機", "22": "電線電纜",
        "23": "半導體", "24": "半導體", "25": "電腦周邊",
        "26": "其他電子", "27": "通訊",
        "28": "金融", "29": "金融",
        "30": "電子", "31": "電子",
        "32": "電子", "33": "電子",
        "40": "生技", "41": "生技", "47": "生技",
        "57": "航運", "58": "航運",
        "60": "半導體", "61": "電子零組件",
        "62": "電子零組件", "63": "電子", "64": "電子",
        "65": "電子", "66": "電子",
        "80": "電子", "81": "電子",
        "91": "通路", "95": "觀光", "96": "其他",
    }
    return mapping.get(prefix, "其他")
