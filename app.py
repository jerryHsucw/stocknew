"""
台股分析 Dashboard
執行方式：streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io

from data_fetcher import (
    get_stock_data, DEFAULT_STOCKS, STOCK_NAMES,
    get_display_name, get_stock_info
)
from technical_analysis import add_all_indicators, get_signal
from screener import run_screener, run_market_screener, run_etf_screener, get_sector_summary, get_top_picks, get_exit_candidates, run_short_term_screener
from news_scraper import get_all_news, get_stock_related_news, search_news_by_keyword
from institutional_fetcher import (
    get_all_institutional_data,
    fetch_institutional_history,
    fetch_margin_history,
)

# ── 頁面設定 ──────────────────────────────────────────────
st.set_page_config(
    page_title="台股分析儀表板",
    page_icon="📈",
    layout="wide",
)

st.title("📈 台股分析儀表板")
st.caption("資料來源：Yahoo Finance｜新聞：鉅亨網、Yahoo財經、經濟日報")

# ── 側邊欄 ────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")
    mode = st.radio("功能模式", ["📋 全市場掃描", "📅 近期強弱掃描", "🔍 個股查詢", "📊 各股技術分析"])
    st.divider()
    st.caption("© 台股分析工具")


# ═══════════════════════════════════════════════════════════
# 模式一：全市場掃描
# ═══════════════════════════════════════════════════════════
if mode == "📋 全市場掃描":

    # 偵測是否在 Streamlit Cloud 上執行
    import socket
    try:
        is_cloud = "streamlit" in socket.gethostname().lower() or \
                   st.context.headers.get("host", "").endswith("streamlit.app")
    except Exception:
        is_cloud = False

    col_mode, col_n, col_period = st.columns([2, 1, 1])
    with col_mode:
        if is_cloud:
            scan_mode = st.radio(
                "掃描範圍",
                ["📌 精選清單（25支，快速）", "📊 前5大ETF成分股（約120支）"],
                horizontal=True,
            )
        else:
            scan_mode = st.radio(
                "掃描範圍",
                ["📌 精選清單（25支，快速）", "📊 前5大ETF成分股（約120支）", "🌐 全市場前N大（依成交量）"],
                horizontal=True,
            )
    with col_n:
        top_n = st.number_input(
            "前N大",
            min_value=50, max_value=300, value=150, step=50,
            disabled=(scan_mode != "🌐 全市場前N大（依成交量）"),
            help="從全市場依今日成交金額取前N支（僅本機可用）"
        )
    with col_period:
        scan_period = st.select_slider(
            "資料區間",
            options=["1mo", "3mo", "6mo", "1y"],
            value="3mo",
            help="抓取多長的歷史資料來計算技術指標"
        )

    col_btn, col_tip = st.columns([1, 4])
    with col_btn:
        run_scan = st.button("🔄 開始掃描", type="primary", use_container_width=True)
    with col_tip:
        if scan_mode == "📌 精選清單（25支，快速）":
            st.info("掃描約需 30–60 秒")
        elif scan_mode == "📊 前5大ETF成分股（約120支）":
            st.info("整合 0050、0056、00878、00929、00940 成分股，約需 2–3 分鐘")
        else:
            st.warning(f"全市場前 {int(top_n)} 大，預計需要 2–5 分鐘，請耐心等候")

    if run_scan:
        if scan_mode == "📌 精選清單（25支，快速）":
            with st.spinner("正在掃描精選清單..."):
                df_all = run_screener(period=scan_period)
            status_msg = f"已掃描精選清單，共 {len(df_all)} 支"
        elif scan_mode == "📊 前5大ETF成分股（約120支）":
            with st.spinner("正在抓取ETF成分股並分析（約 2–3 分鐘）..."):
                df_all, status_msg = run_etf_screener(period=scan_period)
        else:
            with st.spinner(f"正在從證交所抓取全市場前 {int(top_n)} 大股票並分析（需 2–5 分鐘）..."):
                df_all, status_msg = run_market_screener(top_n=int(top_n), period=scan_period)

        if df_all.empty:
            st.error("無法取得資料，請確認網路連線")
            st.stop()

        st.session_state["scan_result"] = df_all
        st.session_state["scan_status"] = status_msg

    if st.session_state.get("scan_status"):
        st.caption(f"📊 {st.session_state['scan_status']}")

    df_all = st.session_state.get("scan_result")
    if df_all is None:
        st.info("點擊上方「開始掃描」按鈕，開始分析台股。")
        st.stop()

    # ── 摘要卡片 ──
    oversold   = len(df_all[df_all["訊號"] == "被錯殺"])
    buy_ready  = len(df_all[df_all["訊號"] == "考慮買進"])
    exit_cnt   = len(df_all[df_all["訊號"].isin(["注意退場", "偏空觀望"])])
    total      = len(df_all)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("掃描股票數", total)
    c2.metric("🟢 被錯殺 / 考慮買進", oversold + buy_ready)
    c3.metric("🔴 注意退場", exit_cnt)
    c4.metric("⚪ 觀望", total - oversold - buy_ready - exit_cnt)

    st.divider()

    # ── 類股強弱 ──
    st.subheader("🏭 類股強弱排行")
    sector_df = get_sector_summary(df_all)
    fig_sector = go.Figure(go.Bar(
        x=sector_df["類股"],
        y=sector_df["平均評分"],
        marker_color=["green" if v > 0 else "red" for v in sector_df["平均評分"]],
        text=sector_df["平均評分"],
        textposition="outside",
    ))
    fig_sector.update_layout(height=300, margin=dict(t=20, b=20))
    st.plotly_chart(fig_sector, use_container_width=True)

    st.divider()

    # ── 三欄：被錯殺 | 考慮買進 | 注意退場 ──
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("🟢 被錯殺")
        top = df_all[df_all["訊號"] == "被錯殺"][["代號", "名稱", "評分", "RSI", "原因"]]
        if top.empty:
            st.write("目前無符合條件")
        else:
            st.dataframe(top, hide_index=True, use_container_width=True)

    with col2:
        st.subheader("🔵 考慮買進")
        buy = df_all[df_all["訊號"] == "考慮買進"][["代號", "名稱", "評分", "RSI", "原因"]]
        if buy.empty:
            st.write("目前無符合條件")
        else:
            st.dataframe(buy, hide_index=True, use_container_width=True)

    with col3:
        st.subheader("🔴 注意退場")
        ext = df_all[df_all["訊號"].isin(["注意退場", "偏空觀望"])][["代號", "名稱", "評分", "RSI", "原因"]]
        if ext.empty:
            st.write("目前無符合條件")
        else:
            st.dataframe(ext, hide_index=True, use_container_width=True)

    st.divider()

    # ── 完整清單 ──
    with st.expander("📄 完整掃描清單（含法人資料）"):
        display_df = df_all.drop(columns=["_ticker", "_sector"], errors="ignore")
        st.dataframe(display_df, hide_index=True, use_container_width=True)

    # ── 法人資料總覽 ──
    inst_cols = ["代號", "名稱", "三大法人(張)", "外資(張)", "投信(張)", "自營商(張)",
                 "融資餘額(張)", "融券餘額(張)", "借券餘額(張)", "借券賣出(張)"]
    inst_available = [c for c in inst_cols if c in df_all.columns]
    if len(inst_available) > 2:
        with st.expander("🏦 三大法人 / 融資融券 / 借券總覽"):
            inst_df = df_all[inst_available].copy()
            # 三大法人排序（買超最多在前）
            if "三大法人(張)" in inst_df.columns:
                inst_df = inst_df.sort_values("三大法人(張)", ascending=False)
            st.dataframe(inst_df, hide_index=True, use_container_width=True)
            st.caption("正值＝買超；負值＝賣超。單位：張（1張＝1000股）。資料來源：TWSE 當日盤後。")

    st.divider()

    # ── 新聞區 ──
    st.subheader("📰 最新財經新聞")
    with st.spinner("載入新聞中..."):
        news_list = get_all_news(max_per_source=6)

    if news_list:
        news_keyword = st.text_input("🔍 新聞關鍵字篩選（股票名稱/代號）", placeholder="例：台積電、2330")
        if news_keyword:
            filtered_news = search_news_by_keyword(news_list, news_keyword)
        else:
            filtered_news = news_list

        if not filtered_news:
            st.warning(f"找不到包含「{news_keyword}」的新聞")
        else:
            for item in filtered_news[:20]:
                with st.container():
                    col_src, col_title = st.columns([1, 5])
                    with col_src:
                        st.caption(item["來源"])
                    with col_title:
                        st.markdown(f"**[{item['標題']}]({item['連結']})**")
                    if item["摘要"]:
                        st.caption(item["摘要"])
                    st.caption(item["時間"])
                    st.divider()
    else:
        st.warning("無法載入新聞，請確認網路連線")

    st.divider()

    # ── 指標計算公式說明 ──
    st.subheader("📐 指標計算公式說明")
    with st.expander("點擊展開 — RSI（相對強弱指標）"):
        st.markdown("""
**用途：** 衡量股價超買或超賣程度

**計算步驟：**
1. 計算每日漲跌幅
2. 取 14 日平均漲幅（Avg Gain）與平均跌幅（Avg Loss）
3. RS = Avg Gain ÷ Avg Loss
4. **RSI = 100 − (100 ÷ (1 + RS))**

**判讀：**
| RSI 值 | 意義 | 本系統訊號 |
|--------|------|-----------|
| < 30 | 超賣（可能被錯殺） | +30 分 |
| 30–40 | 偏低 | +15 分 |
| 60–70 | 偏高 | −10 分 |
| > 70 | 超買（注意退場） | −30 分 |
        """)

    with st.expander("點擊展開 — MACD（指數平滑移動平均）"):
        st.markdown("""
**用途：** 判斷趨勢方向與交叉訊號

**計算步驟：**
1. EMA12 = 12 日指數移動平均
2. EMA26 = 26 日指數移動平均
3. **MACD 線 = EMA12 − EMA26**
4. **Signal 線 = MACD 線的 9 日 EMA**
5. **柱狀圖（Histogram）= MACD 線 − Signal 線**

**判讀：**
| 情況 | 意義 | 本系統訊號 |
|------|------|-----------|
| MACD 由下往上穿越 Signal | 黃金交叉（看多） | +25 分 |
| MACD 由上往下穿越 Signal | 死亡交叉（看空） | −25 分 |
| MACD > Signal | 多頭排列 | +10 分 |
| MACD < Signal | 空頭排列 | −10 分 |
        """)

    with st.expander("點擊展開 — 布林帶（Bollinger Bands）"):
        st.markdown("""
**用途：** 判斷股價相對高低位置

**計算步驟：**
1. 中軌（MA20）= 20 日收盤價均線
2. 標準差 σ = 20 日收盤價標準差
3. **上軌 = MA20 + 2σ**
4. **下軌 = MA20 − 2σ**

**判讀：**
| 情況 | 意義 | 本系統訊號 |
|------|------|-----------|
| 股價 ≤ 下軌 | 超賣（可能反彈） | +20 分 |
| 股價 ≥ 上軌 | 超買（注意壓回） | −20 分 |
        """)

    with st.expander("點擊展開 — 均線交叉（MA5 / MA20）"):
        st.markdown("""
**用途：** 判斷短期趨勢方向

**計算：**
- **MA5** = 最近 5 個交易日收盤價平均
- **MA20** = 最近 20 個交易日收盤價平均

**判讀：**
| 情況 | 意義 | 本系統訊號 |
|------|------|-----------|
| MA5 向上穿越 MA20 | 黃金交叉（短線轉多） | +20 分 |
| MA5 向下穿越 MA20 | 死亡交叉（短線轉空） | −20 分 |
        """)

    with st.expander("點擊展開 — 量比與量價關係"):
        st.markdown("""
**用途：** 確認趨勢的可信度

**計算：**
- **量比 = 今日成交量 ÷ 5 日平均成交量**

**判讀：**
| 情況 | 意義 | 本系統訊號 |
|------|------|-----------|
| 量比 > 1.5 且價格上漲 | 量增價漲（強勢確認） | +15 分 |
| 量比 > 1.5 且價格下跌 | 量增價跌（賣壓沉重） | −15 分 |
        """)

    with st.expander("點擊展開 — 三大法人 / 融資融券 / 借券評分"):
        st.markdown("""
**用途：** 從籌碼面判斷機構動向，輔助技術訊號

**三大法人淨買超（單位：張）**
| 條件 | 本系統訊號 |
|------|-----------|
| 淨買超 ≥ 1,000 張 | +20 分（大量買進） |
| 淨買超 ≥ 100 張 | +10 分 |
| 淨賣超 ≥ 100 張 | −10 分 |
| 淨賣超 ≥ 1,000 張 | −20 分（大量賣出） |

**融券餘額**
| 條件 | 本系統訊號 |
|------|-----------|
| 融券餘額 ≥ 500 張 | −10 分（空頭壓力） |

**借券賣出（機構做空）**
| 條件 | 本系統訊號 |
|------|-----------|
| 借券賣出 ≥ 500 張 | −20 分（機構大量做空） |
| 借券賣出 ≥ 100 張 | −10 分 |
| 借券餘額 ≥ 1,000 張 | −10 分（做空部位大） |

> ⚠️ 主力（分點）買賣資料無官方 API，未納入計算。
        """)

    with st.expander("點擊展開 — 綜合評分與訊號對應"):
        st.markdown("""
**評分加總後對應訊號：**

| 評分範圍 | 訊號 | 建議動作 |
|---------|------|---------|
| ≥ 50 分 | 🟢 被錯殺 | 技術面多重超賣，可研究買進 |
| 20–49 分 | 🔵 考慮買進 | 出現買進訊號，留意觀察 |
| −15 到 19 分 | ⚪ 觀望 | 無明確訊號，持續觀察 |
| −40 到 −16 分 | 🟠 偏空觀望 | 技術面偏弱，謹慎操作 |
| ≤ −40 分 | 🔴 注意退場 | 多重空頭訊號，考慮減碼 |

> ⚠️ 以上訊號為技術面參考，不構成投資建議。投資有風險，請自行判斷。
        """)


# ═══════════════════════════════════════════════════════════
# 模式二：近期強弱掃描
# ═══════════════════════════════════════════════════════════
elif mode == "📅 近期強弱掃描":

    st.subheader("📅 近期強弱掃描")
    st.caption("以短線動能、量能、MA5、KD、法人連續方向評分，適合觀察近期強弱格局")

    # ── 參數列 ────────────────────────────────────────────────
    col_days, col_scope, col_n2 = st.columns([1, 2, 1])
    with col_days:
        st_n_days = st.selectbox("近期交易日數", [5, 10, 15, 30], index=1)
    with col_scope:
        st_scan_scope = st.radio(
            "掃描範圍",
            ["📌 精選清單（25支）", "📊 前5大ETF成分股", "🌐 全市場前N大"],
            horizontal=True,
        )
    with col_n2:
        st_top_n2 = st.number_input(
            "前N大", min_value=50, max_value=300, value=150, step=50,
            disabled=(st_scan_scope != "🌐 全市場前N大"),
        )

    col_btn2, col_tip2 = st.columns([1, 4])
    with col_btn2:
        run_st_scan = st.button("🔄 開始掃描", type="primary", use_container_width=True, key="st_scan_btn")
    with col_tip2:
        st.info(f"下載近 1 個月價格資料，取最近 {st_n_days} 個交易日計算短線評分。含三大法人連續動向（逐日抓取，約需較長時間）。")

    if run_st_scan:
        scope_map = {"📌 精選清單（25支）": "精選", "📊 前5大ETF成分股": "ETF", "🌐 全市場前N大": "全市場"}
        scope_key = scope_map[st_scan_scope]
        with st.spinner(f"掃描中（近 {st_n_days} 日），含法人歷史資料，請稍候..."):
            df_st, st_status = run_short_term_screener(
                n_days=st_n_days, scan_mode=scope_key, top_n=int(st_top_n2)
            )
        st.session_state["st_result"] = df_st
        st.session_state["st_status"] = st_status
        st.session_state["st_n_days"] = st_n_days

    if st.session_state.get("st_status"):
        st.caption(f"📊 {st.session_state['st_status']}")

    df_st = st.session_state.get("st_result")
    if df_st is None:
        st.info("點擊上方「開始掃描」按鈕，開始近期強弱分析。")
        st.stop()

    _n = st.session_state.get("st_n_days", st_n_days)

    # ── 摘要卡片 ─────────────────────────────────────────────
    bull  = len(df_st[df_st["訊號"] == "強勢多頭"])
    semi_bull = len(df_st[df_st["訊號"] == "短期偏多"])
    bear  = len(df_st[df_st["訊號"].isin(["弱勢空頭", "短期偏空"])])
    total_st = len(df_st)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("掃描股票數", total_st)
    c2.metric("🔥 強勢多頭 / 短期偏多", bull + semi_bull)
    c3.metric("🔴 短期偏空 / 弱勢空頭", bear)
    c4.metric("⚪ 盤整觀望", total_st - bull - semi_bull - bear)

    st.divider()

    # ── 類股強弱 ─────────────────────────────────────────────
    st.subheader("🏭 類股強弱排行（近期）")
    if "_sector" in df_st.columns:
        sector_st = (
            df_st[df_st["訊號"] != "資料不足"]
            .groupby("_sector")["評分"].mean().round(1)
            .reset_index().rename(columns={"_sector": "類股", "評分": "平均評分"})
            .sort_values("平均評分", ascending=False)
        )
        fig_st_sector = go.Figure(go.Bar(
            x=sector_st["類股"], y=sector_st["平均評分"],
            marker_color=["#ef5350" if v >= 0 else "#00b050" for v in sector_st["平均評分"]],
            text=sector_st["平均評分"], textposition="outside",
        ))
        fig_st_sector.update_layout(height=280, margin=dict(t=20, b=20))
        st.plotly_chart(fig_st_sector, use_container_width=True)

    st.divider()

    # ── Excel 下載輔助函式 ────────────────────────────────────
    def _to_excel(df_bull, df_semi, df_bear) -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_bull.to_excel(writer, sheet_name="強勢多頭", index=False)
            df_semi.to_excel(writer, sheet_name="短期偏多", index=False)
            df_bear.to_excel(writer, sheet_name="偏空弱勢", index=False)
        return buf.getvalue()

    # ── 三欄訊號排版 ──────────────────────────────────────────
    col_a, col_b, col_c = st.columns(3)
    ret_col = f"{_n}日漲跌(%)"

    def _st_cols(df_st, signals):
        cols = ["代號", "名稱", "評分", "收盤價", ret_col, "MA5", "K值", "原因"]
        return df_st[df_st["訊號"].isin(signals)][[c for c in cols if c in df_st.columns]]

    top_bull = _st_cols(df_st, ["強勢多頭"])
    top_semi = _st_cols(df_st, ["短期偏多"])
    top_bear = _st_cols(df_st, ["短期偏空", "弱勢空頭"])

    with col_a:
        st.subheader("🔥 強勢多頭")
        st.dataframe(top_bull if not top_bull.empty else pd.DataFrame({"訊息": ["目前無"]}),
                     hide_index=True, use_container_width=True)

    with col_b:
        st.subheader("🟢 短期偏多")
        st.dataframe(top_semi if not top_semi.empty else pd.DataFrame({"訊息": ["目前無"]}),
                     hide_index=True, use_container_width=True)

    with col_c:
        st.subheader("🔴 偏空 / 弱勢")
        st.dataframe(top_bear if not top_bear.empty else pd.DataFrame({"訊息": ["目前無"]}),
                     hide_index=True, use_container_width=True)

    # ── Excel 下載按鈕 ────────────────────────────────────────
    st.divider()
    if not (top_bull.empty and top_semi.empty and top_bear.empty):
        excel_bytes = _to_excel(top_bull, top_semi, top_bear)
        st.download_button(
            label="📥 下載 Excel（強勢多頭 / 短期偏多 / 偏空弱勢）",
            data=excel_bytes,
            file_name=f"近期強弱掃描_{_n}日.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.divider()

    # ── 完整清單 ──────────────────────────────────────────────
    with st.expander("📄 完整近期強弱清單（含法人今日資料）"):
        display_st = df_st.drop(columns=["_ticker", "_sector"], errors="ignore")
        st.dataframe(display_st, hide_index=True, use_container_width=True)

    # ── 評分說明 ──────────────────────────────────────────────
    with st.expander("📐 近期強弱評分規則說明"):
        st.markdown(f"""
| 評分項目 | 條件 | 分數 |
|---------|------|------|
| **{_n}日動能** | 漲幅 ≥8% / ≥5% / ≥3% | +30 / +20 / +10 |
| | 跌幅 ≤-8% / ≤-5% / ≤-3% | -30 / -20 / -10 |
| **量能** | 量比>1.5x 上漲 | +25 |
| | 量比>1.5x 下跌 | -25 |
| | 縮量(<0.7x) 下跌 | -10 |
| **MA5 趨勢** | 收盤>MA5 且 MA5 上升 | +20 |
| | 收盤<MA5 且 MA5 下降 | -20 |
| **{_n}日高低** | 創 {_n} 日新高 | +15 |
| | 創 {_n} 日新低 | -15 |
| **KD** | K<20（超賣） | +15 |
| | K>80（超買） | -10 |
| | KD 黃金交叉 | +15 |
| | KD 死亡交叉 | -15 |
| **三大法人** | 連續 ≥3 日買超 | +20 |
| | 連續 2 日買超 | +10 |
| | 連續 ≥3 日賣超 | -20 |
| | 連續 2 日賣超 | -10 |

**訊號對應：** 🔥 強勢多頭(≥50) / 🟢 短期偏多(25~49) / ⚪ 盤整(-24~24) / 🟠 短期偏空(-25~-49) / 🔴 弱勢空頭(≤-50)
        """)


# ═══════════════════════════════════════════════════════════
# 模式三：個股查詢
# ═══════════════════════════════════════════════════════════
elif mode == "🔍 個股查詢":
    # 建立選單：顯示名稱 → ticker
    all_tickers = [t for tickers in DEFAULT_STOCKS.values() for t in tickers]
    options = {get_display_name(t): t for t in all_tickers}

    col_sel, col_custom = st.columns([2, 2])
    with col_sel:
        selected_label = st.selectbox("選擇股票", list(options.keys()))
        ticker = options[selected_label]
    with col_custom:
        custom_code = st.text_input("或輸入自訂代號", placeholder="例：0050 或 2330")
        if custom_code:
            ticker = custom_code.strip().upper()
            if not ticker.endswith(".TW"):
                ticker += ".TW"

    period = st.select_slider("資料區間", options=["1mo", "3mo", "6mo", "1y"], value="3mo")

    with st.spinner(f"載入 {ticker} 資料..."):
        df = get_stock_data(ticker, period)

    if df is None or df.empty:
        st.error(f"無法取得 {ticker} 的資料，請確認代號是否正確")
        st.stop()

    df = add_all_indicators(df)

    with st.spinner("載入法人資料..."):
        inst_all = get_all_institutional_data()
    code_key = ticker.replace(".TW", "")
    inst_data = inst_all.get(code_key, {})
    sig = get_signal(df, inst_data=inst_data)

    # ── 股票基本資訊 ──
    info = get_stock_info(ticker)
    code = ticker.replace(".TW", "")
    st.subheader(f"{info.get('名稱', ticker)} （{code}）")

    # ── 訊號卡片 ──
    signal_color = {
        "被錯殺": "🟢", "考慮買進": "🔵",
        "注意退場": "🔴", "偏空觀望": "🟠", "觀望": "⚪"
    }
    icon = signal_color.get(sig["signal"], "⚪")

    col_sig, col_score, col_rsi, col_close = st.columns(4)
    col_sig.metric("訊號", f"{icon} {sig['signal']}")
    col_score.metric("綜合評分", sig["score"])
    col_rsi.metric("RSI(14)", f"{sig['rsi']:.1f}" if sig.get("rsi") else "N/A")
    col_close.metric("收盤價", f"{sig.get('close', 0):.2f}")

    # ── 分析理由 ──
    if sig["reasons"]:
        st.info("**分析依據：**\n" + "\n".join(f"- {r}" for r in sig["reasons"]))

    # ── 法人資料 ──
    if inst_data:
        st.subheader("🏦 法人籌碼（當日盤後）")
        ic1, ic2, ic3, ic4 = st.columns(4)
        ic1.metric("三大法人(張)", f"{inst_data.get('institutional_net', 0):+,}")
        ic2.metric("外資(張)",     f"{inst_data.get('foreign_net', 0):+,}")
        ic3.metric("投信(張)",     f"{inst_data.get('trust_net', 0):+,}")
        ic4.metric("自營商(張)",   f"{inst_data.get('dealer_net', 0):+,}")

        ic5, ic6, ic7, ic8 = st.columns(4)
        ic5.metric("融資餘額(張)", f"{inst_data.get('margin_balance', 0):,}")
        ic6.metric("融券餘額(張)", f"{inst_data.get('short_balance', 0):,}")
        ic7.metric("借券餘額(張)", f"{inst_data.get('lending_balance', 0):,}")
        ic8.metric("借券賣出(張)", f"{inst_data.get('lending_sell', 0):,}")
        st.caption("正值＝買超；負值＝賣超。1張＝1000股。資料來源：TWSE 盤後。")

    st.divider()

    # ── K線圖 + 技術指標 ──
    st.subheader("📊 K 線圖與技術指標")
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.25, 0.20],
        vertical_spacing=0.03,
        subplot_titles=("K線 + 布林帶 + 均線", "MACD", "RSI"),
    )

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="K線", increasing_line_color="#ef5350",
        decreasing_line_color="#26a69a",
    ), row=1, col=1)

    # 布林帶
    for col_name, color, dash in [
        ("BB_Upper", "rgba(173,216,230,0.6)", "dash"),
        ("BB_Mid", "rgba(173,216,230,0.9)", "solid"),
        ("BB_Lower", "rgba(173,216,230,0.6)", "dash"),
    ]:
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col_name], name=col_name,
            line=dict(color=color, dash=dash, width=1),
            showlegend=False,
        ), row=1, col=1)

    # 均線
    for ma, color in [("MA5", "#FF6B6B"), ("MA20", "#4ECDC4"), ("MA60", "#FFE66D")]:
        if ma in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma], name=ma,
                line=dict(color=color, width=1.5),
            ), row=1, col=1)

    # MACD
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD"], name="MACD",
        line=dict(color="#2196F3", width=1.5),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD_Signal"], name="訊號線",
        line=dict(color="#FF9800", width=1.5),
    ), row=2, col=1)
    colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df["MACD_Hist"]]
    fig.add_trace(go.Bar(
        x=df.index, y=df["MACD_Hist"], name="柱狀",
        marker_color=colors,
    ), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=df.index, y=df["RSI"], name="RSI",
        line=dict(color="#9C27B0", width=1.5),
    ), row=3, col=1)
    for level, color in [(70, "red"), (50, "gray"), (30, "green")]:
        fig.add_hline(y=level, line_dash="dot", line_color=color, row=3, col=1)

    fig.update_layout(
        height=700,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=40, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── 個股相關新聞 ──
    st.subheader(f"📰 {info.get('名稱', ticker)} 相關新聞")
    with st.spinner("載入新聞中..."):
        all_news = get_all_news(max_per_source=10)
        stock_news = get_stock_related_news(
            all_news,
            ticker=ticker,
            name=STOCK_NAMES.get(ticker, ""),
        )

    if not stock_news:
        st.info("目前無相關新聞，顯示最新財經新聞")
        stock_news = all_news[:10]

    for item in stock_news[:10]:
        with st.container():
            st.markdown(f"**[{item['標題']}]({item['連結']})**")
            col_src, col_time = st.columns(2)
            col_src.caption(f"來源：{item['來源']}")
            col_time.caption(item["時間"])
            if item["摘要"]:
                st.caption(item["摘要"])
            st.divider()


# ═══════════════════════════════════════════════════════════
# 模式三：各股技術分析
# ═══════════════════════════════════════════════════════════
elif mode == "📊 各股技術分析":

    # ── 快取歷史法人資料（TTL 30 分鐘）─────────────────────
    @st.cache_data(ttl=1800, show_spinner=False)
    def _cached_inst_history(code: str, n_days: int) -> pd.DataFrame:
        return fetch_institutional_history(code, n_days)

    @st.cache_data(ttl=1800, show_spinner=False)
    def _cached_margin_history(code: str, n_days: int) -> pd.DataFrame:
        return fetch_margin_history(code, n_days)

    # ── 股票選擇 ──────────────────────────────────────────
    all_tickers_ta = [t for tickers in DEFAULT_STOCKS.values() for t in tickers]
    options_ta = {get_display_name(t): t for t in all_tickers_ta}

    col_sel, col_custom, col_days = st.columns([2, 2, 1])
    with col_sel:
        selected_label_ta = st.selectbox("選擇股票", list(options_ta.keys()), key="ta_sel")
        ticker_ta = options_ta[selected_label_ta]
    with col_custom:
        custom_ta = st.text_input("或輸入自訂代號", placeholder="例：2330", key="ta_custom")
        if custom_ta:
            ticker_ta = custom_ta.strip().upper()
            if not ticker_ta.endswith(".TW"):
                ticker_ta += ".TW"
    with col_days:
        hist_days = st.selectbox("交易日數", [5, 10, 20, 30, 60, 120, 250], index=2, key="ta_days")

    code_ta   = ticker_ta.replace(".TW", "")
    name_ta   = STOCK_NAMES.get(ticker_ta, code_ta)
    # 依顯示天數選擇對應的 yfinance 抓取區間（需多一點緩衝供指標計算）
    if hist_days <= 30:
        price_period_ta = "3mo"
    elif hist_days <= 60:
        price_period_ta = "6mo"
    elif hist_days <= 120:
        price_period_ta = "1y"
    else:
        price_period_ta = "2y"

    with st.spinner(f"載入 {name_ta}（{code_ta}）股價資料..."):
        df_ta = get_stock_data(ticker_ta, price_period_ta)

    if df_ta is None or df_ta.empty:
        st.error(f"無法取得 {ticker_ta} 的資料，請確認代號是否正確")
        st.stop()

    df_ta = add_all_indicators(df_ta).tail(hist_days)

    st.subheader(f"📊 {name_ta}（{code_ta}）技術分析")

    # ── 計算成交量均線 ─────────────────────────────────────
    df_ta["MV5"]  = df_ta["Volume"].rolling(5).mean()
    df_ta["MV20"] = df_ta["Volume"].rolling(20).mean()
    # 成交量顏色：收紅（close >= open）= 紅，收黑（close < open）= 綠
    vol_colors = [
        "#ef5350" if c >= o else "#00b050"
        for c, o in zip(df_ta["Close"], df_ta["Open"])
    ]

    # ── 圖一：K線 / 成交量 / KD / MACD（4 格共享 X 軸）───
    fig_ta = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        row_heights=[0.45, 0.15, 0.20, 0.20],
        vertical_spacing=0.02,
        subplot_titles=("日K線 + 均線", "成交量（張）", "KD（9 日）", "MACD"),
    )

    # ── Row 1：K 線 + 均線 ────────────────────────────────
    fig_ta.add_trace(go.Candlestick(
        x=df_ta.index,
        open=df_ta["Open"], high=df_ta["High"],
        low=df_ta["Low"],   close=df_ta["Close"],
        name="K線",
        increasing_line_color="#ef5350",
        increasing_fillcolor="#ef5350",
        decreasing_line_color="#00b050",
        decreasing_fillcolor="#00b050",
    ), row=1, col=1)

    for ma, color in [("MA5", "#FF6B6B"), ("MA20", "#4ECDC4"), ("MA60", "#FFE66D")]:
        if ma in df_ta.columns and df_ta[ma].notna().any():
            fig_ta.add_trace(go.Scatter(
                x=df_ta.index, y=df_ta[ma], name=ma,
                line=dict(color=color, width=1.5),
            ), row=1, col=1)

    # ── Row 2：成交量柱狀圖 + MV5 + MV20 ─────────────────
    fig_ta.add_trace(go.Bar(
        x=df_ta.index,
        y=df_ta["Volume"] / 1000,   # 股 → 張
        name="量(張)",
        marker_color=vol_colors,
        showlegend=True,
    ), row=2, col=1)
    fig_ta.add_trace(go.Scatter(
        x=df_ta.index, y=df_ta["MV5"] / 1000,
        name="量均5", line=dict(color="#64B5F6", width=1.5),
    ), row=2, col=1)
    fig_ta.add_trace(go.Scatter(
        x=df_ta.index, y=df_ta["MV20"] / 1000,
        name="量均20", line=dict(color="#FF8A65", width=1.5),
    ), row=2, col=1)

    # ── Row 3：KD ─────────────────────────────────────────
    fig_ta.add_trace(go.Scatter(
        x=df_ta.index, y=df_ta["K"], name="K值",
        line=dict(color="#FF6B6B", width=1.8),
    ), row=3, col=1)
    fig_ta.add_trace(go.Scatter(
        x=df_ta.index, y=df_ta["D"], name="D值",
        line=dict(color="#4ECDC4", width=1.8),
    ), row=3, col=1)
    for kd_level, kd_color in [(80, "red"), (50, "gray"), (20, "green")]:
        fig_ta.add_hline(
            y=kd_level, line_dash="dot",
            line_color=kd_color, opacity=0.4,
            row=3, col=1,
        )

    # ── Row 4：MACD ───────────────────────────────────────
    fig_ta.add_trace(go.Scatter(
        x=df_ta.index, y=df_ta["MACD"], name="MACD",
        line=dict(color="#2196F3", width=1.5),
    ), row=4, col=1)
    fig_ta.add_trace(go.Scatter(
        x=df_ta.index, y=df_ta["MACD_Signal"], name="訊號線",
        line=dict(color="#FF9800", width=1.5),
    ), row=4, col=1)
    macd_colors = ["#ef5350" if v >= 0 else "#00b050" for v in df_ta["MACD_Hist"]]
    fig_ta.add_trace(go.Bar(
        x=df_ta.index, y=df_ta["MACD_Hist"],
        name="柱狀", marker_color=macd_colors,
    ), row=4, col=1)

    # ── 各子圖最新值標籤（Yahoo 股市風格）────────────────
    last_close  = float(df_ta["Close"].iloc[-1])
    last_vol    = float(df_ta["Volume"].iloc[-1]) / 1000
    last_k      = float(df_ta["K"].iloc[-1])
    last_macd   = float(df_ta["MACD"].iloc[-1])
    up_color    = "#ef5350" if df_ta["Close"].iloc[-1] >= df_ta["Open"].iloc[-1] else "#00b050"

    label_cfg = [
        (1, last_close, up_color,   f"{last_close:.2f}"),
        (2, last_vol,   "#888888",  f"{last_vol:,.0f}"),
        (3, last_k,     "#FF6B6B",  f"{last_k:.1f}"),
        (4, last_macd,  "#2196F3",  f"{last_macd:.3f}"),
    ]
    for row_n, y_val, color, label_text in label_cfg:
        # 虛線標記最新值
        fig_ta.add_hline(
            y=y_val, line_dash="dot", line_color=color,
            line_width=1, opacity=0.6, row=row_n, col=1,
        )
        # 右側色塊標籤
        fig_ta.add_annotation(
            x=1, xref=f"x{row_n} domain" if row_n > 1 else "x domain",
            y=y_val, yref=f"y{row_n}",
            text=f"<b>{label_text}</b>",
            showarrow=False,
            xanchor="left", yanchor="middle",
            bgcolor=color, bordercolor=color,
            font=dict(color="white", size=11),
            xshift=4,
        )

    fig_ta.update_layout(
        height=860,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=80, t=40, b=20),  # 右側加寬給標籤空間
    )
    # Y 軸標籤靠右顯示
    fig_ta.update_yaxes(side="right")
    # 成交量 Y 軸不顯示科學記號
    fig_ta.update_yaxes(tickformat=",d", row=2, col=1)
    st.plotly_chart(fig_ta, use_container_width=True)

    st.divider()

    # ── 圖二：三大法人買賣超（歷史）──────────────────────
    st.subheader("🏦 三大法人買賣超（張）")
    st.caption(f"抓取最近 {hist_days} 個交易日資料，約需 20–40 秒，結果快取 30 分鐘")

    with st.spinner("載入三大法人歷史資料..."):
        inst_hist = _cached_inst_history(code_ta, hist_days)

    if not inst_hist.empty:
        fig_inst = go.Figure()
        fig_inst.add_trace(go.Bar(
            x=inst_hist.index, y=inst_hist["foreign_net"],
            name="外資", marker_color="#2196F3",
        ))
        fig_inst.add_trace(go.Bar(
            x=inst_hist.index, y=inst_hist["trust_net"],
            name="投信", marker_color="#4CAF50",
        ))
        fig_inst.add_trace(go.Bar(
            x=inst_hist.index, y=inst_hist["dealer_net"],
            name="自營商", marker_color="#FF9800",
        ))
        fig_inst.add_hline(y=0, line_color="white", opacity=0.3)
        fig_inst.update_layout(
            barmode="group", height=350,
            xaxis=dict(tickformat="%m/%d", tickangle=-45),
            yaxis_title="買賣超（張）",
            legend=dict(orientation="h"),
            margin=dict(l=40, r=40, t=10, b=40),
        )
        st.plotly_chart(fig_inst, use_container_width=True)
    else:
        st.info("三大法人歷史資料暫時無法取得")

    st.divider()

    # ── 圖三：融資融券（歷史）────────────────────────────
    st.subheader("💹 融資融券每日買賣（張）")

    with st.spinner("載入融資融券歷史資料..."):
        margin_hist = _cached_margin_history(code_ta, hist_days)

    if not margin_hist.empty:
        fig_margin = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.5, 0.5],
            vertical_spacing=0.06,
            subplot_titles=("融資買賣（張）", "融券買賣（張）"),
        )
        fig_margin.add_trace(go.Bar(
            x=margin_hist.index, y=margin_hist["margin_buy"],
            name="融資買進", marker_color="#ef5350",
        ), row=1, col=1)
        fig_margin.add_trace(go.Bar(
            x=margin_hist.index, y=margin_hist["margin_sell"],
            name="融資賣出", marker_color="#26a69a",
        ), row=1, col=1)
        fig_margin.add_trace(go.Bar(
            x=margin_hist.index, y=margin_hist["short_sell"],
            name="融券賣出", marker_color="#9C27B0",
        ), row=2, col=1)
        fig_margin.add_trace(go.Bar(
            x=margin_hist.index, y=margin_hist["short_buy"],
            name="融券買進", marker_color="#FF9800",
        ), row=2, col=1)
        fig_margin.update_layout(
            height=420, barmode="group",
            xaxis2=dict(tickformat="%m/%d", tickangle=-45),
            legend=dict(orientation="h"),
            margin=dict(l=40, r=40, t=20, b=40),
        )
        st.plotly_chart(fig_margin, use_container_width=True)
    else:
        st.info("融資融券歷史資料暫時無法取得（TWSE 盤後才發布，假日無資料）")

    st.divider()

    # ── 表格：三大法人 + 融資融券 彙整 ──────────────────────
    st.subheader("📋 交易明細彙整表（張）")

    has_inst   = not inst_hist.empty
    has_margin = not margin_hist.empty

    if has_inst or has_margin:
        # 對齊日期索引（取聯集）
        all_dates = sorted(
            set(inst_hist.index.tolist() if has_inst else []) |
            set(margin_hist.index.tolist() if has_margin else []),
            reverse=True,
        )

        table_rows = []
        for dt in all_dates:
            row = {"日期": dt.strftime("%Y/%m/%d")}

            # 三大法人
            if has_inst and dt in inst_hist.index:
                r = inst_hist.loc[dt]
                row["外資(張)"]   = int(r.get("foreign_net", 0))
                row["投信(張)"]   = int(r.get("trust_net", 0))
                row["自營商(張)"] = int(r.get("dealer_net", 0))
                row["法人合計(張)"] = int(r.get("institutional_net", 0)
                                         or (r.get("foreign_net", 0)
                                             + r.get("trust_net", 0)
                                             + r.get("dealer_net", 0)))
            else:
                row["外資(張)"] = row["投信(張)"] = row["自營商(張)"] = row["法人合計(張)"] = None

            # 融資融券
            if has_margin and dt in margin_hist.index:
                r = margin_hist.loc[dt]
                row["融資買進(張)"] = int(r.get("margin_buy", 0))
                row["融資賣出(張)"] = int(r.get("margin_sell", 0))
                row["融資餘額(張)"] = int(r.get("margin_balance", 0))
                row["融券賣出(張)"] = int(r.get("short_sell", 0))
                row["融券買進(張)"] = int(r.get("short_buy", 0))
                row["融券餘額(張)"] = int(r.get("short_balance", 0))
            else:
                for c in ["融資買進(張)", "融資賣出(張)", "融資餘額(張)",
                          "融券賣出(張)", "融券買進(張)", "融券餘額(張)"]:
                    row[c] = None

            table_rows.append(row)

        df_table = pd.DataFrame(table_rows)

        # 計算合計列（數值欄位加總，日期顯示「合計」）
        numeric_cols = [c for c in df_table.columns if c != "日期"]
        total_row = {"日期": "【合計】"}
        for c in numeric_cols:
            col_data = pd.to_numeric(df_table[c], errors="coerce")
            total_row[c] = int(col_data.sum()) if col_data.notna().any() else None
        df_table = pd.concat(
            [df_table, pd.DataFrame([total_row])], ignore_index=True
        )

        # 格式化：數值加千分位，None 顯示 "-"
        def fmt(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "-"
            try:
                return f"{int(v):,}"
            except Exception:
                return str(v)

        df_display = df_table.copy()
        for c in numeric_cols:
            df_display[c] = df_table[c].apply(fmt)

        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("目前無可用的法人或融資融券資料")
