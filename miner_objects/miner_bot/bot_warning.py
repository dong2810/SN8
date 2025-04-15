# bot_warning.py (v2)

import requests
import numpy as np
import time
import os
import json
from datetime import datetime
from db_handler import DBHandler

# =========================
# Load Config + Secret
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, 'config.json')) as f:
    config = json.load(f)

with open(os.path.join(BASE_DIR, 'secret.json')) as f:
    secret = json.load(f)

TELEGRAM_BOT_TOKEN = secret['telegram']['bot_token']
TELEGRAM_CHAT_ID = secret['telegram']['chat_id']
API_URL = secret['api']['url']
API_KEY = secret['api']['api_key']

COINS = config['settings']['coin_list']
TEST_MODE = config['settings']['test_mode']
SCAN_INTERVAL = config['settings']['scan_interval_seconds']

# =========================
# Global Init
# =========================
db = DBHandler()

# =========================
# Functions
# =========================

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def fetch_klines(symbol, interval='1h', limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        closes = [float(item[4]) for item in data]
        volumes = [float(item[5]) for item in data]
        highs = [float(item[2]) for item in data]
        lows = [float(item[3]) for item in data]
        return closes, volumes, highs, lows
    except Exception as e:
        print(f"Fetch Error {symbol}: {e}")
        return None, None, None, None

def calculate_rsi(closes, period=14):
    closes = np.array(closes)
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(closes)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(closes)):
        delta = deltas[i - 1] if i > 0 else 0
        upval = max(delta, 0)
        downval = -min(delta, 0)
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return float(rsi[-1])

def calculate_adx(highs, lows, closes, period=14):
    highs = np.array(highs)
    lows = np.array(lows)
    closes = np.array(closes)

    plus_dm = np.maximum(highs[1:] - highs[:-1], 0)
    minus_dm = np.maximum(lows[:-1] - lows[1:], 0)
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - closes[:-1]),
        np.abs(lows[1:] - closes[:-1])
    ])
    atr = np.convolve(tr, np.ones(period)/period, mode='valid')
    plus_di = 100 * np.convolve(plus_dm, np.ones(period)/period, mode='valid') / atr
    minus_di = 100 * np.convolve(minus_dm, np.ones(period)/period, mode='valid') / atr
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = np.convolve(dx, np.ones(period)/period, mode='valid')
    return float(adx[-1])


def calculate_ma(closes, period):
    closes = np.array(closes)
    ma = np.convolve(closes, np.ones(period)/period, mode='valid')
    return float(ma[-1])

def detect_entry(closes, volumes, rsi_now, adx_now):
    if len(closes) < 30:
        return None

    ma7_now = np.mean(closes[-7:])
    ma7_prev = np.mean(closes[-8:-1])
    ma25_now = np.mean(closes[-25:])

    ma7_ma25_gap = abs(ma7_now - ma25_now) / ma25_now if ma25_now != 0 else 0
    last_price = closes[-1] 
    volume_now = volumes[-1]
    volume_avg = np.mean(volumes[-21:-1])
    avg_range = np.mean([abs(closes[i] - closes[i-1]) for i in range(-5, 0)])

    if adx_now < 20:
        return None

    if last_price > ma7_now and ma7_now > ma7_prev and rsi_now > 52:
        if ma7_ma25_gap >= 0.00072 and volume_now > 1.2 * volume_avg and avg_range > 0.001:
            return "LONG"

    if last_price < ma7_now and ma7_now < ma7_prev and rsi_now < 48:
        if ma7_ma25_gap >= 0.00072 and volume_now > 1.2 * volume_avg and avg_range > 0.001:
            return "SHORT"

    return None

def get_trailing_distance(profit):
    if profit < 0.02:
        return 0.002
    elif profit < 0.05:
        return 0.005
    else:
        return 0.01
        
def get_mdd_threshold(profit):

    if profit <= 0:
        return 0.005
    elif profit < 0.02:
        return 0.008
    elif profit < 0.05:
        return 0.011
    else:
        return 0.014

def place_trade(trade_pair, order_type, leverage=0.1):
    # Chuyển đổi symbol: thay "USDT" thành "USD"
    trade_pair_converted = trade_pair.replace("USDT", "USD")
    
    if TEST_MODE:
        print(f"[TEST MODE] Would place {order_type} for {trade_pair_converted}")
        send_telegram_message(f"[TEST MODE] {order_type} {trade_pair_converted}")
    else:
        try:
            payload = {
                "trade_pair": trade_pair_converted,  # Sử dụng trade_pair_converted
                "order_type": order_type,
                "leverage": leverage,
                "api_key": API_KEY
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(API_URL, headers=headers, json=payload)
            print(f"Trade API Response: {response.status_code}")
        except Exception as e:
            print(f"Trade API Error: {e}")

def print_db_positions():
    positions = db.list_positions()
    print("\n📋 Danh sách vị thế hiện tại:")
    if not positions:
        print("(Không có lệnh nào)")
    else:
        for p in positions:
            print(p)

# =========================
# Main Loop
# =========================

def main_loop():
    print("Bot Warning V2 đang chạy...")
    send_telegram_message("🚀 Bot Warning V2 đã khởi động!")

    while True:
        try:
            for symbol in COINS:
                closes, volumes, highs, lows = fetch_klines(symbol)
                if closes is None or volumes is None or highs is None or lows is None or len(closes) < 30:
                    continue

                # Lấy thông tin giá cuối và khối lượng hiện tại
                last_price = float(closes[-1])
                current_vol = float(volumes[-1])

                 # Tính RSI của cây nến cuối (đã ép float trong hàm)
                rsi_now = calculate_rsi(closes)
                adx_now = calculate_adx(highs, lows, closes)
                
                # Phân tích MA theo phương pháp trung bình của các nến cuối
                # Dùng trung bình của 7 cây cuối cho MA7
                ma7_now = np.mean(closes[-7:])
                # Dùng trung bình của 25 cây cuối cho MA25
                ma25_now = np.mean(closes[-25:])

                position = db.get_position(symbol)

                if position is None:
                    print(f"[{symbol}] Giá: {last_price:.5f} | MA7: {ma7_now:.5f} | MA25: {ma25_now:.5f} | RSI: {rsi_now:.2f} | Vol: {current_vol:.2f} | ADX: {adx_now:.2f}")
                    signal = detect_entry(closes, volumes, rsi_now, adx_now)
                    if signal:
                        position_type = signal
                        db.insert_position(symbol, last_price, position_type, "", last_price)
                        send_telegram_message(f"[{symbol}] 🚀 Entry {position_type} tại {last_price:.5f}")
                        place_trade(symbol, position_type)

                else:
                    id, symbol_db, entry_price, position_type, strength, max_price, *rest = position
                    entry_price = float(entry_price)
                    max_price = float(max_price)

                    profit = (last_price - entry_price) / entry_price if position_type == "LONG" else (entry_price - last_price) / entry_price
                    drawdown = (max_price - last_price) / max_price if position_type == "LONG" else (last_price - max_price) / max_price
                    # Tính profit_from_peak (lãi bị mất đi từ max_price so với entry)
                    profit_from_peak = (max_price - last_price) / entry_price if position_type == "LONG" else (last_price - max_price) / entry_price

                    print(f"DEBUG: {symbol} - Type: {position_type} - Last: {last_price:.5f} - Max: {max_price:.5f} - Profit {profit*100:.2f}%")

                    trailing_distance = get_trailing_distance(profit)
                    mdd_threshold = get_mdd_threshold(profit)

                    if position_type == "LONG" and last_price > max_price:
                        db.update_position(symbol, {"max_price": last_price})
                        print(f"[{symbol}] 🟢 LONG cập nhật max_price: {last_price:.5f}")
                    
                    elif position_type == "SHORT" and last_price < max_price:
                        db.update_position(symbol, {"max_price": last_price})
                        print(f"[{symbol}] 🔴 SHORT cập nhật max_price: {last_price:.5f}")

                    print(f"[{symbol}] Profit: {profit*100:.2f}%, Drawdown: {drawdown*100:.2f}% (Trailing: {trailing_distance*100:.2f}%, MDD: {mdd_threshold*100:.2f}%)")

                    # Trước tiên, nếu drawdown vượt MDD (dù profit âm hay dương), cắt lỗ ngay.
                    if drawdown >= mdd_threshold:
                        send_telegram_message(f"[{symbol}] ❌ MDD Cut triggered - Profit {profit*100:.2f}%")
                        place_trade(symbol, "FLAT")
                        db.delete_position(symbol)
                        print_db_positions()
                        continue
                    
                    if profit > 0 and drawdown >= trailing_distance:
                        send_telegram_message(f"[{symbol}] 🎯 Trailing Stop triggered - Profit {profit*100:.2f}%")
                        place_trade(symbol, "FLAT")
                        db.delete_position(symbol)

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(10)

# =========================
# Start
# =========================
if __name__ == "__main__":
    main_loop()
