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
        return closes, volumes  # ✅ luôn trả 2 list
    except Exception as e:
        print(f"Fetch Error {symbol}: {e}")
        return None, None

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

def calculate_ma(closes, period):
    closes = np.array(closes)
    ma = np.convolve(closes, np.ones(period)/period, mode='valid')
    return float(ma[-1])

def is_trend_clean(ma7, ma25, lookback=5):
    recent_ma7 = ma7[-lookback:]
    recent_ma25 = ma25[-lookback:]
    cross_count = 0
    for i in range(1, lookback):
        if (recent_ma7[i-1] - recent_ma25[i-1]) * (recent_ma7[i] - recent_ma25[i]) < 0:
            cross_count += 1
    return cross_count == 0

def detect_entry(closes, volumes, rsi_now):
    """
    Điều kiện entry mở rộng cho cả LONG và SHORT:
      - Số nến tối thiểu: >= 30
      - Tính MA7 (trung bình của 7 cây nến cuối) và MA7_prev (7 cây liền trước)
      - Tính MA25 (trung bình của 25 cây nến cuối) và MA25_prev (25 cây liền trước)
      - Với LONG: MA7 phải tăng, MA25 không giảm mạnh (delta > -0.001)
      - Với SHORT: MA7 phải giảm, MA25 không tăng mạnh (delta < 0.001)
      - Volume của nến cuối > 1.2 lần trung bình của 20 nến trước đó
      - RSI của cây nến cuối > 50 cho LONG, < 50 cho SHORT
    Sau đó phân loại tín hiệu:
      - Nếu volume rất cao (>2x trung bình) và RSI > 65 (cho LONG) hoặc RSI < 35 (cho SHORT): "BREAKOUT"
      - Nếu volume cao (>1.5x trung bình) và RSI > 55 (cho LONG) hoặc RSI < 45 (cho SHORT): "STRONG"
      - Còn lại: "NORMAL"
    """
    if len(closes) < 30:
        return None

    # Tính trung bình MA7: dùng 7 cây nến cuối
    ma7_now = np.mean(closes[-7:])
    ma7_prev = np.mean(closes[-8:-1])

    # Tính trung bình MA25: dùng 25 cây nến cuối
    ma25_now = np.mean(closes[-25:])
    ma25_prev = np.mean(closes[-26:-1])
    # Delta của MA25 để xác định xu hướng
    ma25_delta = (ma25_now - ma25_prev) / ma25_prev if ma25_prev != 0 else 0

    # Đối với LONG: cần MA7 tăng
    is_long_signal = ma7_now > ma7_prev and (ma25_delta > -0.001)
    # Đối với SHORT: cần MA7 giảm và MA25 không tăng mạnh
    is_short_signal = ma7_now < ma7_prev and (ma25_delta < 0.001)

    volume_now = volumes[-1]
    volume_avg = np.mean(volumes[-21:-1])
    volume_ok = volume_now > 1.2 * volume_avg

    # Kiểm tra tín hiệu LONG
    if is_long_signal and volume_ok and rsi_now > 50:
        if volume_now > 2.0 * volume_avg and rsi_now > 65:
            return ("LONG", "BREAKOUT")
        elif volume_now > 1.5 * volume_avg and rsi_now > 55:
            return ("LONG", "STRONG")
        else:
            return ("LONG", "NORMAL")
    # Kiểm tra tín hiệu SHORT
    elif is_short_signal and volume_ok and rsi_now < 50:
        if volume_now > 2.0 * volume_avg and rsi_now < 35:
            return ("SHORT", "BREAKOUT")
        elif volume_now > 1.5 * volume_avg and rsi_now < 45:
            return ("SHORT", "STRONG")
        else:
            return ("SHORT", "NORMAL")
    
    return None

def get_trailing_distance(strength, profit):
    """
    Cấu hình trailing stop an toàn theo loại xu hướng:
      - BREAKOUT: trailing 0.4–0.8%
      - STRONG: trailing 0.6–1.2%
      - NORMAL: trailing 0.5–1.1%
    Các con số được chọn để chốt lời sớm trong breakout (vì rủi ro đảo chiều cao)
    và cho phép trend mạnh giữ lệnh lâu hơn.
    """
    if strength == "BREAKOUT":
        if profit < 0.02:
            return 0.004  # 0.4%
        elif profit < 0.05:
            return 0.006  # 0.6%
        else:
            return 0.008  # 0.8%
    elif strength == "STRONG":
        if profit < 0.02:
            return 0.006  # 0.6%
        elif profit < 0.05:
            return 0.009  # 0.9%
        else:
            return 0.012  # 1.2%
    else:  # NORMAL
        if profit < 0.02:
            return 0.005  # 0.5%
        elif profit < 0.05:
            return 0.008  # 0.8%
        else:
            return 0.011  # 1.1%
        
def get_mdd_threshold(strength):
    """
    MDD (Maximum Drawdown) được tính từ max_price so với giá hiện tại.
    Cấu hình an toàn (cho mục tiêu MDD < 10% tổng vốn) cho mỗi kiểu giao dịch:
      - BREAKOUT: 2%
      - STRONG: 1.7%
      - NORMAL: 1.2%
    """
    if strength == "BREAKOUT":
        return 0.02
    elif strength == "STRONG":
        return 0.017
    else:
        return 0.012

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
            # if not is_in_trading_time():
            #     print("⏳ Ngoài giờ auto-trade, bot standby...")
            #     time.sleep(SCAN_INTERVAL)
            #     continue

            for symbol in COINS:
                closes, volumes = fetch_klines(symbol)
                if closes is None or volumes is None or len(closes) < 100:
                    continue

                # Lấy thông tin giá cuối và khối lượng hiện tại
                last_price = float(closes[-1])
                prev_price = float(closes[-2])
                current_vol = float(volumes[-1])
                avg_vol = np.mean(volumes[-21:-1])

                 # Tính RSI của cây nến cuối (đã ép float trong hàm)
                rsi_now = calculate_rsi(closes)
                
                # Phân tích MA theo phương pháp trung bình của các nến cuối
                # Dùng trung bình của 7 cây cuối cho MA7
                ma7_now = np.mean(closes[-7:])
                ma7_prev = np.mean(closes[-8:-1])
                # Dùng trung bình của 25 cây cuối cho MA25
                ma25_now = np.mean(closes[-25:])
                ma25_prev = np.mean(closes[-26:-1])

                position = db.get_position(symbol)

                if position is None:
                    print(f"[{symbol}] Giá: {last_price:.5f} | MA7: {ma7_now:.5f} | MA25: {ma25_now:.5f} | RSI: {rsi_now:.2f} | Vol: {current_vol:.2f}")
                    signal = detect_entry(closes, volumes, rsi_now)
                    if signal:
                        position_type, mode = signal
                        db.insert_position(symbol, last_price, position_type, mode, last_price)
                        send_telegram_message(f"[{symbol}] 🚀 Entry {mode} {position_type} tại {last_price:.5f}")
                        place_trade(symbol, position_type)

                else:
                    id, symbol_db, entry_price, position_type, strength, max_price, *rest = position
                    entry_price = float(entry_price)
                    max_price = float(max_price)

                    profit = (last_price - entry_price) / entry_price if position_type == "LONG" else (entry_price - last_price) / entry_price
                    drawdown = (max_price - last_price) / max_price if position_type == "LONG" else (last_price - max_price) / max_price

                    print(f"DEBUG: {symbol} - Type: {position_type} - Last: {last_price:.5f} - Max: {max_price:.5f} - Profit {profit*100:.2f}%")

                    trailing_distance = get_trailing_distance(strength, profit)
                    mdd_threshold = get_mdd_threshold(strength)

                    if position_type == "LONG" and last_price > max_price:
                        db.update_position(symbol, {"max_price": last_price})
                        print(f"[{symbol}] 🟢 LONG cập nhật max_price: {last_price:.5f}")
                        max_price = last_price
                    
                    elif position_type == "SHORT" and last_price < max_price:
                        db.update_position(symbol, {"max_price": last_price})
                        print(f"[{symbol}] 🔴 SHORT cập nhật max_price: {last_price:.5f}")
                        max_price = last_price

                    print(f"[{symbol}] Profit: {profit*100:.2f}%, Drawdown: {drawdown*100:.2f}% (Trailing: {trailing_distance*100:.2f}%, MDD: {mdd_threshold*100:.2f}%)")

                    # Trước tiên, nếu drawdown vượt MDD (dù profit âm hay dương), cắt lỗ ngay.
                    if drawdown >= mdd_threshold:
                        send_telegram_message(f"[{symbol}] ❌ MDD Cut triggered - Profit {profit*100:.2f}%")
                        place_trade(symbol, "FLAT")
                        db.delete_position(symbol)
                        print_db_positions()
                        continue
                    
                    if position_type == "LONG":
                        if profit > 0 and drawdown >= trailing_distance and last_price > entry_price:
                            # Kích hoạt trailing stop cho LONG
                            send_telegram_message(f"[{symbol}] 🎯 Trailing Stop triggered - Profit {profit*100:.2f}%")
                            place_trade(symbol, "FLAT")
                            db.delete_position(symbol)
                            continue
                    elif position_type == "SHORT":
                        if profit > 0 and drawdown >= trailing_distance and last_price < entry_price:
                            # Kích hoạt trailing stop cho SHORT, vì lợi nhuận tăng nghĩa là entry_price > last_price
                            send_telegram_message(f"[{symbol}] 🎯 Trailing Stop triggered (SHORT) - Profit {profit*100:.2f}%")
                            place_trade(symbol, "FLAT")
                            db.delete_position(symbol)
                            continue

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(10)

# =========================
# Start
# =========================
if __name__ == "__main__":
    main_loop()
