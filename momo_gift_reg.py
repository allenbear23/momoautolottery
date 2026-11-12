#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 雙11超狂購物節 - 11/10-11/11 滿額送好禮 (https://momo.dm/myZiyn) 搶登記腳本
開搶時間: 2026-11-13 12:00:00 (Asia/Taipei)
目標品項: 【PASEO】厚韌掛抽紙 (D26111100007, 滿$1,111, 1,000名)
"""

import sys
import os
import time
import json
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse
import concurrent.futures
from datetime import datetime, timezone, timedelta

TZ_TAIPEI = timezone(timedelta(hours=8))

EDM_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?npn=1vEK6yXFtvjC&n=1"
API_URL = "https://event.momoshop.com.tw/promoMechReg.PROMO"

M_PROMO_NO = "M26111100083"
TARGET_DT_PROMO_NO = "D26111100007"
TARGET_GIFT_CODE = "gift1"
TARGET_GIFT_NAME = "【PASEO】厚韌掛抽紙"
TARGET_OPEN_TIME = datetime(2026, 11, 13, 12, 0, 0, tzinfo=TZ_TAIPEI)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": EDM_URL,
    "Content-Type": "application/json;charset=utf-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

RETURN_MESSAGES = {
    "INS": "🎉 登記成功！",
    "A": "ℹ️ 您已登記過此活動",
    "A_EX": "ℹ️ 您已登記過其他 5 選 1 活動",
    "EA": "❌ 不符合登記資格 (未達滿額門檻)",
    "FULL": "⚡ 登記已額滿",
    "D": "⏳ 非活動時間 / 尚未開搶",
    "W": "⏳ 非指定星期 / 尚未開搶",
    "L": "⚠️ 請重新登入會員 (Cookie 已失效)",
    "E_CN": "⚠️ 請重新登入會員 (E_CN)",
    "E_M": "⏳ 活動尚未開放 (E_M)",
    "E_DTC": "⏳ 活動尚未開放 (E_DTC)",
    "E_MC": "⏳ 活動尚未開放 (E_MC)",
    "BUSY": "⚠️ 網頁連線過多，請稍後再試",
    "Processing": "⚠️ 點擊次數過多，請稍後再試",
    "ERR": "⚠️ 系統繁忙，請稍後再試",
}


def get_user_display_name(cookie: str, default_idx: int = 1) -> str:
    m = re.search(r"loginUser=([^;]+)", cookie)
    if m:
        try:
            val = m.group(1).replace("+", " ")
            name = urllib.parse.unquote(val).strip()
            if name:
                return f"帳號 {default_idx} ({name})"
        except Exception:
            pass
    return f"帳號 {default_idx}"


def load_all_cookies(cookie_arg: str = None) -> list:
    raw = ""
    if cookie_arg:
        raw = cookie_arg
    else:
        cookie_file = os.path.join(os.path.dirname(__file__), "cookie.txt")
        if os.path.exists(cookie_file):
            with open(cookie_file, "r", encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = os.getenv("MOMO_COOKIE", "")

    cookies = []
    blocks = raw.split("---") if "---" in raw else raw.splitlines()
    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        if any(k in clean for k in ("LOGINSESSION", "st=", "_atrk", "isEN")):
            cookies.append(clean)
    return cookies


def send_reg_request(cookie: str, m_promo_no: str = M_PROMO_NO, dt_promo_no: str = TARGET_DT_PROMO_NO, gift_code: str = TARGET_GIFT_CODE) -> dict:
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie.strip()
    payload = {
        "m_promo_no": m_promo_no,
        "dt_promo_no": dt_promo_no,
        "gift_code": gift_code,
    }

    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.post(
            API_URL,
            json=payload,
            headers=hdrs,
            impersonate="chrome124",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"returnMsg": f"HTTP_{resp.status_code}", "raw": resp.text[:200]}
    except ImportError:
        pass
    except Exception as e:
        return {"returnMsg": "ERR", "error": str(e)}

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(API_URL, data=body, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"returnMsg": f"HTTP_{e.code}", "error": str(e)}
    except Exception as e:
        return {"returnMsg": "ERR", "error": str(e)}


def grab_for_account(idx: int, cookie: str, allow_retry: bool = True) -> str:
    name = get_user_display_name(cookie, idx)
    retryable = {"D", "W", "E_DTC", "E_MC", "BUSY", "Processing", "ERR"}
    max_attempts = 6 if allow_retry else 1

    last_code = "ERR"
    for attempt in range(1, max_attempts + 1):
        res = send_reg_request(cookie)
        code = res.get("returnMsg", "ERR")
        last_code = code
        msg = RETURN_MESSAGES.get(code, str(res))
        print(f"[{datetime.now(TZ_TAIPEI).strftime('%H:%M:%S.%f')[:-3]}] [{name}] (第{attempt}次) {code}: {msg}")

        if code not in retryable or attempt == max_attempts:
            return f"{name}: {msg} ({code})"

        # 若尚未到點或系統短暫忙線，快速間隔重試
        time.sleep(0.4)

    return f"{name}: {RETURN_MESSAGES.get(last_code, last_code)} ({last_code})"


def wait_until_open(target_dt: datetime):
    while True:
        now = datetime.now(TZ_TAIPEI)
        diff = (target_dt - now).total_seconds()
        if diff <= 0.3:
            break
        if diff > 60:
            print(f"[{now.strftime('%H:%M:%S')}] 距離開搶 ({target_dt.strftime('%Y-%m-%d %H:%M:%S')}) 還有 {int(diff)} 秒...")
            time.sleep(min(diff - 30, 60))
        elif diff > 5:
            time.sleep(diff - 3)
        else:
            time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description="Momo 11/13 12:00 滿額送好禮搶登記腳本")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串")
    parser.add_argument("--now", action="store_true", help="立即執行不等待開搶時間")
    parser.add_argument("--no-retry", action="store_true", help="不重試")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。")
        sys.exit(1)

    now = datetime.now(TZ_TAIPEI)
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] 🎯 目標: {TARGET_GIFT_NAME} ({TARGET_DT_PROMO_NO}) | 帳號數: {len(cookies)}")

    if not args.now and now < TARGET_OPEN_TIME:
        wait_until_open(TARGET_OPEN_TIME)

    print(f"[{datetime.now(TZ_TAIPEI).strftime('%H:%M:%S.%f')[:-3]}] 🚀 開始並行搶登記！")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cookies)) as executor:
        futures = [
            executor.submit(grab_for_account, idx, c, not args.no_retry)
            for idx, c in enumerate(cookies, 1)
        ]
        for fut in futures:
            results.append(fut.result())

    print("\n=== 搶登記結果彙整 ===")
    for line in results:
        print(line)

    try:
        from notifier import send_bark
        send_bark(f"momo 滿額好禮 ({TARGET_GIFT_NAME})", "\n".join(results))
    except Exception as e:
        print(f"推播異常: {e}")


if __name__ == "__main__":
    main()
