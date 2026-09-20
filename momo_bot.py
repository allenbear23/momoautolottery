#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 桃金日-好運抽抽樂 自動定時抽獎腳本
"""

import sys
import os
import time
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime

API_URL = "https://event.momoshop.com.tw/game/momoLottery.PROMO"
M_PROMO_NO = "U96091900001"
DT_PROMO_NO = "D96091900001"

RETURN_MESSAGES = {
    'OK': '成功',
    'D': '請於活動時間內參加活動',
    'W': '請於指定星期參加活動',
    'WP': '競標金額錯誤',
    'L': '請重新登入會員 (Cookie 已過期或無效)',
    'A': '已超過本時段抽獎次數上限！',
    'A_EX': '已超過本時段抽獎次數上限！',
    'EA': '已超過本時段抽獎次數上限！',
    'FULL': '名額已經額滿!!',
    'NOT_USED': '很抱歉，活動暫不開放',
    'NOT_APP': '請在momo APP參加活動',
    'NOT_WEB': '請在momo網頁版參加活動',
    'NOT_NC': '您非活動期間新客',
    'NOT_WFB': '您非活動期間首購',
    'NOT_APPFB': '您非活動期間APP首購',
    'NO_PT': '點數不足',
    'INS': '登記成功，感謝您對本活動的支持',
    'exchanged': '您今日已兌獎，恕無法再參加，請於明日再來~',
    'shared': '今日已分享該活動！',
    'linkedFriend': '已幫好友獲得金額1元！',
    'linked': '已有其他好友幫忙分享',
    'notshared': '此連結已過期，需請好友重新分享今日連結',
    'E_LINK': '不能分享給自己',
    'ERR': '很抱歉，目前系統繁忙，請稍後再試'
}

GIFT_NAMES = {
    "peach": "桃",
    "gold": "金",
    "day": "日",
    "mo_1": "1元",
    "mo_2": "2元",
    "mo_5": "5元",
    "mo_12": "12元",
    "mo_222": "222元"
}

SCHEDULE_TIMES = ["09:00", "13:00", "16:00", "19:00", "21:00"]


def get_headers(cookie: str):
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O8dV4oaCUPZ&n=1",
        "Cookie": cookie.strip()
    }


def send_request(action: str, cookie: str):
    payload = {
        "doAction": action,
        "m_promo_no": M_PROMO_NO,
        "dt_promo_no": DT_PROMO_NO
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers=get_headers(cookie), method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        return {"status": f"HTTP_ERROR_{e.code}"}
    except Exception as e:
        return {"status": f"ERROR_{str(e)}"}


def do_query(cookie: str):
    res = send_request("qry", cookie)
    status = res.get("status")
    msg = RETURN_MESSAGES.get(status, status)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 查詢結果: 狀態={status} ({msg})")
    if status == "OK" and "data" in res:
        data = res["data"]
        insert_dates = data.get("insert_date", [])
        gift_codes = data.get("gift_code", [])
        print(f"中獎紀錄筆數: {len(insert_dates)}")
        for date_str, code in zip(insert_dates, gift_codes):
            name = GIFT_NAMES.get(code, code)
            print(f"  - {date_str}: {name}")
    return res


def do_draw(cookie: str):
    res = send_request("lottery", cookie)
    status = res.get("status")
    msg = RETURN_MESSAGES.get(status, status)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] 抽獎結果: 狀態={status} ({msg})")

    if status == "OK":
        prize = res.get("result", {}).get("prize", {})
        gift_code = prize.get("giftCode")
        gift_name = GIFT_NAMES.get(gift_code, gift_code)
        print(f"[{now_str}] 抽中: {gift_name}")
        if res.get("prizeStatus") == "PRIZE":
            total = res.get("total", "")
            print(f"[{now_str}] 集滿桃金日！獲得 mo 點: {total} 元")
    return res


def run_session_draws(cookie: str, max_draws: int = 2):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行本時段抽獎...")
    for i in range(max_draws):
        res = do_draw(cookie)
        status = res.get("status")
        if status in ("A", "A_EX", "EA"):
            print("已達本時段上限，停止抽獎。")
            break
        if status == "L":
            print("登入憑證失效，請更新 Cookie。")
            break
        if i < max_draws - 1:
            time.sleep(3)


def run_scheduler(cookie: str):
    print(f"定時抽獎服務已啟動。預定觸發時段: {', '.join(SCHEDULE_TIMES)}")
    last_triggered_date_hour = ""

    while True:
        now = datetime.now()
        current_hm = now.strftime("%H:%M")
        current_dh = now.strftime("%Y-%m-%d_%H")

        if current_hm in SCHEDULE_TIMES and current_dh != last_triggered_date_hour:
            last_triggered_date_hour = current_dh
            run_session_draws(cookie, max_draws=2)

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
    parser = argparse.ArgumentParser(description="Momo 桃金日抽抽樂自動腳本")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串")
    parser.add_argument("--now", action="store_true", help="立即執行一次抽獎流程 (最多抽 2 次)")
    parser.add_argument("--query", action="store_true", help="查詢當前抽獎與點數紀錄")
    parser.add_argument("--schedule", action="store_true", help="啟動定時輪詢 (09:00, 13:00, 16:00, 19:00, 21:00)")
    args = parser.parse_args()

    cookie = load_cookie(args.cookie)
    if not cookie:
        print("錯誤: 未找到 Cookie。請透過 --cookie 指定，或將 Cookie 寫入同目錄下的 cookie.txt。")
        sys.exit(1)

    if args.query:
        do_query(cookie)
    elif args.now:
        run_session_draws(cookie, max_draws=2)
    else:
        run_scheduler(cookie)


if __name__ == "__main__":
    main()
