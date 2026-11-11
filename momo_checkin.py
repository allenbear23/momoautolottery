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
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

CHECKIN_BASE_URL = "https://ma.momoshop.com.tw/api/campaign/game"
SHARE_PLUGIN_ID = "8d593694-9773-42c2-a3ea-4559a87cb6d5"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoshop/12.1.0",
    "Origin": "https://ma.momoshop.com.tw",
    "Referer": "https://ma.momoshop.com.tw/edm/dailycheckin",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh-Hant;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty"
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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def process_referral(referral_code: str, cookie: str) -> str:
    if not referral_code:
        return "EMPTY"
    url = f"{CHECKIN_BASE_URL}/share/r/{referral_code}"
    hdrs = dict(HEADERS)
    if cookie:
        hdrs["Cookie"] = cookie.strip()
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with opener.open(req, timeout=10) as resp:
            code = resp.getcode()
            return "SUCCESS" if 200 <= code < 400 else f"HTTP_{code}"
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return "SUCCESS"
        if e.code == 400:
            return "FORBIDDEN"
        if e.code == 404:
            return "NOT_FOUND"
        if e.code == 410:
            return "EXPIRED"
        return f"HTTP_{e.code}"
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 處理推薦連結異常: {e}")
        return "ERROR"


def create_share_link(mission_id: str, cookie: str, plugin_id: str = SHARE_PLUGIN_ID) -> str:
    url = f"{CHECKIN_BASE_URL}/{mission_id}/share-links"
    res = request_json(url, method="POST", data={"plugin_id": plugin_id}, cookie=cookie)
    share_url = res.get("share_url", "")
    if share_url:
        parsed = urllib.parse.urlparse(share_url)
        qs = urllib.parse.parse_qs(parsed.query)
        ref_list = qs.get("referral", [])
        if ref_list:
            return ref_list[0]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 建立分享連結失敗: {res}")
    return ""


def _has_share_reward_today(activity: dict, today_str: str) -> bool:
    records = (activity.get("reward_ledger") or {}).get("records") or []
    target_key = f"share_click:{today_str}"
    return any(
        r.get("reward_type") == "share_click" and r.get("scope_key") == target_key
        for r in records
    )


def run_mutual_share(accounts: list):
    """利用多帳號自動互相點擊每日簽到分享連結以領取額外 mo 點"""
    if len(accounts) < 2:
        print("\n[簽到分享] 帳號數不足 2 組，略過互助分享。")
        return

    mission = get_latest_mission()
    if not mission or "mission_id" not in mission:
        return

    mission_id = mission["mission_id"]
    bonus_list = mission.get("bonus_rewards") or []
    share_bonus_cfg = next((b for b in bonus_list if b.get("bonus_type") == "share_click"), None)
    if not share_bonus_cfg:
        print("\n[簽到分享] 本檔期無 share_click 分享加碼活動，略過。")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n==============================")
    print(f"🤝 開始執行簽到活動互助分享 ({today_str})...")
    print(f"==============================")

    summary_lines = []
    n = len(accounts)
    for idx, (sharer_name, sharer_cookie) in enumerate(accounts):
        act = get_user_activity(mission_id, sharer_cookie)
        if act.get("message") == "Unauthorized":
            print(f"[{sharer_name}] Cookie 無效，略過分享。")
            continue

        act_bonus = next(
            (b for b in (act.get("bonus_rewards") or []) if b.get("bonus_type") == "share_click"),
            {}
        )
        max_days = act_bonus.get("condition", {}).get(
            "max_rewarded_distinct_days",
            share_bonus_cfg.get("condition", {}).get("max_rewarded_distinct_days", 2)
        )
        rewarded_days = act_bonus.get("rewarded_distinct_days", 0)
        progress_status = act_bonus.get("progress_status", "")
        reward_amt = act_bonus.get("reward", {}).get("amount", 1)

        if progress_status == "COMPLETED" or rewarded_days >= max_days:
            print(f"[{sharer_name}] 本檔期分享獎勵已額滿 ({rewarded_days}/{max_days} 天)，無需再分享。")
            continue

        if _has_share_reward_today(act, today_str):
            print(f"[{sharer_name}] 今日 ({today_str}) 分享獎勵已領取 ({rewarded_days}/{max_days} 天)。")
            continue

        referral_code = create_share_link(mission_id, sharer_cookie)
        if not referral_code:
            continue

        print(f"[{sharer_name}] 已產生分享碼 {referral_code}，尋找互助帳號點擊...")
        helped = False
        for offset in range(1, n):
            helper_idx = (idx + offset) % n
            helper_name, helper_cookie = accounts[helper_idx]
            status = process_referral(referral_code, helper_cookie)
            print(f"  -> {helper_name} 點擊結果: {status}")
            time.sleep(0.8)

            act_after = get_user_activity(mission_id, sharer_cookie)
            act_bonus_after = next(
                (b for b in (act_after.get("bonus_rewards") or []) if b.get("bonus_type") == "share_click"),
                {}
            )
            new_days = act_bonus_after.get("rewarded_distinct_days", rewarded_days)
            if _has_share_reward_today(act_after, today_str) or new_days > rewarded_days:
                msg = f"✅ {sharer_name}: 由 {helper_name} 協助完成分享，獲得 {reward_amt} mo點 ({new_days}/{max_days} 天)"
                print(f"  {msg}")
                summary_lines.append(msg)
                helped = True
                break

        if not helped:
            print(f"[{sharer_name}] ⚠️ 所有其他帳號均無法觸發今日分享獎勵（可能皆已協助過）。")

    if summary_lines:
        try:
            from notifier import send_bark
            send_bark("momo 簽到互助分享完成", "\n".join(summary_lines))
        except Exception as e:
            print(f"發送分享推播異常: {e}")


def run_daily_checkin(cookie: str, referral: str = "", force: bool = False, account_label: str = None):
    user_label = account_label or get_user_display_name(cookie)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行 momo 天天簽到流程 ({user_label})...")
    
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
            f"👤 帳號: {user_label}",
            f"📅 活動: {display_name}",
            f"🎯 今日簽到任務完成",
            f"📈 檔期進度: 已簽到 {done_days}/{total_days} 天",
            f"💰 累計領取: {claimed} mo點",
            "\n【任務明細】",
            *task_results
        ]
        send_bark(f"momo 簽到完成 - {user_label}", "\n".join(body_lines))
    except Exception as e:
        print(f"發送推播通知異常: {e}")

    return True


def get_user_display_name(cookie: str, default_idx: int = 1) -> str:
    m = re.search(r'loginUser=([^;]+)', cookie)
    if m:
        try:
            val = m.group(1).replace('+', ' ')
            name = urllib.parse.unquote(val).strip()
            if name:
                return f"帳號 {default_idx} ({name})"
        except Exception:
            pass
    return f"帳號 {default_idx}"


def load_all_cookies(cookie_arg: str = None) -> list:
    cookies = []
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

    if "---" in raw:
        blocks = raw.split("---")
    else:
        blocks = raw.splitlines()

    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        if any(k in clean for k in ("LOGINSESSION", "st=", "_atrk", "isEN")):
            cookies.append(clean)

    return cookies


def main():
    parser = argparse.ArgumentParser(description="Momo 天天簽到自動化工具 (支援多帳號)")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串 (多帳號可用換行或 --- 分隔)")
    parser.add_argument("--referral", default="", help="推薦/互助碼")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    parser.add_argument("--force", action="store_true", help="強制重新簽到即使今日已完成")
    parser.add_argument("--no-share", action="store_true", help="停用自動互助分享")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。請透過 --cookie 指定，或將 Cookie 寫入 cookie.txt。")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 載入 {len(cookies)} 個會員帳號執行簽到：")
    accounts = []
    for idx, c in enumerate(cookies, 1):
        name = get_user_display_name(c, idx)
        accounts.append((name, c))
        print(f"\n==============================")
        print(f"👤 開始執行 {name} 天天簽到...")
        print(f"==============================")
        try:
            run_daily_checkin(c, referral=args.referral, force=args.force, account_label=name)
        except Exception as e:
            print(f"[{name}] 簽到異常: {e}")

    if not args.no_share and not args.referral:
        try:
            run_mutual_share(accounts)
        except Exception as e:
            print(f"[簽到分享] 執行異常: {e}")


if __name__ == "__main__":
    main()
