#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feebee 飛比價格 每日自動簽到腳本 (純簽到版本，無廣告抽獎)
活動網址: https://feebee.com.tw/event/reward_ad?is_show_production_ad=1&type=daily_checkin&from=mission_center
"""

import sys
import os
import time
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

# 導入 Bark 通知模組
try:
    from notifier import send_bark
except ImportError:
    def send_bark(title: str, body: str, group: str = "feebee"):
        return False

WEB_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
DEFAULT_APP_UA = "ios-prod-release-v4.9.4-2026110201"
DEFAULT_APPD = "41609167"

WALLET_URL = "https://feebee.com.tw/member/point/wallet/"
REWARD_AD_URL = "https://feebee.com.tw/event/reward_ad?is_show_production_ad=1&type=daily_checkin&from=mission_center"
MISSION_CENTER_URL = "https://feebee.com.tw/event/mission_center?did={did}"


def normalize_cookie(raw_cookie: str) -> str:
    """確保 Cookie 包含 app 與 appd 參數"""
    cookie_str = raw_cookie.strip()
    if not cookie_str:
        return ""

    parts = [p.strip() for p in cookie_str.split(";") if p.strip()]
    has_app = any(p.startswith("app=") for p in parts)
    has_appd = any(p.startswith("appd=") for p in parts)

    if not has_app:
        parts.insert(0, f"app={DEFAULT_APP_UA}")
    if not has_appd:
        parts.insert(1, f"appd={DEFAULT_APPD}")

    return "; ".join(parts)


def load_all_cookies(cookie_arg: str = None) -> list:
    """載入多帳號 Cookie"""
    cookies = []
    raw = ""

    if cookie_arg:
        raw = cookie_arg
    else:
        for fname in ["feebee_cookie.txt", "cookie_feebee.txt"]:
            fpath = os.path.join(os.path.dirname(__file__), fname)
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    raw = f.read()
                break
        if not raw:
            raw = os.getenv("FEEBEE_COOKIE", "")

    if "---" in raw:
        blocks = raw.split("---")
    else:
        blocks = raw.splitlines()

    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        normalized = normalize_cookie(clean)
        if normalized:
            cookies.append(normalized)

    return cookies


def request_get(url: str, headers: dict = None, cookie: str = None) -> tuple:
    req_headers = {
        "User-Agent": WEB_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if headers:
        req_headers.update(headers)
    if cookie:
        req_headers["Cookie"] = cookie

    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return e.code, body
    except Exception as e:
        return 0, str(e)


def check_wallet_status(cookie: str) -> dict:
    """
    查詢 Feebee 錢包狀態與歷史紀錄
    時區依據：Feebee 伺服器輸出為 UTC 時間，需轉為 UTC+8 (台灣時間) 比對今日簽到
    """
    code, html = request_get(WALLET_URL, cookie=cookie)
    if code != 200:
        return {"logged_in": False, "msg": f"連線異常 (HTTP {code})"}

    if "/logout" not in html and "登出" not in html and "point_total" not in html:
        return {"logged_in": False, "msg": "未登入或 Cookie 已過期"}

    user_name = "Feebee會員"
    m_user = re.search(r"my_account_name[^>]*>Hi,([^！!<]+)", html)
    if not m_user:
        m_user = re.search(r"class=[\"\x27]user-login__text[\"\x27]>([^<]+)<", html)
    if m_user:
        user_name = m_user.group(1).strip()

    points = "0"
    m_pt = re.search(r"class=[\"\x27]point_total[\"\x27][^>]*>([^<]+)<", html)
    if not m_pt:
        m_pt = re.search(r"class=[\"\x27]my-point__value[\"\x27]>([^<]+)<", html)
    if m_pt:
        points = m_pt.group(1).strip()

    # 比對今日簽到紀錄 (UTC -> UTC+8)
    tz_tw = timezone(timedelta(hours=8))
    today_tw = datetime.now(tz_tw).strftime("%Y-%m-%d")
    already_checked_in = False

    # 1. 手機版格式
    dates = re.findall(r"data-qa-id=\"point-history-date-\d+\">([^<]+)<", html)
    titles = re.findall(r"data-qa-id=\"point-history-title-\d+\">([^<]+)<", html)
    for d_str, t_str in zip(dates, titles):
        try:
            dt_utc = datetime.strptime(d_str.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            dt_tw = dt_utc.astimezone(tz_tw)
            if dt_tw.strftime("%Y-%m-%d") == today_tw and "每日簽到" in t_str:
                already_checked_in = True
                break
        except Exception:
            if d_str.startswith(today_tw) and "每日簽到" in t_str:
                already_checked_in = True
                break

    # 2. 桌面版格式
    if not already_checked_in:
        items = re.findall(
            r"<tr class=\"point-wallet__item\">\s*<td class=\"point-wallet__time\">([^<]+)</td>\s*<td class=\"point-wallet__platform\">([^<]+)</td>\s*<td class=\"point-wallet__content\">([^<]+)</td>",
            html
        )
        for t_str, _, c_str in items:
            try:
                dt_utc = datetime.strptime(t_str.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                dt_tw = dt_utc.astimezone(tz_tw)
                if dt_tw.strftime("%Y-%m-%d") == today_tw and "每日簽到" in c_str:
                    already_checked_in = True
                    break
            except Exception:
                if t_str.startswith(today_tw) and "每日簽到" in c_str:
                    already_checked_in = True
                    break

    return {
        "logged_in": True,
        "user_name": user_name,
        "points": points,
        "already_checked_in": already_checked_in
    }


def execute_daily_checkin(cookie: str) -> dict:
    """
    透過 GET reward_ad 頁面觸發每日簽到 (後端即時入帳)
    """
    m_appd = re.search(r"appd=([^;]+)", cookie)
    appd = m_appd.group(1).strip() if m_appd else DEFAULT_APPD

    headers = {
        "User-Agent": WEB_UA,
        "Referer": MISSION_CENTER_URL.format(did=appd),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    code, html = request_get(REWARD_AD_URL, headers=headers, cookie=cookie)
    if code != 200:
        return {"success": False, "msg": f"請求簽到頁面失敗 (HTTP {code})"}

    m_reward = re.search(r"window\.dailyCheckinReward\s*=\s*(\d+)", html)
    m_has = re.search(r"hasDailyCheckin\s*:\s*(true|false)", html)
    m_login = re.search(r"isLogin\s*:\s*(true|false)", html)

    reward = int(m_reward.group(1)) if m_reward else 0
    has_checkin = (m_has.group(1) == "true") if m_has else False
    is_login = (m_login.group(1) == "true") if m_login else False

    if not is_login and "isLogin" in html:
        return {"success": False, "msg": "簽到頁面判定未登入，請更新 Cookie"}

    if has_checkin and reward > 0:
        return {"success": True, "reward": reward, "msg": f"簽到成功！獲得 {reward} 點"}
    else:
        return {"success": True, "reward": 0, "msg": "今日已完成簽到"}


def run_account_checkin(index: int, total: int, cookie: str) -> dict:
    print(f"\n[{index}/{total}] 檢查 Feebee 會員狀態...")

    # 1. 錢包查詢
    wallet = check_wallet_status(cookie)
    if not wallet["logged_in"]:
        print(f"  ❌ 登入校驗失敗: {wallet.get('msg', 'Cookie 無效')}")
        return {"success": False, "msg": "Cookie 無效或未登入"}

    user_name = wallet["user_name"]
    points = wallet["points"]
    already_checked = wallet["already_checked_in"]
    print(f"  👤 會員: {user_name} | 💰 目前點數: {points} 點")

    # 2. 每日簽到
    checkin_msg = ""
    if already_checked:
        print("  ℹ️ 今日紀錄顯示已完成每日簽到")
        checkin_msg = "今日已簽到"
    else:
        print("  ⏳ 執行每日簽到...")
        res = execute_daily_checkin(cookie)
        if res.get("reward", 0) > 0:
            print(f"  🎉 {res['msg']}")
            checkin_msg = f"簽到成功(+{res['reward']}點)"
        else:
            print(f"  ℹ️ {res['msg']}")
            checkin_msg = res["msg"]

    # 3. 複查錢包最新點數
    w_after = check_wallet_status(cookie)
    if w_after.get("logged_in"):
        points = w_after.get("points", points)

    summary = f"👤 {user_name} | {checkin_msg} | 💰 餘額: {points}點"
    return {
        "success": True,
        "user_name": user_name,
        "points": points,
        "msg": summary
    }


def main():
    parser = argparse.ArgumentParser(description="Feebee 每日自動簽到 (純簽到)")
    parser.add_argument("--cookie", type=str, help="Feebee Cookie 字串")
    args = parser.parse_args()

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("❌ 未找到 Feebee Cookie！請在 feebee_cookie.txt 設定或指定環境變數 FEEBEE_COOKIE。")
        sys.exit(1)

    print(f"🚀 開始執行 Feebee 每日簽到任務 (共有 {len(cookies)} 組帳號)")
    results = []

    for idx, c in enumerate(cookies, 1):
        res = run_account_checkin(idx, len(cookies), c)
        results.append(f"帳號 {idx}: {res.get('msg', '未知')}")
        if idx < len(cookies):
            time.sleep(2)

    # 推播通知
    push_title = "Feebee 飛比每日簽到結果"
    push_body = "\n".join(results)
    print("\n" + "=" * 40)
    print(push_title)
    print(push_body)
    print("=" * 40)

    send_bark(push_title, push_body, group="feebee")


if __name__ == "__main__":
    main()
