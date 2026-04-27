"""
5分鐘 KD 收集器 - 從 TAIFEX 即時 API 組 5 分鐘 K 棒並計算 KD
使用方式：python kd5_collector.py
Ctrl+C 停止，資料自動存到 kd5_data.csv
"""

import requests
import pandas as pd
import time
import os
import subprocess
from datetime import datetime

CSV_FILE    = "kd5_data.csv"
SYMBOL_IDS  = ["MXFE6-F", "MXFE6-M", "MXFF6-F", "MXFF6-M"]  # 日盤-F 夜盤-M
KD_PERIOD   = 9
BAR_MIN     = 5                          # 幾分鐘一根
GIT_PUSH    = True                       # False = 不自動 push
PUSH_EVERY  = 30                         # 每幾分鐘 push 一次

# ── 自動 git push ─────────────────────────────────────────────
def git_push():
    try:
        subprocess.run(["git", "add", CSV_FILE], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"data {datetime.now().strftime('%m/%d %H:%M')}"],
                       check=True, capture_output=True)
        subprocess.run(["git", "push"], check=True, capture_output=True)
        print(f"  [git push ok]", flush=True)
    except subprocess.CalledProcessError:
        pass  # 沒有新資料時 commit 會失敗，忽略

# ── 判斷日盤/夜盤 ─────────────────────────────────────────
def get_session():
    """08:45~13:45 日盤(-F)，其餘夜盤(-M)"""
    t = datetime.now().hour * 100 + datetime.now().minute
    return "F" if 845 <= t <= 1345 else "M"

# ── 抓即時報價 ───────────────────────────────────────────────
def fetch_price():
    session = get_session()
    try:
        r = requests.post(
            "https://mis.taifex.com.tw/futures/api/getQuoteDetail",
            json={"SymbolID": SYMBOL_IDS},
            timeout=8
        )
        quotes = r.json().get("RtData", {}).get("QuoteList", [])
        for q in quotes:
            if not q["SymbolID"].endswith(f"-{session}"):
                continue
            if q.get("CTotalVolume", "0") not in ("", "0") and q.get("CLastPrice", ""):
                return {
                    "symbol": q["SymbolID"],
                    "price":  float(q["CLastPrice"]),
                    "high":   float(q["CHighPrice"]),
                    "low":    float(q["CLowPrice"]),
                    "time":   q["CTime"],   # HHMMSS
                }
    except Exception as e:
        print(f"  [fetch error] {e}")
    return None

# ── 把 HHMMSS 轉成「5分鐘槽」的起始時間字串 ─────────────────
def bar_slot(time_str):
    h = int(time_str[:2])
    m = int(time_str[2:4])
    slot_m = (m // BAR_MIN) * BAR_MIN
    return f"{h:02d}:{slot_m:02d}"

# ── 讀取已存的 K 棒 CSV ──────────────────────────────────────
def load_bars():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        print(f"  Loaded {len(df)} bars from {CSV_FILE}")
        return df
    return pd.DataFrame(columns=["date","time","open","high","low","close"])

# ── 計算 KD ──────────────────────────────────────────────────
def calc_kd(df, period=KD_PERIOD):
    if len(df) < 2:
        return 50.0, 50.0
    low_min  = df["low"].rolling(period, min_periods=1).min()
    high_max = df["high"].rolling(period, min_periods=1).max()
    rng = high_max - low_min
    rsv = ((df["close"] - low_min) / rng.replace(0, 1) * 100).fillna(50)
    K = rsv.ewm(com=2, adjust=False).mean()
    D = K.ewm(com=2, adjust=False).mean()
    return round(K.iloc[-1], 2), round(D.iloc[-1], 2)

# ── 主迴圈 ───────────────────────────────────────────────────
def main():
    print(f"=== 5分鐘 KD 收集器 (period={KD_PERIOD}) ===")
    print(f"資料檔：{CSV_FILE}")
    print(f"Ctrl+C 停止\n")

    bars      = load_bars()
    cur_slot  = None
    cur_bar   = None
    last_push = datetime.now()

    while True:
        now   = datetime.now()
        today = now.strftime("%Y-%m-%d")   # 每次更新，夜盤跨午夜也正確
        data  = fetch_price()

        if data is None:
            print(f"  {now.strftime('%H:%M:%S')} - no data")
            time.sleep(10)
            continue

        slot  = bar_slot(data["time"])
        price = data["price"]

        # 新的 5 分鐘槽開始
        if slot != cur_slot:
            # 儲存上一根 K 棒
            if cur_bar and cur_slot:
                new_row = pd.DataFrame([{
                    "date":  today,
                    "time":  cur_slot,
                    "open":  cur_bar["open"],
                    "high":  cur_bar["high"],
                    "low":   cur_bar["low"],
                    "close": cur_bar["close"],
                }])
                bars = pd.concat([bars, new_row], ignore_index=True)
                bars.to_csv(CSV_FILE, index=False)

            # 開新 K 棒
            cur_slot = slot
            cur_bar  = {"open": price, "high": price, "low": price, "close": price}
        else:
            # 更新目前 K 棒
            cur_bar["high"]  = max(cur_bar["high"], price)
            cur_bar["low"]   = min(cur_bar["low"],  price)
            cur_bar["close"] = price

        # 計算 KD（用已完成的棒 + 目前這根）
        tmp_bar = pd.DataFrame([{
            "date": today, "time": cur_slot,
            "open": cur_bar["open"], "high": cur_bar["high"],
            "low": cur_bar["low"],   "close": cur_bar["close"]
        }])
        all_bars = pd.concat([bars, tmp_bar], ignore_index=True)
        K, D = calc_kd(all_bars)

        # 下引線判斷
        body       = abs(price - cur_bar["open"])
        lower_wick = min(price, cur_bar["open"]) - cur_bar["low"]
        ratio      = (lower_wick / body) if body > 0 else 999
        has_lower  = lower_wick > 10 and ratio >= 1.5   # 下引線 > 10點 且 >= 實體1.5倍

        # 顯示
        n_bars = len(all_bars)
        signal = ""
        if K < 20 and has_lower:
            signal = f"  *** 進場訊號！K<20 + 下引線({lower_wick:.0f}pt/{ratio:.1f}x) ***"
        elif K < 20:
            signal = f"  << K<20 超賣，等下引線（目前下引{lower_wick:.0f}pt/{ratio:.1f}x）"
        elif K > 80:
            signal = "  >> K>80 超買注意"

        upper_wick = cur_bar["high"] - max(price, cur_bar["open"])
        alert = " *** SIGNAL ***" if K < 20 and has_lower else ""
        print(f"{now.strftime('%H:%M:%S')} [{data['symbol']}]  {price:.0f}  K:{K:.1f}  D:{D:.1f}  下引:{lower_wick:.0f}pt  上引:{upper_wick:.0f}pt{alert}", flush=True)

        # 定時 git push
        if GIT_PUSH and (datetime.now() - last_push).seconds >= PUSH_EVERY * 60:
            git_push()
            last_push = datetime.now()

        time.sleep(15)   # 每 15 秒 poll 一次

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n停止收集。")
