#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PChome 24h P幣餘額與即將到期檢查模組 (pchome_coin.py)
自動查詢會員目前可用 P 幣、待生效 P 幣、即將到期點數與明細，並發送 Bark 每日通知
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://ecvip.pchome.com.tw/web/PPoint/list",
    "Origin": "https://24h.pchome.com.tw",
    "Accept": "application/json, text/javascript, */*; q=0.01"
}


def load_all_cookies(cookie_arg: str = None) -> list:
    cookies = []
    raw = ""

    if cookie_arg:
        raw = cookie_arg
    else:
        for fname in ["pchome_cookie.txt", "cookie_pchome.txt"]:
            fpath = os.path.join(os.path.dirname(__file__), fname)
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    raw = f.read()
                break
        if not raw:
            raw = os.getenv("PCHOME_COOKIE", "")

    if "---" in raw:
        blocks = raw.split("---")
    else:
        blocks = raw.splitlines()

    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        cookies.append(clean)

    return cookies


def get_member_id(cookie: str) -> str:
    url = f"https://ecapi.pchome.com.tw/member/v2/member/id?_callback=jsonpcb_memberid&_={int(time.time()*1000)}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            m = re.search(r'jsonpcb_memberid\(\"([^\"]+)\"\)', text)
            if m:
                return m.group(1)
            return "會員"
    except Exception:
        return "未知會員"


def get_pcoin_total(cookie: str) -> dict:
    url = f"https://ecvip.pchome.com.tw/fsapi/pchcoin/coinTotal&{int(time.time()/60)}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("objTotal", {})
    except Exception as e:
        print(f"[PChome] 取得 P 幣總額失敗: {e}")
        return {}


def get_expiring_list(cookie: str) -> list:
    url = f"https://ecvip.pchome.com.tw/fsapi/pchcoin/expList&{int(time.time()/60)}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("rows", [])
    except Exception as e:
        print(f"[PChome] 取得即將到期明細失敗: {e}")
        return []


def check_account_pcoin(account_idx: int, cookie: str, send_bark=None, force_notify=False):
    mid = get_member_id(cookie)
    masked_mid = (mid[:4] + "***" + mid[-4:]) if len(mid) > 8 else mid
    tag = f"[帳號{account_idx} ({masked_mid})]"

    print(f"\n==================================================")
    print(f"👤 {tag} P 幣帳戶檢查")
    print(f"==================================================")

    total_data = get_pcoin_total(cookie)
    if not total_data:
        print("❌ 無法取得 P 幣資訊，請確認 Cookie 是否有效。")
        return

    rest_amt = int(total_data.get("RESTAMT", "0").replace(",", "").strip() or 0)
    un_amt = int(total_data.get("UNAMT", "0").replace(",", "").strip() or 0)
    exp_amt = int(total_data.get("EXPAMT", "0").replace(",", "").strip() or 0)
    exp_date = total_data.get("EXPDATE")
    debt_amt = int(total_data.get("DEBTAMT", "0").replace(",", "").strip() or 0)

    print(f"💰 可用 P 幣餘額: {rest_amt} P")
    if un_amt > 0:
        print(f"⏳ 待生效 P 幣: {un_amt} P")
    if debt_amt != 0:
        print(f"⚠️ 待歸還 P 幣: {debt_amt} P")

    exp_warning = ""
    if exp_amt > 0:
        exp_warning = f"⚠️ 即將到期 P 幣: {exp_amt} P (截止日: {exp_date})"
        print(exp_warning)
    else:
        print("✅ 近期無即將到期之 P 幣")

    # 取得詳細即將到期列表
    exp_rows = get_expiring_list(cookie)
    if exp_rows:
        print("\n📅 到期明細:")
        for r in exp_rows:
            print(f"   • {r.get('EXPDATE')}: {r.get('AMOUNT')} P")

    # 發送通知條件: 指定強制通知，或有即將到期點數，或餘額有異動
    if send_bark and (force_notify or exp_amt > 0):
        body_lines = [
            f"👤 帳號: {masked_mid}",
            f"💰 可用 P 幣: {rest_amt} P",
        ]
        if un_amt > 0:
            body_lines.append(f"⏳ 待生效: {un_amt} P")
        if exp_amt > 0:
            body_lines.append(f"⚠️ {exp_amt} P 將於 {exp_date} 到期！")

        body_lines.append(f"⏰ 查詢時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        title = f"PChome P幣每日提醒 ({tag})"
        if exp_amt > 0:
            title = f"🚨 PChome P幣到期警報 ({tag})"

        send_bark(
            title=title,
            body="\n".join(body_lines),
            group="pchome_coin"
        )
        print("📲 已發送 Bark 推播通知。")


def main():
    parser = argparse.ArgumentParser(description="PChome 24h P幣餘額與即將到期檢查工具")
    parser.add_argument("--cookie", type=str, help="指定 PChome Cookie")
    parser.add_argument("--notify", action="store_true", help="強制發送 Bark 每日餘額推播通知")
    args = parser.parse_args()

    try:
        from notifier import send_bark
    except Exception:
        send_bark = None

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("⚠️ 找不到任何 PChome Cookie！")
        print("請在 pchome_cookie.txt 貼入 Cookie，或設定環境變數 PCHOME_COOKIE。")
        sys.exit(0)

    print(f"👥 載入 {len(cookies)} 組 PChome 帳號憑證...")

    for idx, ck in enumerate(cookies, 1):
        check_account_pcoin(idx, ck, send_bark, force_notify=args.notify)



if __name__ == "__main__":
    main()
