#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PChome 24h 天天簽到拿 P 幣 (check-in) 自動化腳本
每日 08:00:00 換日開放簽到，支援定時/狙擊模式、多帳號並行與 Bark 推播
活動網址: https://24h.pchome.com.tw/activity/check-in
"""

import sys
import os
import time
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime

ACTIVITY_API_URL = "https://ecapi.pchome.com.tw/fsapi/marketing/signingift/v1/activity"
RECEIVED_API_BASE = "https://ecapi.pchome.com.tw/fsapi/marketing/signingift/v1/receivedrecor"
SIGNIN_API_URL = "https://ecapi.pchome.com.tw/fsapi/marketing/signingift/v1/signin"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 PChome24h",
    "Origin": "https://24h.pchome.com.tw",
    "Referer": "https://24h.pchome.com.tw/activity/check-in",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json"
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


def get_current_activity():
    req = urllib.request.Request(ACTIVITY_API_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("current")
    except Exception as e:
        print(f"[PChome] 取得活動資訊異常: {e}")
        return None


def get_member_received(activity_id: str, cookie: str):
    url = f"{RECEIVED_API_BASE}/{activity_id}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("member_received", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        if e.code == 401:
            print("[PChome] 查詢簽到紀錄失敗: 未登入或 Cookie 已過期 (401-001)")
            return None
        print(f"[PChome] 查詢簽到紀錄 HTTP 錯誤: {e.code} - {body}")
        return None
    except Exception as e:
        print(f"[PChome] 查詢簽到紀錄異常: {e}")
        return None


def execute_signin(activity_id: str, gift_id: str, cookie: str):
    payload = {
        "activity_id": activity_id,
        "gift_id": gift_id
    }
    data = json.dumps(payload).encode("utf-8")
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(SIGNIN_API_URL, data=data, headers=hdrs, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": "SUCCESS", "code": 200, "message": "今日簽到成功！"}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            res_json = json.loads(err_body)
            status_code = res_json.get("status", "")
        except Exception:
            status_code = ""

        if e.code == 400:
            if status_code == "400-001":
                return {"status": "FULL", "code": 400, "message": "今日活動名額已額滿！"}
            elif status_code == "400-002":
                return {"status": "PAUSED", "code": 400, "message": "活動已暫停！"}
            return {"status": "FAIL", "code": 400, "message": f"簽到失敗 (400: {status_code})"}
        elif e.code == 401:
            return {"status": "NO_LOGIN", "code": 401, "message": "未登入或 Cookie 失效！"}
        elif e.code == 403:
            if status_code == "403-001":
                return {"status": "NEED_PHONE", "code": 403, "message": "帳號需綁定手機門號方可簽到！"}
            return {"status": "FORBIDDEN", "code": 403, "message": "存取被拒 (403)"}
        return {"status": "HTTP_ERROR", "code": e.code, "message": err_body}
    except Exception as e:
        return {"status": "EXCEPTION", "code": 0, "message": str(e)}


def run_pchome_checkin_for_account(cookie: str, account_idx: int = 1, current_act: dict = None):
    act = current_act or get_current_activity()
    if not act:
        print(f"[帳號 {account_idx}] 無法取得當前進行中之簽到活動。")
        return {"success": False, "message": "無法取得活動資訊"}

    activity_id = act.get("activity_id")
    status = act.get("current_activity_status", "")
    current_period = act.get("current_period_start_date", "")
    duration_cards = act.get("activity_duration", [])

    print(f"\n==============================")
    print(f"👤 PChome 帳號 {account_idx} 簽到流程")
    print(f"活動編號: {activity_id} | 當前狀態: {status}")
    print(f"當日週期起點: {current_period}")
    print(f"==============================")

    # 查詢該會員已領取紀錄
    received_records = get_member_received(activity_id, cookie)
    if received_records is None:
        return {"success": False, "message": "Cookie 失效或未登入"}

    received_count = len(received_records)
    print(f"[帳號 {account_idx}] 目前本檔累積簽到天數: {received_count} / {len(duration_cards)} 天")

    # 檢查今日是否已簽到：比對今日日期與最後一筆領取紀錄
    today_iso = datetime.now().strftime("%Y-%m-%d")
    for r in received_records:
        rec_time = r.get("received_time", "") or r.get("create_time", "")
        if rec_time.startswith(today_iso):
            print(f"✅ [帳號 {account_idx}] 今日已完成簽到！略過重複執行。")
            return {"success": True, "message": "今日已完成簽到", "records": received_records}

    if received_count >= len(duration_cards):
        print(f"🎉 [帳號 {account_idx}] 本檔期所有天數均已簽滿！")
        return {"success": True, "message": "本檔已全數簽滿", "records": received_records}

    if status == "BUDGETS_FULL":
        print(f"⚠️ 今日 PChome 簽到名額已額滿 (BUDGETS_FULL)！請於明日 08:00:00 前提早開搶。")
        return {"success": False, "message": "今日名額已額滿"}

    # 取得下一張待簽卡片的 gift_id
    next_card = duration_cards[received_count]
    next_gift_id = next_card.get("gift_id")
    p_coin = next_card.get("p_coin", "1")
    print(f"[帳號 {account_idx}] 執行第 {received_count + 1} 天簽到 (預計領取 {p_coin} P幣，gift_id={next_gift_id})...")

    result = execute_signin(activity_id, next_gift_id, cookie)
    print(f"結果: {result['message']}")

    # Bark 推播
    try:
        from notifier import send_bark
        body = f"【PChome 24h 天天簽到】\n帳號 {account_idx}：{result['message']}\n檔期進度：{received_count + (1 if result['status'] == 'SUCCESS' else 0)}/{len(duration_cards)} 天"
        send_bark("PChome 簽到結果", body)
    except Exception as e:
        print(f"發送推播異常: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="PChome 24h 天天簽到自動化工具")
    parser.add_argument("--cookie", help="PChome 登入 Cookie 字串")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("提示: 未找到 PChome Cookie。")
        print("請建立 pchome_cookie.txt 或使用 --cookie 傳入 Cookie。")
        sys.exit(1)

    act = get_current_activity()
    if not act:
        print("錯誤: 無法連線 PChome 簽到 API。")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 載入 {len(cookies)} 個 PChome 帳號憑證...")
    for idx, c in enumerate(cookies, 1):
        run_pchome_checkin_for_account(c, account_idx=idx, current_act=act)


if __name__ == "__main__":
    main()
