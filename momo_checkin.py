#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 天天簽到 (dailycheckin) 自動簽到腳本
API: https://ma.momoshop.com.tw/api/campaign/game/
"""

import sys
import os
import time
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime

CHECKIN_BASE_URL = "https://ma.momoshop.com.tw/api/campaign/game"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoshop",
    "Origin": "https://ma.momoshop.com.tw",
    "Referer": "https://ma.momoshop.com.tw/edm/dailycheckin"
}


def request_json(url: str, method: str = "GET", data: dict = None, cookie: str = ""):
    hdrs = dict(HEADERS)
    if cookie:
        hdrs["Cookie"] = cookie.strip()
    
    body = None
    if data is not None:
        hdrs["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(err_body)
        except Exception:
            return {"success": False, "status_code": e.code, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": str(e)}


def get_latest_mission():
    url = f"{CHECKIN_BASE_URL}/latest"
    res = request_json(url)
    return res


def get_user_activity(mission_id: str, cookie: str):
    url = f"{CHECKIN_BASE_URL}/{mission_id}/activity"
    return request_json(url, cookie=cookie)


def play_task(mission_id: str, task_group_seq: int, task_seq: int, cookie: str):
    url = f"{CHECKIN_BASE_URL}/{mission_id}/play"
    payload = {
        "task_group_seq": task_group_seq,
        "task_seq": task_seq
    }
    return request_json(url, method="POST", data=payload, cookie=cookie)


def process_referral(referral_code: str, cookie: str):
    if not referral_code:
        return
    url = f"{CHECKIN_BASE_URL}/share/r/{referral_code}"
    hdrs = dict(HEADERS)
    if cookie:
        hdrs["Cookie"] = cookie.strip()
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 處理推薦連結完成: referral={referral_code}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 處理推薦連結異常: {e}")


def run_daily_checkin(cookie: str, referral: str = "2b4b924f6cd7a33d8279a2b80172d730", force: bool = False):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行 momo 天天簽到流程...")
    
    # 1. 取得最新簽到活動
    mission = get_latest_mission()
    if not mission or "mission_id" not in mission:
        print("無法取得最新簽到活動，可能目前無進行中的簽到檔期。")
        return False
    
    mission_id = mission["mission_id"]
    display_name = mission.get("display_name", "天天簽到")
    print(f"當前活動: {display_name} (ID: {mission_id})")

    # 2. 處理分享互助
    if referral:
        process_referral(referral, cookie)

    # 3. 查詢用戶當前進度
    activity = get_user_activity(mission_id, cookie)
    if activity.get("message") == "Unauthorized":
        print("錯誤: 登入憑證無效或過期，請更新 Cookie。")
        try:
            from notifier import send_bark
            send_bark("momo 天天簽到失敗", "⚠️ Cookie 登入憑證無效或過期，請重新登入更新。")
        except Exception:
            pass
        return False

    print(f"使用者狀態查詢成功: {activity.get('status', 'OK')}")

    # 4. 找出今天的任務
    today_str = datetime.now().strftime("%Y-%m-%d")
    task_calendars = mission.get("task_calendars", [])
    today_calendar = None
    for cal in task_calendars:
        if cal.get("task_date") == today_str:
            today_calendar = cal
            break
            
    if not today_calendar:
        print(f"未在活動行事曆中找到今日 ({today_str}) 的簽到任務。")
        try:
            from notifier import send_bark
            send_bark("momo 天天簽到提醒", f"未在活動行事曆中找到今日 ({today_str}) 的簽到任務。")
        except Exception:
            pass
        return False

    task_group_seq = today_calendar.get("task_calendar_seq")
    tasks = today_calendar.get("tasks", [])

    # 檢查今日是否已完成簽到任務，若已簽過則直接略過不重複執行
    if not force:
        user_calendars = activity.get("task_calendars", [])
        today_user_cal = next((c for c in user_calendars if c.get("task_calendar_seq") == task_group_seq), None)
        if today_user_cal and today_user_cal.get("status") == "COMPLETED":
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 今日 ({today_str}) 簽到任務已於稍早完成，無需重複簽到。")
            return True

    print(f"今日任務組: task_calendar_seq={task_group_seq}，共 {len(tasks)} 個任務：")

    # 5. 執行各個任務
    task_results = []
    for t in tasks:
        task_seq = t.get("task_seq")
        name = t.get("display_name", f"任務 {task_seq}")
        wait_sec = t.get("setup", {}).get("time_on_page_seconds", 8)
        
        print(f" -> 正在執行任務 [{task_seq}]: {name} (模擬停留 {wait_sec} 秒)...")
        time.sleep(min(wait_sec, 8))
        
        res = play_task(mission_id, task_group_seq, task_seq, cookie)
        if res.get("success") or res.get("status") == "OK" or "data" in res:
            print(f"    ✅ 任務 [{task_seq}] 完成: {res}")
            task_results.append(f"• {name}: 完成")
        elif res.get("code") == "FULFILLED":
            print(f"    ℹ️ 任務 [{task_seq}] 今日已完成")
            task_results.append(f"• {name}: 今日已完成")
        else:
            msg = res.get("message", res)
            print(f"    ℹ️ 任務 [{task_seq}] 回應: {msg}")
            task_results.append(f"• {name}: {msg}")

    # 6. 重新查詢最新進度
    time.sleep(1)
    final_act = get_user_activity(mission_id, cookie)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 簽到流程完成！最新狀態: {final_act}")

    # 發送 Bark 通知
    try:
        from notifier import send_bark
        claimed = final_act.get("reward_ledger", {}).get("claimed_amount", 0)
        calendars = final_act.get("task_calendars", [])
        done_days = sum(1 for c in calendars if c.get("status") == "COMPLETED")
        total_days = len(calendars)
        
        body_lines = [
            f"📅 活動: {display_name}",
            f"🎯 今日簽到任務完成",
            f"📈 檔期進度: 已簽到 {done_days}/{total_days} 天",
            f"💰 累計領取: {claimed} mo點",
            "\n【任務明細】",
            *task_results
        ]
        send_bark("momo 天天簽到完成", "\n".join(body_lines))
    except Exception as e:
        print(f"發送推播通知異常: {e}")

    return True


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
    parser = argparse.ArgumentParser(description="Momo 天天簽到自動化工具")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串")
    parser.add_argument("--referral", default="2b4b924f6cd7a33d8279a2b80172d730", help="推薦/互助碼")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    parser.add_argument("--force", action="store_true", help="強制重新簽到即使今日已完成")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookie = load_cookie(args.cookie)
    if not cookie:
        print("錯誤: 未找到 Cookie。請透過 --cookie 指定，或將 Cookie 寫入 cookie.txt。")
        sys.exit(1)

    run_daily_checkin(cookie, referral=args.referral, force=args.force)


if __name__ == "__main__":
    main()
