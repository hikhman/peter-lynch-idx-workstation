import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import yfinance as yf

def parse_ticker_data(t):
    full_t = f"{t}.JK" if not t.endswith(".JK") else t
    base_ticker = t.replace(".JK", "")
    
    try:
        stock = yf.Ticker(full_t)
        info = stock.info
        if not info:
            return None
            
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price or price <= 0:
            return None
            
        name = info.get("longName") or info.get("shortName") or base_ticker
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        mkt_cap = (info.get("marketCap", 0) or 0) / 1e12  # Triliun Rupiah
        
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
        der = (der_raw / 100.0) if der_raw is not None else (None if sector == "Financial Services" else 0.0)
        current_ratio = info.get("currentRatio") or 1.0
        
        total_cash = info.get("totalCash", 0) or 0
        total_debt = info.get("totalDebt", 0) or 0
        is_net_cash = total_cash > total_debt
        
        # OCF & Net Income
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
            
        # Kategori Peter Lynch
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
            "DER (x)": round(der, 2) if der is not None else None,
            "Net Cash": "Ya" if is_net_cash else "Tidak",
            "Current Ratio (x)": round(current_ratio, 2),
            "OCF / Net Income (x)": round(ocf_to_ni, 2),
            "Harga Wajar Lynch (Rp)": round(fair_price, 0),
            "Margin of Safety (%)": round(mos_pct, 1),
            "Lynch Score": score
        }
    except Exception:
        return None

def sync_all(max_workers=10):
    with open("idx_tickers.json", "r") as f:
        tickers = json.load(f)
        
    print(f"Memulai sinkronisasi data {len(tickers)} emiten IDX...")
    start_time = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(parse_ticker_data, t): t for t in tickers}
        completed = 0
        for future in as_completed(future_to_ticker):
            completed += 1
            res = future.result()
            if res:
                results.append(res)
            if completed % 100 == 0 or completed == len(tickers):
                print(f"Progres: {completed}/{len(tickers)} ({len(results)} valid) - Waktu: {time.time()-start_time:.1f}s")
                
    df = pd.DataFrame(results)
    df.sort_values(by="Lynch Score", ascending=False, inplace=True)
    df.to_csv("idx_screener_data.csv", index=False)
    print(f"Selesai! {len(df)} saham berhasil disimpan ke idx_screener_data.csv dalam {time.time()-start_time:.1f} detik.")

if __name__ == "__main__":
    sync_all(max_workers=12)
