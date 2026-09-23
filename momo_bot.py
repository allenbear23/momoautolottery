#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 好運轉轉樂 (秋日購物節 9/23-9/30) 自動定時抽獎腳本
支援全自動解析 spinRotateConfig.js、十個時段智能對應與 Bark 推播
"""

import sys
import os
import time
import json
import re
import argparse
import urllib.request
import urllib.error
from datetime import datetime

DEFAULT_EVENT_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O7Cj3Xyvxjm&n=1"
DEFAULT_M_PROMO_NO = "U96092300001"

SLOT_HOURS = [10, 11, 12, 14, 15, 16, 17, 18, 20, 21]
SCHEDULE_TIMES = [f"{h:02d}:00" for h in SLOT_HOURS]

DEFAULT_DT_PROMO_ARRAY = [
    "D96092300001",  # 10:00
    "D96092300002",  # 11:00
    "D96092300003",  # 12:00
    "D96092300004",  # 14:00
    "D96092300005",  # 15:00
    "D96092300006",  # 16:00
    "D96092300007",  # 17:00
    "D96092300008",  # 18:00
    "D96092300009",  # 20:00
    "D96092300010",  # 21:00
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoshop/12.5.0"
}

RETURN_MESSAGES = {
    'OK': '成功',
    'INS': '恭喜獲得獎項！',
    'A': '您已經參加過本時段了！',
    'A_EX': '您已經參加過本時段了！',
    'FULL': '名額已經額滿！',
    'L': '請重新登入會員 (Cookie 已過期或無效)',
    'D': '請於活動時間內參加活動',
    'NOT_USED': '很抱歉，活動暫不開放',
    'NOT_APP': '請在 momo APP 參加活動',
    'ERR': '系統繁忙，請稍後再試'
}

GIFT_NAMES = {
    "mo_388": "$388 mo點",
    "mo_3": "$3 mo點",
    "mo_1": "$1 mo點",
    "coupon_1": "3C商品$700券",
    "coupon_2": "潮流服飾85折券",
    "coupon_3": "內著商品85折券",
    "coupon_4": "專櫃美妝81折券",
    "coupon_5": "家用清潔88折券",
    "coupon_6": "保健商品85折券",
    "coupon_7": "家居商品$500券"
}

ACTIVE_CONFIG = {
    "domain": "https://event.momoshop.com.tw",
    "url": DEFAULT_EVENT_URL,
    "m_promo_no": DEFAULT_M_PROMO_NO,
    "dt_promo_no_array": list(DEFAULT_DT_PROMO_ARRAY),
    "title": "好運轉轉樂"
}


def fetch_page(url: str, timeout: int = 8) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def fetch_promo_config(edm_url: str):
    """
    從 EDM 頁面解析 spinRotateConfig.js
    """
    try:
        html = fetch_page(edm_url, timeout=10)
        js_match = re.search(r'src=[\"\']([^\"\']*spinRotateConfig\.js[^\"\']*)[\"\']', html)
        if not js_match:
            return None

        js_url = js_match.group(1)
        if js_url.startswith("//"):
            js_url = "https:" + js_url

        js_content = fetch_page(js_url, timeout=10)
        m = re.search(r'mPromoNo\s*:\s*[\"\']([^\"\']+)[\"\']', js_content)
        t = re.search(r'title\s*:\s*[\"\']([^\"\']+)[\"\']', js_content)
        dom = re.search(r'spinEventDomain\s*:\s*[\"\']([^\"\']+)[\"\']', js_content)
        dts = re.findall(r'[\"\'](D\d+)[\"\']', js_content)

        m_no = m.group(1) if m else DEFAULT_M_PROMO_NO
        title = t.group(1) if t else "好運轉轉樂"
        domain = dom.group(1) if dom else "https://event.momoshop.com.tw"
        dt_list = dts if dts else list(DEFAULT_DT_PROMO_ARRAY)

        # 解析獎項定義
        gifts = re.findall(r'giftCode\s*:\s*[\"\']([^\"\']+)[\"\'].*?giftContent\s*:\s*[\"\']([^\"\']+)[\"\']', js_content, re.DOTALL)
        for code, name in gifts:
            GIFT_NAMES[code] = name

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 配置解析成功: 活動='{title}', mPromoNo={m_no}, 時段代碼數={len(dt_list)}")
        return {
            "domain": domain,
            "url": edm_url,
            "m_promo_no": m_no,
            "dt_promo_no_array": dt_list,
            "title": title
        }
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 解析配置異常: {e}")
        return None


def get_current_slot_info():
    """
    根據當前時間取得對應的時段索引與 dt_promo_no
    若在 58~59 分，則提前鎖定下一個時段
    """
    now = datetime.now()
    cur_hour = now.hour
    cur_min = now.minute

    # 若接近整點（>=58分），預先視為下一小時
    target_hour = cur_hour
    if cur_min >= 58:
        target_hour = cur_hour + 1

    # 匹配最接近的開放時段
    slot_index = 0
    if target_hour in SLOT_HOURS:
        slot_index = SLOT_HOURS.index(target_hour)
    else:
        # 尋找未來最近的時段或預設當天最新
        found = False
        for idx, h in enumerate(SLOT_HOURS):
            if target_hour <= h:
                slot_index = idx
                found = True
                break
        if not found:
            slot_index = len(SLOT_HOURS) - 1

    dt_list = ACTIVE_CONFIG["dt_promo_no_array"]
    dt_promo = dt_list[slot_index] if slot_index < len(dt_list) else dt_list[0]
    slot_time_str = f"{SLOT_HOURS[slot_index]:02d}:00"
    return slot_index, slot_time_str, dt_promo


def get_headers(cookie: str):
    return {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": ACTIVE_CONFIG["url"],
        "Cookie": cookie.strip()
    }


def send_api_request(endpoint: str, payload: dict, cookie: str):
    url = f"{ACTIVE_CONFIG['domain']}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=get_headers(cookie), method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        return {"returnMsg": f"HTTP_ERROR_{e.code}"}
    except Exception as e:
        return {"returnMsg": f"ERROR_{str(e)}"}


def do_query(cookie: str):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    dt_str = ",".join(ACTIVE_CONFIG["dt_promo_no_array"])
    payload = {
        "m_promo_no": ACTIVE_CONFIG["m_promo_no"],
        "dt_promo_no": dt_str,
        "qry_type": "1003"
    }

    res = send_api_request("promoMechQry.PROMO", payload, cookie)
    if res.get("returnMsg") == "L":
        print(f"[{now_str}] 查詢失敗: 會員登入憑證失效 (Cookie 已逾期)")
        return None

    if res.get("returnMsg") != "OK":
        print(f"[{now_str}] 查詢回應: {res}")
        return None

    gift_codes = res.get("gift_code", [])
    insert_dates = res.get("insert_date", [])
    records = list(zip(insert_dates, gift_codes))

    total_mo = 0
    coupons = []
    for _, code in records:
        if code.startswith("mo_"):
            try:
                total_mo += int(code.split("_")[1])
            except Exception:
                pass
        else:
            coupons.append(GIFT_NAMES.get(code, code))

    print(f"[{now_str}] 【{ACTIVE_CONFIG['title']}】活動紀錄:")
    print(f"  • 今日累計轉次數: {len(records)} 次")
    print(f"  • 累計獲得 mo 點: {total_mo} 元")
    if coupons:
        print(f"  • 獲得折價券: {', '.join(coupons)}")
    print("  • 詳細紀錄:")
    if not records:
        print("    (今日尚無轉輪盤紀錄)")
    for d, c in records:
        print(f"    - {d}: {GIFT_NAMES.get(c, c)}")

    return {
        "total_draws": len(records),
        "total_mo": total_mo,
        "coupons": coupons,
        "records": records
    }


def wait_until_slot_start(max_wait_seconds: int = 150):
    """
    若目前時間接近目標時段整點（例如 58 或 59 分），自動倒數至整點 :00:01 再發送抽獎請求
    """
    now = datetime.now()
    for th in SLOT_HOURS:
        target_time = now.replace(hour=th, minute=0, second=1, microsecond=0)
        diff = (target_time - now).total_seconds()
        if 0 < diff <= max_wait_seconds:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 提早啟動，等待 {th:02d}:00:01 開放，倒數 {diff:.1f} 秒...")
            time.sleep(diff)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 整點已到，立即開始轉輪盤！")
            return


def do_draw(cookie: str, dt_promo: str):
    payload = {
        "m_promo_no": ACTIVE_CONFIG["m_promo_no"],
        "dt_promo_no": dt_promo,
        "gift_code": ""
    }
    res = send_api_request("promoMechReg.PROMO", payload, cookie)
    return res


def run_session_draws(cookie: str, silent_if_limit: bool = False, wait_slot: bool = True):
    if wait_slot:
        wait_until_slot_start()

    slot_index, slot_time_str, dt_promo = get_current_slot_info()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] 目標時段: {slot_time_str} (代碼: {dt_promo})，發送轉輪盤請求...")

    res = do_draw(cookie, dt_promo)
    return_msg = res.get("returnMsg", "")
    prize_code = res.get("prize", "")
    msg_text = RETURN_MESSAGES.get(return_msg, return_msg)

    draw_records = []
    print(f"[{now_str}] 回應狀態: {return_msg} ({msg_text})")

    if return_msg == "INS":
        gift_name = GIFT_NAMES.get(prize_code, prize_code)
        draw_records.append(f"🎉 抽中：{gift_name}")
        print(f"[{now_str}] 轉盤中獎: {gift_name}")
    elif return_msg in ("A", "A_EX"):
        draw_records.append("本時段已轉過輪盤")
    elif return_msg == "FULL":
        draw_records.append("本時段名額已額滿 (5,000名)")
    elif return_msg == "L":
        draw_records.append("⚠️ Cookie 已失效，請重新登入更新")
    elif return_msg in ("D", "NOT_USED"):
        draw_records.append("活動尚未開放或非開放時段")
    else:
        draw_records.append(f"回應: {msg_text}")

    if silent_if_limit and (draw_records == ["本時段已轉過輪盤"] or draw_records == ["活動尚未開放或非開放時段"]):
        print(f"非活動時段或已抽過 ({draw_records[0]})，略過推播。")
        return

    # 查詢今日統計
    time.sleep(1)
    summary = do_query(cookie)
    summary_lines = []
    if summary:
        summary_lines.append(f"\n💰 今日累計 mo 點: {summary['total_mo']} 元")
        summary_lines.append(f"🎯 今日轉盤次數: {summary['total_draws']} 次")
        if summary["coupons"]:
            summary_lines.append(f"🎟️ 已得折價券: {len(summary['coupons'])} 張")

    # 發送 Bark 通知
    try:
        from notifier import send_bark
        body_text = f"【時段 {slot_time_str}】\n" + "\n".join(draw_records) + ("\n" + "\n".join(summary_lines) if summary_lines else "")
        send_bark(f"momo 轉轉樂結果 ({slot_time_str})", body_text.strip())
    except Exception as e:
        print(f"發送推播通知異常: {e}")


def run_scheduler(cookie: str, event_url: str):
    print(f"定時抽獎服務已啟動。每日開放時段: {', '.join(SCHEDULE_TIMES)}")
    last_triggered_date_hour = ""

    while True:
        now = datetime.now()
        current_hm = now.strftime("%H:%M")
        current_dh = now.strftime("%Y-%m-%d_%H")

        if current_hm in SCHEDULE_TIMES and current_dh != last_triggered_date_hour:
            last_triggered_date_hour = current_dh
            run_session_draws(cookie)
            try:
                from momo_checkin import run_daily_checkin
                run_daily_checkin(cookie)
            except Exception as e:
                print(f"執行天天簽到異常: {e}")

        time.sleep(20)


def load_cookie(cookie_arg: str = None) -> str:
    if cookie_arg:
        return cookie_arg.strip()

    cookie_file = os.path.join(os.path.dirname(__file__), "cookie.txt")
    if os.path.exists(cookie_file):
        with open(cookie_file, "r", encoding="utf-8") as f:
            c = f.read().strip()
            if c:
                return c

    env_c = os.getenv("MOMO_COOKIE")
    if env_c:
        return env_c.strip()

    return ""


def main():
    parser = argparse.ArgumentParser(description="Momo 好運轉轉樂自動抽獎腳本")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串")
    parser.add_argument("--url", help="活動 EDM 網址 (預設秋日購物節好運轉轉樂)")
    parser.add_argument("--now", action="store_true", help="立即執行一次當前時段轉輪盤流程")
    parser.add_argument("--query", action="store_true", help="查詢當前轉盤中獎紀錄與 mo 點")
    parser.add_argument("--schedule", action="store_true", help="啟動十個時段的定時輪詢")
    parser.add_argument("--silent-if-limit", action="store_true", help="若本時段已無額度或非開放時段則略過推播")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookie = load_cookie(args.cookie)
    if not cookie:
        print("錯誤: 未找到 Cookie。請將 Cookie 寫入 cookie.txt 或使用 --cookie。")
        sys.exit(1)

    edm_url = args.url or DEFAULT_EVENT_URL
    parsed = fetch_promo_config(edm_url)
    if parsed:
        ACTIVE_CONFIG.update(parsed)

    if args.query:
        do_query(cookie)
    elif args.now:
        run_session_draws(cookie, silent_if_limit=args.silent_if_limit)
    else:
        run_scheduler(cookie, edm_url)


if __name__ == "__main__":
    main()
