#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feebee 飛比價格 每日自動簽到與獎勵廣告抽獎腳本
支援會員狀態查詢、錢包餘額檢查、每日簽到與廣告抽獎
活動網址: https://feebee.com.tw/event/reward_ad?is_show_production_ad=1&did=nil
"""

import sys
import os
import time
import json
import re
import uuid
import hashlib
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# 導入 Bark 通知模組
try:
    from notifier import send_bark
except ImportError:
    def send_bark(title: str, body: str, group: str = "feebee"):
        return False

APP_UA = "android-prod-release-v3.1.10-2017071191"
WEB_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"

WALLET_URL = "https://feebee.com.tw/member/point/wallet/"
EVENT_URL = "https://feebee.com.tw/event/reward_ad?is_show_production_ad=1&did={did}"
API_STATUS_URL = "https://api.feebee.com.tw/web/reward_ad/status"
API_VERIFY_URL = "https://api.feebee.com.tw/web/reward_ad/verify_status"
API_LOTTERY_URL = "https://api.feebee.com.tw/web/reward_ad/lottery"


def generate_signed_appd(device_id: str = None) -> str:
    """產生符合 Feebee 官方校驗規則的 App Device ID"""
    did = device_id or uuid.uuid4().hex[:16]
    salt = f"crs6vSq8H3v{did}TcDIUJyD5"
    sig = hashlib.sha1(salt.encode("utf-8")).hexdigest()[5:13]
    return f"{did}.{sig}"


def normalize_cookie(raw_cookie: str) -> str:
    """補全 app 相關 cookie"""
    cookie_str = raw_cookie.strip()
    if not cookie_str:
        return ""

    parts = [p.strip() for p in cookie_str.split(";") if p.strip()]
    has_app = any(p.startswith("app=") for p in parts)
    has_appd = any(p.startswith("appd=") for p in parts)

    if not has_app:
        parts.append(f"app={APP_UA}")
    if not has_appd:
        parts.append(f"appd={generate_signed_appd()}")

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


def request_get(url: str, headers: dict, cookie: str = "") -> tuple:
    """發送 GET 請求，回傳 (status_code, body_string)"""
    hdrs = dict(headers)
    if cookie:
        hdrs["Cookie"] = cookie

    req = urllib.request.Request(url, headers=hdrs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return e.code, err_body
    except Exception as e:
        return 0, str(e)


def check_wallet_status(cookie: str) -> dict:
    """查詢會員錢包與今日簽到狀態（相容桌面版與手機版頁面）"""
    headers = {
        "User-Agent": WEB_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://feebee.com.tw/"
    }
    code, html = request_get(WALLET_URL, headers, cookie)
    if code != 200:
        return {"logged_in": False, "msg": f"連線異常 (HTTP {code})"}

    if "/logout" not in html and "登出" not in html:
        return {"logged_in": False, "msg": "未登入或 Cookie 已過期"}

    # 提取用戶名稱
    user_name = "Feebee會員"
    m_user = re.search(r"my_account_name[^>]*>Hi,([^！!<]+)", html)
    if not m_user:
        m_user = re.search(r"class=[\"\x27]user-login__text[\"\x27]>([^<]+)<", html)
    if m_user:
        user_name = m_user.group(1).strip()

    # 提取點數
    points = "0"
    m_pt = re.search(r"class=[\"\x27]point_total[\"\x27][^>]*>([^<]+)<", html)
    if not m_pt:
        m_pt = re.search(r"class=[\"\x27]my-point__value[\"\x27]>([^<]+)<", html)
    if m_pt:
        points = m_pt.group(1).strip()

    # 檢查今日簽到紀錄
    today_str = datetime.now().strftime("%Y-%m-%d")
    already_checked_in = False

    # 1. 手機版 data-qa-id 格式
    dates = re.findall(r"data-qa-id=\"point-history-date-\d+\">([^<]+)<", html)
    titles = re.findall(r"data-qa-id=\"point-history-title-\d+\">([^<]+)<", html)
    for d, t in zip(dates, titles):
        if d.startswith(today_str) and "每日簽到" in t:
            already_checked_in = True
            break

    # 2. 桌面版 table 格式
    if not already_checked_in:
        items = re.findall(
            r"<tr class=\"point-wallet__item\">\s*<td class=\"point-wallet__time\">([^<]+)</td>\s*<td class=\"point-wallet__platform\">([^<]+)</td>\s*<td class=\"point-wallet__content\">([^<]+)</td>",
            html
        )
        for t, _, c in items:
            if t.startswith(today_str) and "每日簽到" in c:
                already_checked_in = True
                break

    return {
        "logged_in": True,
        "user_name": user_name,
        "points": points,
        "already_checked_in": already_checked_in
    }


def run_account_checkin(index: int, total: int, cookie: str) -> dict:
    print(f"\n[{index}/{total}] 檢查 Feebee 會員狀態...")

    # 1. 先確認會員身分與錢包紀錄
    wallet = check_wallet_status(cookie)
    if not wallet["logged_in"]:
        print(f"  ❌ 登入校驗失敗: {wallet.get('msg', 'Cookie 無效')}")
        return {"success": False, "msg": "Cookie 無效或未登入"}

    user_name = wallet["user_name"]
    points = wallet["points"]
    already_checked = wallet["already_checked_in"]
    print(f"  👤 會員: {user_name} | 💰 目前點數: {points} 點")

    # 2. 若今日尚未簽到，觸發簽到流程
    checkin_msg = ""
    if already_checked:
        print("  ℹ️ 今日已完成每日簽到，跳過簽到請求")
        checkin_msg = "今日已簽到"
    else:
        print("  ⏳ 執行今日簽到...")
        m_appd = re.search(r"appd=([^;]+)", cookie)
        appd = m_appd.group(1).strip() if m_appd else generate_signed_appd()
        page_url = EVENT_URL.format(did=appd)
        headers = {
            "User-Agent": APP_UA,
            "X-feebee-webview": APP_UA,
            "Referer": "https://feebee.com.tw/point/mission/",
        }
        _, html = request_get(page_url, headers, cookie)
        # 額外嘗試 flybee checkin
        request_get("https://feebee.com.tw/flybee/checkin", {"User-Agent": WEB_UA}, cookie)

        # 重新檢查錢包確認是否簽到入帳
        w_after = check_wallet_status(cookie)
        if w_after.get("already_checked_in"):
            diff = int(w_after.get("points", 0)) - int(points)
            reward_str = f"+{diff}" if diff > 0 else "+2"
            print(f"  🎉 每日簽到成功！獲得 {reward_str} 點 (點數: {w_after.get('points')})")
            checkin_msg = f"簽到成功({reward_str}點)"
            points = w_after.get("points")
        else:
            print("  ⚠️ 簽到請求已發送，狀態待確認")
            checkin_msg = "已發送簽到"

    # 3. 執行看廣告抽獎
    api_headers = {
        "User-Agent": APP_UA,
        "X-feebee-webview": APP_UA,
        "Referer": "https://feebee.com.tw/event/reward_ad",
        "Origin": "https://feebee.com.tw",
        "Accept": "application/json, text/plain, */*",
    }

    _, status_raw = request_get(API_STATUS_URL, api_headers, cookie)
    remain_chance = 0
    remain_time = 0
    try:
        status_data = json.loads(status_raw)
        remain_chance = status_data.get("remain_chance_count", 0)
        remain_time = status_data.get("remain_time_for_ad", 0)
        print(f"  🎰 抽獎狀態: 機會 {remain_chance} 次，冷卻 {remain_time} 秒")
    except Exception:
        pass

    # 若冷卻為 0 且無次數，驗證廣告獲取抽獎資格
    if remain_chance == 0 and remain_time == 0:
        v_ts = int(time.time())
        verify_url = f"{API_VERIFY_URL}?v_ts={v_ts}"
        _, verify_raw = request_get(verify_url, api_headers, cookie)
        try:
            v_data = json.loads(verify_raw)
            if v_data.get("verify_status"):
                print("  ✅ 廣告觀看驗證成功，獲得 1 次抽獎機會！")
                remain_chance = 1
        except Exception:
            pass

    # 執行抽獎
    lottery_msg = ""
    if remain_chance > 0:
        _, lottery_raw = request_get(API_LOTTERY_URL, api_headers, cookie)
        try:
            l_data = json.loads(lottery_raw)
            point = l_data.get("point", 0)
            err = l_data.get("error_code", "")
            if l_data.get("prize") or point > 0:
                print(f"  🎁 抽獎中獎！獲得 {point} 點！")
                lottery_msg = f"抽中 {point} 點"
            elif err:
                lottery_msg = f"抽獎限制({err})"
            else:
                lottery_msg = "抽獎未中"
        except Exception:
            pass

    parts = [f"👤 {user_name}", checkin_msg]
    if lottery_msg:
        parts.append(lottery_msg)
    parts.append(f"💰 餘額: {points}點")

    return {
        "success": True,
        "user_name": user_name,
        "points": points,
        "msg": " | ".join(parts)
    }


def main():
    parser = argparse.ArgumentParser(description="Feebee 每日自動簽到與看廣告抽獎")
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
