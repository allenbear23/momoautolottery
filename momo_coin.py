#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 幣 / Mo 點到期檢查與提醒模組
查詢會員中心即將到期之點數，並於到期當日發送推播通知
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime


def get_cookie(cookie_arg: str = None) -> str:
    if cookie_arg:
        return cookie_arg.strip()
    cookie_file = os.path.join(os.path.dirname(__file__), "cookie.txt")
    if os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                c = f.read().strip()
                if c:
                    return c
        except Exception:
            pass
    return os.getenv("MOMO_COOKIE", "").strip()


def query_coin_info(cookie: str, currency_type: str = "1") -> dict:
    """
    查詢 mo 幣 (currency_type="1") 或 mo 點 (currency_type="2")
    """
    url = "https://www.momoshop.com.tw/servlet/MemberCenterServ"
    payload = {
        "flag": 3156,
        "data": {
            "currencyType": str(currency_type)
        }
    }
    form_data = urllib.parse.urlencode({"data": json.dumps(payload)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=form_data,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie,
            "Referer": "https://www.momoshop.com.tw/mypage/MemberCenter.jsp?func=68",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(content)
            return data
    except Exception as e:
        return {"rtnCode": "ERROR", "rtnMsg": str(e)}


def check_and_notify_expiring_coins(cookie: str = None, force_notify: bool = False) -> dict:
    c = cookie or get_cookie()
    if not c:
        print("[mo幣檢查] 錯誤: 未提供 Cookie。")
        return {"status": "NO_COOKIE"}

    today_str = datetime.now().strftime("%Y/%m/%d")
    today_dash = datetime.now().strftime("%Y-%m-%d")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 檢查今日 ({today_str}) 即將到期之 mo 幣...")

    # 查詢 1: mo 幣, 2: mo 點
    expiring_items = []
    total_expiring = 0

    for ctype, name in [("1", "mo幣"), ("2", "mo點")]:
        res = query_coin_info(c, currency_type=ctype)
        rtn_code = str(res.get("rtnCode", ""))

        if rtn_code == "503":
            print(f"[mo幣檢查] 提示: 會員中心 Session 已逾期 (Session Timeout)。需要有效 Web Session 方可即時查詢。")
            return {"status": "SESSION_TIMEOUT", "message": "會員中心登入逾期"}

        if rtn_code == "200" or "expirationAmount" in res:
            exp_amount_raw = res.get("expirationAmount") or "0"
            exp_date = res.get("expirationDate") or ""
            balance = res.get("pointAmount") or "0"

            try:
                exp_amount = float(str(exp_amount_raw).replace(",", ""))
            except Exception:
                exp_amount = 0

            print(f"  • {name}目前餘額: {balance} | 即將到期: {exp_amount_raw} (到期日: {exp_date or '無'})")

            # 檢查是否為今日到期
            if exp_amount > 0 and (exp_date == today_str or exp_date == today_dash or force_notify):
                expiring_items.append({
                    "name": name,
                    "amount": exp_amount_raw,
                    "date": exp_date
                })
                total_expiring += exp_amount

    if expiring_items:
        details = "\n".join([f"• {item['name']}: {item['amount']} 元 (將於 {item['date']} 23:59:59 到期)" for item in expiring_items])
        title = "⚠️ momo 幣今日到期提醒！"
        body = f"【今日到期通知】\n您有即將過期的點數，請儘速使用：\n{details}\n\n折抵消費優先扣除即將到期點數。"
        print(f"[mo幣檢查] 🔔 發現今日有到期點數！發送 Bark 提醒...")
        try:
            from notifier import send_bark
            send_bark(title, body)
        except Exception as e:
            print(f"[mo幣檢查] 發送推播異常: {e}")
        return {"status": "EXPIRING_FOUND", "expiring": expiring_items, "total": total_expiring}
    else:
        print(f"[mo幣檢查] 今日無即將到期之點數。")
        return {"status": "NO_EXPIRING", "total": 0}


def main():
    parser = argparse.ArgumentParser(description="Momo 幣到期檢查工具")
    parser.add_argument("--cookie", help="Momo 網站 Cookie")
    parser.add_argument("--force-notify", action="store_true", help="強制推播目前查詢結果 (用於測試)")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    check_and_notify_expiring_coins(cookie=args.cookie, force_notify=args.force_notify)


if __name__ == "__main__":
    main()
