import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(
    page_title="Peter Lynch GARP Workstation - Seluruh IDX",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

CACHE_FILE = "idx_screener_data.csv"
TICKERS_FILE = "idx_tickers.json"

# ==========================================
# 2. DAFTAR INDEKS & WATCHLIST PRESET
# ==========================================
PRESET_UNIVERSES = {
    "🇮🇩 Seluruh Saham IDX (980+ Emiten)": "ALL",
    "🏆 Indeks LQ45": [
        "ACES", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ARTO", "ASII", "BBCA", "BBNI",
        "BBRI", "BBTN", "BMRI", "BRIS", "BRPT", "CPIN", "EMTK", "ESSA", "EXCL", "GGRM",
        "GOTO", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ISAT", "ITMG", "JSMR",
        "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "MIKA", "PGAS", "PTBA", "SMGR", "SRTG",
        "TLKM", "TOWR", "UNTR", "UNVR", "VKTR"
    ],
    "📊 Indeks IDX30": [
        "ADRO", "AMMN", "AMRT", "ANTM", "ARTO", "ASII", "BBCA", "BBNI", "BBRI", "BMRI",
        "BRPT", "CPIN", "GOTO", "HRUM", "ICBP", "INCO", "INDF", "INKP", "ISAT", "ITMG",
        "KLBF", "MDKA", "MEDC", "PGAS", "PTBA", "SMGR", "TLKM", "TOWR", "UNTR", "UNVR"
    ],
    "🛡️ Peter Lynch Favorite Watchlist (Non-Bank)": [
        "ICBP", "INDF", "MYOR", "CMRY", "ULTJ", "SIDO", "KLBF", "AMRT", "MIDI", "MAPA",
        "MAPI", "ACES", "ERAA", "ASII", "AUTO", "DRMA", "SMSM", "ARNA", "TOTL", "PBID",
        "MARK", "TLKM", "ISAT", "EXCL", "MTEL", "MSTI", "ASGR", "MIKA", "HEAL", "SILO",
        "BIRD", "ASSA", "AKRA", "UNTR", "ADRO", "PTBA", "ITMG", "TAPG", "JPFA", "CPIN"
    ],
    "✏️ Kustom (Input Manual)": "CUSTOM"
}

# ==========================================
# 3. ENGINE SINKRONISASI & PARSING DATA
# ==========================================
def parse_single_ticker(t):
    full_t = f"{t}.JK" if not t.endswith(".JK") else t
    base_ticker = t.replace(".JK", "").strip().upper()
    
    try:
        stock = yf.Ticker(full_t)
        info = stock.info
        if not info:
            return None
            
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price or price <= 0:
            return None
            
        name = info.get("longName") or info.get("shortName") or base_ticker
        sector = info.get("sector", "Lainnya")
        industry = info.get("industry", "Lainnya")
        mkt_cap = (info.get("marketCap", 0) or 0) / 1e12  # Triliun Rp
        
        # PER
        per = info.get("trailingPE") or info.get("forwardPE")
        if per is None or per <= 0:
            eps = info.get("trailingEps")
            if eps and eps > 0:
                per = price / eps
            else:
                per = None
                
        # Div Yield
        div_yield_raw = info.get("dividendYield", 0) or 0
        div_yield = div_yield_raw * 100 if div_yield_raw < 1 else div_yield_raw
        
        # ROE
        roe_raw = info.get("returnOnEquity", 0) or 0
        roe = roe_raw * 100
        
        # DER & Current Ratio
        der_raw = info.get("debtToEquity")
        der = (der_raw / 100.0) if der_raw is not None else None
        current_ratio = info.get("currentRatio") or 1.0
        
        total_cash = info.get("totalCash", 0) or 0
        total_debt = info.get("totalDebt", 0) or 0
        is_net_cash = total_cash > total_debt
        
        # Cash Flow & Net Income
        ocf = info.get("operatingCashflow", 0) or 0
        net_income = info.get("netIncomeToCommon", 0) or 0
        ocf_to_ni = (ocf / net_income) if (net_income > 0 and ocf != 0) else 1.0
        
        # EPS Growth
        eg_raw = info.get("earningsGrowth")
        rg_raw = info.get("revenueGrowth")
        if eg_raw is not None:
            eps_growth = eg_raw * 100
        elif rg_raw is not None:
            eps_growth = rg_raw * 100
        else:
            eps_growth = 0.0
            
        # PEG & PEGY
        if per is not None and per > 0:
            peg = (per / eps_growth) if eps_growth > 0 else 99.9
            pegy = (per / (eps_growth + div_yield)) if (eps_growth + div_yield) > 0 else 99.9
            fair_per = max(5.0, min(eps_growth + div_yield, 25.0)) if eps_growth > 0 else 8.0
            fair_price = price * (fair_per / per)
            mos_pct = ((fair_price - price) / fair_price) * 100 if fair_price > 0 else -100.0
        else:
            peg = 99.9
            pegy = 99.9
            fair_price = 0.0
            mos_pct = -100.0
            
        # Lynch Category
        if eps_growth >= 15 and eps_growth <= 35:
            lynch_category = "Fast Grower 🚀"
        elif eps_growth > 35:
            lynch_category = "Hyper Grower (Waspada Siklus) 🔥"
        elif eps_growth >= 7 and eps_growth < 15:
            lynch_category = "Stalwart 🛡️"
        elif eps_growth >= 0 and eps_growth < 7:
            lynch_category = "Slow Grower 🐢"
        else:
            lynch_category = "Turnaround / Cyclical 🔄"
            
        # Peter Lynch Score (0 - 100)
        score = 0
        if pegy < 0.7: score += 35
        elif pegy <= 1.0: score += 28
        elif pegy <= 1.3: score += 15
        
        if 15 <= eps_growth <= 30: score += 25
        elif 10 <= eps_growth < 15 or 30 < eps_growth <= 40: score += 15
        elif eps_growth > 40: score += 10
        
        if der is not None:
            if der <= 0.3 or is_net_cash: score += 20
            elif der <= 0.5: score += 15
            elif der <= 0.8: score += 8
        else:
            if is_net_cash: score += 10
            
        if roe >= 15: score += 12
        elif roe >= 10: score += 6
        if ocf_to_ni >= 0.8: score += 8
        
        return {
            "Ticker": base_ticker,
            "Full_Ticker": full_t,
            "Nama Emiten": name,
            "Sektor": sector,
            "Industri": industry,
            "Kategori Lynch": lynch_category,
            "Harga (Rp)": round(price, 0),
            "Market Cap (T)": round(mkt_cap, 2),
            "PER (x)": round(per, 2) if per is not None else None,
            "EPS Growth (%)": round(eps_growth, 2),
            "Div Yield (%)": round(div_yield, 2),
            "PEG (x)": round(peg, 2),
            "PEGY (x)": round(pegy, 2),
            "ROE (%)": round(roe, 2),
            "DER (x)": round(der, 2) if der is not None else np.nan,
            "Net Cash": "Ya" if is_net_cash else "Tidak",
            "Current Ratio (x)": round(current_ratio, 2),
            "OCF / Net Income (x)": round(ocf_to_ni, 2),
            "Harga Wajar Lynch (Rp)": round(fair_price, 0),
            "Margin of Safety (%)": round(mos_pct, 1),
            "Lynch Score": score
        }
    except Exception:
        return None

def run_sync_all():
    if not os.path.exists(TICKERS_FILE):
        st.error(f"File {TICKERS_FILE} tidak ditemukan.")
        return None
        
    with open(TICKERS_FILE, "r") as f:
        tickers = json.load(f)
        
    prog_bar = st.progress(0.0)
    status_label = st.empty()
    results = []
    
    with ThreadPoolExecutor(max_workers=12) as executor:
        future_to_ticker = {executor.submit(parse_single_ticker, t): t for t in tickers}
        completed = 0
        total = len(tickers)
        for future in as_completed(future_to_ticker):
            completed += 1
            res = future.result()
            if res:
                results.append(res)
            if completed % 15 == 0 or completed == total:
                prog_bar.progress(completed / total)
                status_label.text(f"Sinkronisasi data IDX: {completed}/{total} saham diproses ({len(results)} valid)...")
                
    prog_bar.empty()
    status_label.empty()
    
    df = pd.DataFrame(results)
    df.sort_values(by="Lynch Score", ascending=False, inplace=True)
    df.to_csv(CACHE_FILE, index=False)
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def load_all_idx_data():
    if os.path.exists(CACHE_FILE):
        return pd.read_csv(CACHE_FILE)
    return None

# ==========================================
# 4. SIDEBAR: PENGATURAN & FILTER PETER LYNCH
# ==========================================
st.sidebar.title("🔍 Parameter Peter Lynch")

# Tombol Sinkronisasi Manual
if st.sidebar.button("🔄 Sinkronisasi / Refresh Data IDX", help="Mengunduh data fundamental terbaru dari 980+ emiten IDX"):
    with st.spinner("Sedang menyinkronkan seluruh emiten IDX via multi-threading..."):
        df_new = run_sync_all()
        if df_new is not None:
            st.sidebar.success(f"Berhasil memperbarui {len(df_new)} saham!")
            st.cache_data.clear()
            st.rerun()

# Pilihan Universe Saham
st.sidebar.subheader("1. Pemilihan Universe Saham")
selected_preset = st.sidebar.selectbox("Pilih Daftar Saham:", list(PRESET_UNIVERSES.keys()))

custom_tickers = ""
if selected_preset == "✏️ Kustom (Input Manual)":
    custom_tickers = st.sidebar.text_area(
        "Masukkan Kode Saham (pisahkan koma):",
        value="ICBP, ASII, TLKM, UNTR, SIDO, ARNA",
        height=80
    )

# Pengecualian Sektor Bank
exclude_banks = st.sidebar.checkbox(
    "Kecualikan Sektor Perbankan (Financial Services)",
    value=True,
    help="Peter Lynch memisahkan bank karena struktur hutang (DER) tinggi adalah hal yang normal bagi bank."
)

st.sidebar.subheader("2. Filter Pertumbuhan & Valuasi (GARP)")
min_growth, max_growth = st.sidebar.slider(
    "Rentang EPS Growth (%):",
    min_value=-20.0, max_value=80.0, value=(10.0, 35.0), step=1.0,
    help="Peter Lynch mengutamakan Fast Grower (15% - 30%) yang konsisten."
)
max_pegy = st.sidebar.slider(
    "Maksimum PEGY Ratio (x):",
    min_value=0.2, max_value=3.0, value=1.2, step=0.05,
    help="PEGY = PER / (Growth + Dividend). Nilai < 1.0x menandakan saham undervalued."
)
max_per = st.sidebar.slider(
    "Maksimum PER (x):",
    min_value=3.0, max_value=50.0, value=25.0, step=1.0
)

st.sidebar.subheader("3. Filter Kualitas & Neraca (Balance Sheet)")
max_der = st.sidebar.slider(
    "Maksimum DER (Debt-to-Equity) (x):",
    min_value=0.1, max_value=3.0, value=0.8, step=0.05,
    help="Filter utang aman ala Peter Lynch (DER < 0.5x – 0.8x)."
)
min_roe = st.sidebar.slider(
    "Minimum ROE (%):",
    min_value=0.0, max_value=40.0, value=12.0, step=1.0
)
min_ocf_ni = st.sidebar.slider(
    "Minimum OCF / Net Income (x):",
    min_value=0.0, max_value=2.0, value=0.6, step=0.1,
    help="Memastikan laba perusahaan didukung arus kas operasional riil."
)

# ==========================================
# 5. PEMROSESAN DATA
# ==========================================
df_all = load_all_idx_data()

if df_all is None or df_all.empty:
    st.info("⚠️ Data cache fundamental seluruh IDX belum tersedia. Klik tombol di bawah untuk memulai sinkronisasi 980+ emiten IDX pertama kali.")
    if st.button("🚀 Mulai Unduh Data Seluruh Saham IDX"):
        with st.spinner("Sedang memproses seluruh emiten IDX..."):
            df_all = run_sync_all()
            if df_all is not None:
                st.success("Sinkronisasi selesai!")
                st.cache_data.clear()
                st.rerun()
    st.stop()

# Info Tanggal Cache
if os.path.exists(CACHE_FILE):
    cache_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE)).strftime("%d %b %Y, %H:%M WIB")
else:
    cache_time = "Baru saja"

# Filter Universe
universe_val = PRESET_UNIVERSES[selected_preset]
if universe_val == "ALL":
    df_universe = df_all.copy()
elif universe_val == "CUSTOM":
    user_symbols = [x.strip().upper() for x in custom_tickers.split(",") if x.strip()]
    df_universe = df_all[df_all["Ticker"].isin(user_symbols)].copy()
else:
    df_universe = df_all[df_all["Ticker"].isin(universe_val)].copy()

# Filter Sektor Bank
if exclude_banks:
    df_universe = df_universe[df_universe["Sektor"] != "Financial Services"]

# Terapkan Filter Kriteria Peter Lynch
df_filtered = df_universe[
    (df_universe["PER (x)"].notnull()) &
    (df_universe["PER (x)"] > 0) &
    (df_universe["PER (x)"] <= max_per) &
    (df_universe["EPS Growth (%)"] >= min_growth) &
    (df_universe["EPS Growth (%)"] <= max_growth) &
    (df_universe["PEGY (x)"] <= max_pegy) &
    ((df_universe["DER (x)"].isna()) | (df_universe["DER (x)"] <= max_der)) &
    (df_universe["ROE (%)"] >= min_roe) &
    (df_universe["OCF / Net Income (x)"] >= min_ocf_ni)
].sort_values(by="Lynch Score", ascending=False)

# ==========================================
# 6. HEADER & DASHBOARD UTAMA
# ==========================================
st.title("📈 Peter Lynch IDX Equity Screener & Workstation")
st.markdown(
    f"Analisis komprehensif saham **Bursa Efek Indonesia (IDX)** berbasis metode investasi **Peter Lynch** (*Growth at a Reasonable Price*). "
    f"Database mencakup **{len(df_all)} emiten aktif** *(Update terakhir: {cache_time})*."
)

tab1, tab2, tab3 = st.tabs([
    "🎯 1. Peter Lynch Screener", 
    "🔬 2. Deep-Dive Company Analyzer", 
    "💼 3. Portfolio & Sell-Trigger Monitor"
])

# ==========================================
# TAB 1: SCREENER & KUADRAN GARP
# ==========================================
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Universe Dianalisis", f"{len(df_universe)} Saham")
    col2.metric("Lolos Kriteria Lynch", f"{len(df_filtered)} Saham")
    avg_pegy = df_filtered["PEGY (x)"].mean() if not df_filtered.empty else 0
    col3.metric("Rata-rata PEGY Lolos", f"{avg_pegy:.2f}x")
    top_pick = df_filtered.iloc[0]["Ticker"] if not df_filtered.empty else "-"
    col4.metric("Top Skor GARP", top_pick)

    st.subheader(f"📋 Hasil Screening Saham ({len(df_filtered)} Emiten Lolos)")
    
    if not df_filtered.empty:
        # Pilihan filter sektor tambahan di atas tabel
        all_sectors = ["Semua Sektor"] + sorted([s for s in df_filtered["Sektor"].dropna().unique().tolist() if s != "Unknown"])
        c_filter1, c_filter2 = st.columns([2, 1])
        with c_filter1:
            sel_sec = st.selectbox("Saring berdasarkan Sektor:", all_sectors)
        with c_filter2:
            sort_by = st.selectbox("Urutkan Berdasarkan:", ["Lynch Score", "PEGY (x)", "Margin of Safety (%)", "EPS Growth (%)", "ROE (%)"])
            
        df_show = df_filtered if sel_sec == "Semua Sektor" else df_filtered[df_filtered["Sektor"] == sel_sec]
        ascending = True if sort_by == "PEGY (x)" else False
        df_show = df_show.sort_values(by=sort_by, ascending=ascending)
        
        st.dataframe(
            df_show[[
                "Ticker", "Nama Emiten", "Sektor", "Kategori Lynch", "Harga (Rp)", "PER (x)",
                "EPS Growth (%)", "Div Yield (%)", "PEGY (x)", "ROE (%)", "DER (x)",
                "Net Cash", "OCF / Net Income (x)", "Margin of Safety (%)", "Lynch Score"
            ]],
            use_container_width=True,
            hide_index=True
        )
        
        # Download button CSV hasil filter
        csv_data = df_show.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Hasil Screening (CSV)",
            data=csv_data,
            file_name=f"screener_peter_lynch_idx_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.warning("Tidak ada saham yang lolos kriteria filter saat ini. Coba longgarkan slider parameter di sidebar kiri.")

    # Grafik Sebaran GARP
    st.markdown("---")
    st.subheader("📊 Peta Kuadran Peter Lynch: PER vs. Total Return Driver (Growth + Div Yield)")
    
    df_plot = df_universe[
        (df_universe["PER (x)"].notnull()) &
        (df_universe["PER (x)"] > 0) &
        (df_universe["PER (x)"] < 50) &
        (df_universe["EPS Growth (%)"] > -15) &
        (df_universe["EPS Growth (%)"] < 80)
    ].copy()
    
    df_plot["Total Return Driver (%)"] = df_plot["EPS Growth (%)"] + df_plot["Div Yield (%)"]
    df_plot["Lolos Filter"] = df_plot["Ticker"].isin(df_filtered["Ticker"])
    
    fig = px.scatter(
        df_plot,
        x="Total Return Driver (%)",
        y="PER (x)",
        size="Market Cap (T)",
        color="Kategori Lynch",
        hover_name="Nama Emiten",
        text="Ticker",
        hover_data=["PEGY (x)", "ROE (%)", "DER (x)", "Lynch Score"],
        title="Garis Hijau = Garis Wajar PEGY 1.0x (Saham di bawah garis hijau adalah saham Undervalued / Murah)",
        height=550
    )
    
    x_line = np.linspace(5, 75, 100)
    fig.add_trace(go.Scatter(
        x=x_line, y=x_line, mode="lines",
        name="Batas Wajar (PEGY = 1.0x)",
        line=dict(color="green", dash="dash", width=2)
    ))
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# TAB 2: DEEP-DIVE COMPANY ANALYZER
# ==========================================
with tab2:
    st.subheader("🔬 Bedah Fundamental & Forensik Laporan Keuangan")
    
    all_tickers_list = sorted(df_all["Ticker"].tolist())
    # Utamakan saham lolos filter di pilihan awal jika ada
    default_select_idx = 0
    if not df_filtered.empty:
        top_ticker = df_filtered.iloc[0]["Ticker"]
        if top_ticker in all_tickers_list:
            default_select_idx = all_tickers_list.index(top_ticker)
            
    selected_ticker = st.selectbox(
        "Pilih Emiten untuk Dianalisis Secara Mendalam:",
        options=all_tickers_list,
        index=default_select_idx
    )
    
    row = df_all[df_all["Ticker"] == selected_ticker].iloc[0]
    
    st.markdown(f"### {row['Nama Emiten']} (`{row['Ticker']}`) — {row['Kategori Lynch']}")
    st.caption(f"Sektor: **{row['Sektor']}** | Industri: **{row.get('Industri', '-')}** | Market Cap: **Rp {row['Market Cap (T)']} T**")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Harga Saat Ini", f"Rp {row['Harga (Rp)']:,.0f}")
    c2.metric("Harga Wajar Lynch", f"Rp {row['Harga Wajar Lynch (Rp)']:,.0f}", f"{row['Margin of Safety (%)']}% MoS")
    pegy_val = f"{row['PEGY (x)']}x" if pd.notnull(row['PEGY (x)']) else "-"
    c3.metric("PEGY Ratio", pegy_val, "Ideal < 1.0x", delta_color="inverse")
    c4.metric("ROE", f"{row['ROE (%)']}%")
    der_val = f"{row['DER (x)']}x" if pd.notnull(row['DER (x)']) else "N/A"
    c5.metric("DER (Utang/Modal)", der_val, f"Net Cash: {row['Net Cash']}")
    
    st.markdown("#### Checklist Peter Lynch")
    pegy_num = row["PEGY (x)"] if pd.notnull(row["PEGY (x)"]) else 99
    der_num = row["DER (x)"] if pd.notnull(row["DER (x)"]) else 0
    
    checks = [
        ("✅" if pegy_num <= 1.0 else "⚠️", f"**Valuasi PEGY:** {pegy_num:.2f}x (Standar emas Peter Lynch: PEGY < 1.0x)."),
        ("✅" if 15 <= row["EPS Growth (%)"] <= 30 else "ℹ️", f"**Pertumbuhan Laba (Growth):** {row['EPS Growth (%)']:.1f}% per tahun (Ideal Fast Grower: 15% – 30%)."),
        ("✅" if der_num <= 0.5 else "⚠️", f"**Kesehatan Neraca:** DER {der_num:.2f}x dan Current Ratio {row['Current Ratio (x)']}x (Lynch menyukai utang rendah)."),
        ("✅" if row["OCF / Net Income (x)"] >= 0.8 else "🚨", f"**Kualitas Laba Bersih:** OCF/Net Income {row['OCF / Net Income (x)']}x (Nilai > 0.8x membuktikan laba riil berupa kas)."),
    ]
    for icon, desc in checks:
        st.write(f"{icon} {desc}")

    # Mengambil Laporan Keuangan Detail untuk 1 Saham Terpilih
    with st.spinner("Memuat tren laporan keuangan historis dari Yahoo Finance..."):
        try:
            t_obj = yf.Ticker(row["Full_Ticker"])
            inc = t_obj.income_stmt
            bs = t_obj.balance_sheet
            
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                if inc is not None and not inc.empty and "Total Revenue" in inc.index and "Net Income" in inc.index:
                    df_fin = pd.DataFrame({
                        "Revenue (Miliar Rp)": inc.loc["Total Revenue"] / 1e9,
                        "Net Income (Miliar Rp)": inc.loc["Net Income"] / 1e9
                    }).dropna().iloc[::-1]
                    df_fin.index = pd.to_datetime(df_fin.index).strftime("%Y")
                    fig_fin = px.bar(df_fin, barmode="group", title="Tren Pendapatan & Laba Bersih Tahunan")
                    st.plotly_chart(fig_fin, use_container_width=True)
                else:
                    st.info("Data laporan laba rugi historis tidak tersedia secara lengkap untuk emiten ini.")
                    
            with col_chart2:
                if bs is not None and not bs.empty and "Inventory" in bs.index and inc is not None and not inc.empty and "Total Revenue" in inc.index:
                    df_inv = pd.DataFrame({
                        "Revenue": inc.loc["Total Revenue"],
                        "Inventory": bs.loc["Inventory"]
                    }).dropna().iloc[::-1]
                    df_inv["Inventory to Revenue (%)"] = (df_inv["Inventory"] / df_inv["Revenue"]) * 100
                    df_inv.index = pd.to_datetime(df_inv.index).strftime("%Y")
                    fig_inv = px.line(
                        df_inv, y="Inventory to Revenue (%)", markers=True,
                        title="Forensik Persediaan: Rasio Inventory terhadap Revenue (%)"
                    )
                    st.plotly_chart(fig_inv, use_container_width=True)
                    st.caption("💡 **Prinsip Lynch:** Jika rasio persediaan melonjak lebih cepat daripada penjualan, waspadai risiko perlambatan bisnis.")
                else:
                    st.info("Data persediaan (inventory) tidak berlaku atau tidak tersedia untuk sektor ini.")
        except Exception as e:
            st.warning("Tidak dapat memuat detail grafik historis.")

# ==========================================
# TAB 3: PORTFOLIO & SELL-TRIGGER MONITOR
# ==========================================
with tab3:
    st.subheader("💼 Pemantauan Portofolio & Sinyal Jual Otomatis (Lynch Sell Rules)")
    st.markdown("Pantau posisi saham Anda dari seluruh emiten BEI. Sistem mendeteksi kapan fundamental memburuk atau valuasi terlalu mahal:")
    
    default_portfolio = pd.DataFrame([
        {"Ticker": "ICBP", "Jumlah Lot": 50, "Harga Beli Rata-rata (Rp)": 10200},
        {"Ticker": "ARNA", "Jumlah Lot": 200, "Harga Beli Rata-rata (Rp)": 680},
        {"Ticker": "MAPA", "Jumlah Lot": 100, "Harga Beli Rata-rata (Rp)": 820},
        {"Ticker": "MSTI", "Jumlah Lot": 120, "Harga Beli Rata-rata (Rp)": 1450},
    ])
    
    edited_port = st.data_editor(default_portfolio, num_rows="dynamic", use_container_width=True)
    
    if not edited_port.empty:
        port_merged = pd.merge(edited_port, df_all, on="Ticker", how="inner")
        if not port_merged.empty:
            port_merged["Nilai Investasi Awal (Rp)"] = port_merged["Jumlah Lot"] * 100 * port_merged["Harga Beli Rata-rata (Rp)"]
            port_merged["Nilai Pasar Saat Ini (Rp)"] = port_merged["Jumlah Lot"] * 100 * port_merged["Harga (Rp)"]
            port_merged["Floating P&L (%)"] = ((port_merged["Harga (Rp)"] - port_merged["Harga Beli Rata-rata (Rp)"]) / port_merged["Harga Beli Rata-rata (Rp)"]) * 100
            
            def evaluate_action(r):
                pegy_v = r["PEGY (x)"] if pd.notnull(r["PEGY (x)"]) else 99
                der_v = r["DER (x)"] if pd.notnull(r["DER (x)"]) else 0
                growth_v = r["EPS Growth (%)"] if pd.notnull(r["EPS Growth (%)"]) else 0
                roe_v = r["ROE (%)"] if pd.notnull(r["ROE (%)"]) else 0
                
                if pegy_v > 1.6:
                    return "🔴 SELL / TRIM (Valuasi Sangat Mahal, PEGY > 1.6x)"
                elif der_v > 1.2 and r["Sektor"] != "Financial Services":
                    return "🔴 SELL / REVIEW (Utang Membengkak, DER > 1.2x)"
                elif growth_v < 3:
                    return "🟠 PANTAU KETAT (Pertumbuhan Laba Stagnan < 3%)"
                elif pegy_v <= 0.9 and roe_v >= 14 and (der_v <= 0.6 or r["Net Cash"] == "Ya"):
                    return "🟢 BUY MORE / ACCUMULATE (GARP Idaman)"
                else:
                    return "🔵 HOLD (Fundamental Terjaga)"
                    
            port_merged["Rekomendasi Lynch"] = port_merged.apply(evaluate_action, axis=1)
            
            total_modal = port_merged["Nilai Investasi Awal (Rp)"].sum()
            total_pasar = port_merged["Nilai Pasar Saat Ini (Rp)"].sum()
            total_return = ((total_pasar - total_modal) / total_modal) * 100 if total_modal > 0 else 0
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Modal Portofolio", f"Rp {total_modal:,.0f}")
            m2.metric("Nilai Pasar Portofolio", f"Rp {total_pasar:,.0f}")
            m3.metric("Total Floating Return", f"{total_return:.2f}%")
            
            st.dataframe(
                port_merged[[
                    "Ticker", "Nama Emiten", "Kategori Lynch", "Jumlah Lot", "Harga Beli Rata-rata (Rp)",
                    "Harga (Rp)", "Floating P&L (%)", "PEGY (x)", "DER (x)", "Rekomendasi Lynch"
                ]],
                use_container_width=True,
                hide_index=True
            )
