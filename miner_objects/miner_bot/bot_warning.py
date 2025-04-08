import requests
import numpy as np
import time
import os
import json
from datetime import datetime

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
MAX_DRAWDOWN = config['settings']['global_drawdown_limit_percent'] / 100
TRAILING_TRIGGER = config['settings']['trailing_start_threshold_percent'] / 100
TRAILING_DISTANCE = config['settings']['trailing_distance_percent'] / 100
AUTO_TRADE_TIME = config.get('auto_trade_time', {})

# =========================
# Global Variables
# =========================
positions = {}  # { symbol: { entry_price, position_type, max_price, is_trailing_active } }

# =========================
# Functions
# =========================

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def place_trade(trade_pair, order_type, leverage):
    if TEST_MODE:
        print(f"[TEST MODE] Would place {order_type} order for {trade_pair} with leverage {leverage}")
        send_telegram_message(f"[TEST MODE] {order_type} {trade_pair} (Leverage {leverage}x)")
    else:
        try:
            payload = {
                "trade_pair": trade_pair,
                "order_type": order_type,
                "leverage": leverage,
                "api_key": API_KEY
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(API_URL, headers=headers, json=payload)
            print(f"Trade API Response: {response.status_code}")
        except Exception as e:
            print(f"Trade API Error: {e}")

def fetch_klines(symbol, interval='5m', limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        return data
    except Exception as e:
        print(f"Fetch Error {symbol}: {e}")
        return None

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

    return rsi

def calculate_ma(closes, period):
    closes = np.array(closes)
    ma = np.convolve(closes, np.ones(period)/period, mode='valid')
    return ma

def is_in_trading_time():
    now = datetime.utcnow()
    start = AUTO_TRADE_TIME.get("start")
    end = AUTO_TRADE_TIME.get("end")
    if not start or not end:
        return False
    current_time_str = now.strftime("%H:%M")
    return start <= current_time_str <= end

# =========================
# Main Loop
# =========================

def main_loop():
    print("🚀 Bot is running...")
    send_telegram_message("🚀 Bot đã khởi động thành công!")

    while True:
        try:

            for symbol in COINS:
                data = fetch_klines(symbol)
                if not data:
                    print(f"⚠️ Không fetch được dữ liệu {symbol}")
                    continue

                closes = [float(candle[4]) for candle in data]
                volumes = [float(candle[5]) for candle in data]
                last_price = closes[-1]

                ma25 = calculate_ma(closes, 25)[-1]
                ma99 = calculate_ma(closes, 99)[-1]
                rsi = calculate_rsi(closes)[-1]
                avg_vol = np.mean(volumes[-11:-1])
                current_vol = volumes[-1]

                print(f"[{symbol}] Giá: {last_price:.2f} | MA25: {ma25:.2f} | MA99: {ma99:.2f} | RSI: {rsi:.2f} | Vol: {current_vol:.2f} | AVG_Vol: {avg_vol:.2f}")

                # Nếu đã có vị thế
                if symbol in positions:
                    pos = positions[symbol]
                    entry = pos['entry_price']
                    pos_type = pos['position_type']

                    if pos_type == "LONG":
                        profit_percent = (last_price - entry) / entry
                        drawdown = (pos['max_price'] - last_price) / pos['max_price']
                    else:
                        profit_percent = (entry - last_price) / entry
                        drawdown = (last_price - pos['max_price']) / pos['max_price']

                    # Update max_price nếu cần
                    if pos_type == "LONG" and last_price > pos['max_price']:
                        pos['max_price'] = last_price
                        print(f"[{symbol}] LONG cập nhật max_price: {last_price:.2f}")

                    if pos_type == "SHORT" and last_price < pos['max_price']:
                        pos['max_price'] = last_price
                        print(f"[{symbol}] SHORT cập nhật max_price: {last_price:.2f}")

                    # Trailing Stop
                    if not pos['is_trailing_active'] and profit_percent >= TRAILING_TRIGGER:
                        pos['is_trailing_active'] = True
                        send_telegram_message(f"[{symbol}] Trailing stop kích hoạt! ✅\nGiá hiện tại: {last_price}")

                    if pos['is_trailing_active'] and drawdown >= TRAILING_DISTANCE:
                        send_telegram_message(f"[{symbol}] Chốt lời trailing! ✅\nGiá hiện tại: {last_price}")
                        place_trade(symbol, "FLAT", leverage=3)
                        del positions[symbol]
                        continue

                    # Stoploss
                    if profit_percent <= -MAX_DRAWDOWN:
                        send_telegram_message(f"[{symbol}] ❌ Stoploss! Giá hiện tại: {last_price}")
                        place_trade(symbol, "FLAT", leverage=3)
                        print(f"[{symbol}] ❌ Đã cắt lỗ")
                        del positions[symbol]
                        continue

                else:
                    # Phân tích vào lệnh nếu chưa có lệnh
                    if last_price > ma25 and last_price > ma99 and rsi > 50 and current_vol > avg_vol * 1.2:
                        send_telegram_message(f"[{symbol}] *Tín hiệu mạnh* Entry LONG!\nGiá: {last_price}")
                        place_trade(symbol, "LONG", leverage=3)
                        positions[symbol] = {
                            "entry_price": last_price,
                            "position_type": "LONG",
                            "max_price": last_price,
                            "is_trailing_active": False
                        }
                        send_telegram_message(f"[{symbol}] ✅ Mở lệnh LONG tại giá {last_price}")

                    elif last_price < ma25 and last_price < ma99 and rsi < 50 and current_vol > avg_vol * 1.2:
                        send_telegram_message(f"[{symbol}] *Tín hiệu mạnh* Entry SHORT!\nGiá: {last_price}")
                        place_trade(symbol, "SHORT", leverage=3)
                        positions[symbol] = {
                            "entry_price": last_price,
                            "position_type": "SHORT",
                            "max_price": last_price,
                            "is_trailing_active": False
                        }
                        send_telegram_message(f"[{symbol}] ✅ Mở lệnh SHORT tại giá {last_price}")

            time.sleep(SCAN_INTERVAL)
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main_loop()
