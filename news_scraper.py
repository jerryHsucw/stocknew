"""
台股新聞蒐集模組
來源：
  1. 鉅亨網 RSS（anue.com.tw）
  2. Yahoo 台灣財經 RSS
  3. 經濟日報 RSS
"""
import requests
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# RSS 新聞來源
RSS_SOURCES = {
    "鉅亨網-台股": "https://feeds.feedburner.com/anue/stock",
    "鉅亨網-總覽": "https://feeds.feedburner.com/anue/news",
    "Yahoo財經": "https://tw.stock.yahoo.com/rss",
    "經濟日報": "https://money.udn.com/rssfeed/news/1/5649?ch=money",
    "工商時報": "https://ctee.com.tw/feed",
}


def fetch_rss(url: str, source_name: str, max_items: int = 10) -> list[dict]:
    """從 RSS feed 抓取新聞"""
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            pub_date = ""
            if hasattr(entry, "published"):
                pub_date = entry.published
            elif hasattr(entry, "updated"):
                pub_date = entry.updated

            items.append({
                "來源": source_name,
                "標題": entry.get("title", "").strip(),
                "摘要": _clean_summary(entry.get("summary", "")),
                "連結": entry.get("link", ""),
                "時間": pub_date,
            })
        return items
    except Exception as e:
        print(f"[RSS ERROR] {source_name}: {e}")
        return []


def _clean_summary(html_text: str) -> str:
    """去除 HTML 標籤，保留純文字摘要"""
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        text = soup.get_text(separator=" ").strip()
        return text[:200] + "…" if len(text) > 200 else text
    except Exception:
        return html_text[:200] if html_text else ""


def get_all_news(max_per_source: int = 8) -> list[dict]:
    """從所有來源抓取新聞，合併去重後回傳"""
    all_news = []
    for source, url in RSS_SOURCES.items():
        news = fetch_rss(url, source, max_per_source)
        all_news.extend(news)

    # 依標題去重
    seen = set()
    unique_news = []
    for item in all_news:
        title = item["標題"]
        if title and title not in seen:
            seen.add(title)
            unique_news.append(item)

    return unique_news


def search_news_by_keyword(news_list: list[dict], keyword: str) -> list[dict]:
    """
    從新聞清單中搜尋關鍵字（股票名稱或代號）
    keyword: 例如 "台積電" 或 "2330"
    """
    keyword = keyword.strip()
    return [
        item for item in news_list
        if keyword in item["標題"] or keyword in item["摘要"]
    ]


def get_stock_related_news(news_list: list[dict], ticker: str, name: str) -> list[dict]:
    """
    取得與特定股票相關的新聞
    ticker: "2330.TW"  →  搜尋 "2330"
    name: "台積電"
    """
    code = ticker.replace(".TW", "")
    matches = []
    for item in news_list:
        text = item["標題"] + item["摘要"]
        if code in text or name in text:
            matches.append(item)
    return matches


def format_news_for_display(news_list: list[dict]) -> str:
    """格式化新聞為純文字（備用）"""
    lines = []
    for i, item in enumerate(news_list, 1):
        lines.append(f"{i}. [{item['來源']}] {item['標題']}")
        if item["摘要"]:
            lines.append(f"   {item['摘要']}")
        lines.append(f"   {item['時間']}  {item['連結']}")
        lines.append("")
    return "\n".join(lines)
