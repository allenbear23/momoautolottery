#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 幣 / 活動 Mo 點期滿提醒模組
=================================
1. 優先讀取活動 API 與活動頁文案之點數效期（天天簽到、當期整點抽獎/桃金日/紅包雨），
   於到期前 1 日與到期當日合併發送單一 Bark 推播提醒。
2. 若提供有效 Web Session Cookie，亦相容原本會員中心即時到期點數查詢。
"""

from __future__ import annotations

import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except Exception:
    TAIPEI_TZ = timezone(timedelta(hours=8))


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


load_dotenv()


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

    blocks = raw.split("---") if "---" in raw else raw.splitlines()
    for b in blocks:
        clean = b.strip()
        if not clean or clean.startswith("#"):
            continue
        if any(k in clean for k in ("LOGINSESSION", "st=", "_atrk", "isEN")):
            cookies.append(clean)

    return cookies


def send_bark_notification(title: str, body: str):
    try:
        from notifier import send_bark
        send_bark(title, body)
        return
    except Exception:
        pass

    bark_key = os.getenv("BARK_KEY", "").strip()
    if not bark_key:
        return
    try:
        url = bark_key if bark_key.startswith("http") else f"https://api.day.app/{bark_key}/"
        payload = {
            "title": title,
            "body": body,
            "group": "momo_coin",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[mo點期滿提醒] 發送推播異常: {e}")


def _parse_iso_date(iso_str: str) -> Optional[date]:
    if not iso_str:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso_str).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _parse_expiry_date_from_text(visible_text: str, ref_date: date) -> Optional[date]:
    """從活動頁可見文案萃取點數使用效期 (例如: 效期至11/22 23:59)"""
    for pat in (
        r"(?:mo點|mo幣)[^\n]{0,20}(?:使用)?效期(?:至|到)\s*(?:(20\d{2})/)?(\d{1,2})/(\d{1,2})",
        r"(?:使用)?效期(?:至|到)\s*(?:(20\d{2})/)?(\d{1,2})/(\d{1,2})",
    ):
        m = re.search(pat, visible_text)
        if m:
            y_s, mm_s, dd_s = m.groups()
            mm, dd = int(mm_s), int(dd_s)
            if y_s:
                yy = int(y_s)
            else:
                yy = ref_date.year + (1 if ref_date.month >= 11 and mm <= 2 else 0)
            try:
                return date(yy, mm, dd)
            except ValueError:
                continue
    return None


def _ma_get_json(url: str, cookie: str = "") -> dict:
    """呼叫 ma.momoshop.com.tw API (優先使用 curl_cffi 繞過 TLS/Akamai 403，失敗改用 urllib)"""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoshop/12.1.0",
        "Origin": "https://ma.momoshop.com.tw",
        "Referer": "https://ma.momoshop.com.tw/edm/dailycheckin",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie:
        hdrs["Cookie"] = cookie.strip()

    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, headers=hdrs, impersonate="chrome124", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass

    try:
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def _check_dailycheckin_expiry(cookies: list, today: date) -> Optional[dict]:
    """讀取天天簽到檔期之點數到期日與各帳號累計已領 mo 點"""
    base = "https://ma.momoshop.com.tw/api/campaign/game"
    mission = _ma_get_json(f"{base}/latest")
    if not isinstance(mission, dict) or not mission.get("mission_id"):
        return None

    mission_id = mission["mission_id"]
    name = mission.get("display_name") or "天天簽到"
    expire_iso = (mission.get("reward_expire") or {}).get("end_at") or mission.get("end_at")
    expire_date = _parse_iso_date(expire_iso)
    if not expire_date:
        return None

    account_amounts = []
    for idx, ck in enumerate(cookies, 1):
        lbl = get_user_display_name(ck, idx)
        act = _ma_get_json(f"{base}/{mission_id}/activity", cookie=ck)
        claimed = (act.get("reward_ledger") or {}).get("claimed_amount", 0) if isinstance(act, dict) else 0
        if claimed and claimed > 0:
            account_amounts.append(f"{lbl}: {claimed}點")

    return {
        "name": name,
        "expire_date": expire_date,
        "days_left": (expire_date - today).days,
        "account_amounts": account_amounts,
        "has_known_amounts": True,
    }


def _query_game_cycle_earned_mo(cookie: str, campaign: dict) -> int:
    """統計單一帳號於桃金日/抽抽樂全檔期中「已集齊字卡並歸戶」的 mo 點總和"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
        "Cookie": cookie.strip(),
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": campaign.get("url", "https://www.momoshop.com.tw/"),
    }
    payload = {
        "doAction": "qry",
        "m_promo_no": campaign["m_promo_no"],
        "dt_promo_no": campaign["dt_promo_nos"][0],
    }
    try:
        req = urllib.request.Request(
            campaign["api_url"],
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return 0

    if res.get("status") != "OK":
        return 0

    data = res.get("data", {})
    dates = data.get("insert_date", [])
    codes = data.get("gift_code", [])
    required_words = set((campaign.get("word_gifts") or {"peach": "桃", "gold": "金", "day": "日"}).keys())

    per_day = {}
    for d_str, code in zip(dates, codes):
        day_key = str(d_str)[:10]
        entry = per_day.setdefault(day_key, {"mo": 0, "words": set()})
        if code.startswith("mo_"):
            try:
                entry["mo"] += int(code.split("_", 1)[1])
            except ValueError:
                pass
        elif code in required_words:
            entry["words"].add(code)

    total_earned = 0
    for entry in per_day.values():
        if required_words and required_words.issubset(entry["words"]):
            total_earned += entry["mo"]
    return total_earned


def _check_active_redpacket_expiry(cookies: list, today: date) -> Optional[dict]:
    """讀取當期整點抽獎/桃金日/紅包雨活動之 mo 點使用效期與已領點數"""
    try:
        import momo_redpacket as mr
    except Exception as e:
        print(f"[期滿檢查] 無法載入 momo_redpacket: {e}")
        return None

    campaign = mr.discover_active_campaign(today=today)
    if not campaign:
        return None

    html = mr.fetch_page_text(campaign["url"], timeout=8)
    vis = mr.extract_visible_text(html) if html else ""
    expire_date = _parse_expiry_date_from_text(vis, today)
    if not expire_date:
        ranges = campaign.get("date_ranges") or []
        if ranges:
            expire_date = max(e for _, e in ranges)
    if not expire_date:
        return None

    name = (campaign.get("title") or "當期抽獎活動").replace(" - momo購物網", "").strip()
    is_game_api = "momoLottery.PROMO" in campaign.get("api_url", "")

    account_amounts = []
    if is_game_api:
        for idx, ck in enumerate(cookies, 1):
            lbl = get_user_display_name(ck, idx)
            earned = _query_game_cycle_earned_mo(ck, campaign)
            if earned > 0:
                account_amounts.append(f"{lbl}: {earned}點")

    return {
        "name": name,
        "expire_date": expire_date,
        "days_left": (expire_date - today).days,
        "account_amounts": account_amounts,
        "has_known_amounts": is_game_api,
    }


def check_campaign_expiries(
    cookies: list,
    days_ahead: int = 1,
    today: Optional[date] = None,
    force_notify: bool = False,
    dry_run: bool = False,
) -> dict:
    """檢查進行中活動之 mo 點效期，於到期前 days_ahead 天內合併推播 1 則提醒"""
    if today is None:
        today = taipei_now().date()

    print(f"[{taipei_now().strftime('%H:%M:%S')}] 檢查活動 mo 點期滿日程 (今日: {today.strftime('%Y/%m/%d')}，提醒門檻: <= {days_ahead} 天)...")

    items = []
    for checker in (_check_dailycheckin_expiry, _check_active_redpacket_expiry):
        try:
            info = checker(cookies, today)
            if info:
                items.append(info)
        except Exception as e:
            print(f"[期滿檢查] 檢查異常: {e}")

    expiring_lines = []
    for info in items:
        d_left = info["days_left"]
        exp_str = info["expire_date"].strftime("%m/%d")
        amt_str = "、".join(info["account_amounts"]) if info["account_amounts"] else ("無已歸戶點數" if info["has_known_amounts"] else "請至會員中心確認餘額")
        print(f"  • {info['name']} | 到期日: {exp_str} 23:59 (剩 {d_left} 天) | {amt_str}")

        should_alert = (0 <= d_left <= days_ahead) or force_notify
        if not should_alert:
            continue
        if info["has_known_amounts"] and not info["account_amounts"] and not force_notify:
            continue

        day_tag = "今天 23:59 到期" if d_left == 0 else (f"明天 ({exp_str}) 23:59 到期" if d_left == 1 else f"{exp_str} 23:59 到期")
        expiring_lines.append(f"• {info['name']}（{day_tag}）\n  {amt_str}")

    if expiring_lines:
        title = "⏰ momo 活動 mo點即將到期提醒"
        body = "\n".join(expiring_lines) + "\n\n※ 僅依活動規則與已領紀錄提醒，實際餘額請以 APP 為準。"
        print(f"\n📨 期滿提醒內容：\n{title}\n{body}")
        if not dry_run:
            send_bark_notification(title, body)
        return {"status": "EXPIRING_FOUND", "items": items, "notified": not dry_run}

    print("[期滿檢查] 目前無即將到期之活動 mo 點。")
    return {"status": "NO_EXPIRING", "items": items, "notified": False}


def main():
    parser = argparse.ArgumentParser(description="Momo 活動 mo 點期滿提醒工具 (支援多帳號)")
    parser.add_argument("--cookie", help="Momo 網站 Cookie (多帳號可用換行或 --- 分隔)")
    parser.add_argument("--days-ahead", type=int, default=1, help="提前幾天開始提醒 (預設 1：前一天與到期當天各提醒一次)")
    parser.add_argument("--force-notify", action="store_true", help="強制發送一次提醒 (用於測試)")
    parser.add_argument("--dry-run", action="store_true", help="僅印出期滿檢查結果，不發送 Bark 推播")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。請透過 --cookie 指定，或將 Cookie 寫入 cookie.txt。")
        sys.exit(1)

    print(f"[{taipei_now().strftime('%H:%M:%S')}] 載入 {len(cookies)} 組帳號執行活動 mo 點期滿檢查：")
    check_campaign_expiries(
        cookies=cookies,
        days_ahead=args.days_ahead,
        force_notify=args.force_notify,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

