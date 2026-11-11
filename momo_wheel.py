#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 11月幸運大轉盤 (https://momo.dm/jEnm2E) 自動轉盤與多帳號互助分享腳本
API: https://event.momoshop.com.tw/transationMGM.PROMO
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

WHEEL_EDM_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?npn=1vEHzhU667ij&n=1"
API_URL = "https://event.momoshop.com.tw/transationMGM.PROMO"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": WHEEL_EDM_URL,
    "Content-Type": "application/json;charset=utf-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

GIFT_NAMES = {
    "mo_1": "mo點$1",
    "mo_2": "mo點$2",
    "mo_30": "mo點$30",
    "mo_50": "mo點$50",
    "mo_100": "mo點$100",
    "mo_500": "mo點$500",
    "mo_888": "mo點$888",
    "coupon_300": "折價券300元",
    "coupon_300_2": "折價券300元",
    "coupon_300_3": "折價券300元",
    "coupon_500": "折價券500元",
    "coupon_500_2": "折價券500元",
    "coupon_700": "折價券700元",
}

RETURN_MESSAGES = {
    "OK": "成功",
    "0000": "成功",
    "D": "非活動時間",
    "W": "非指定星期",
    "L": "請重新登入會員 (Cookie 已過期或無效)",
    "A": "已超過抽獎次數上限",
    "A_EX": "已超過抽獎次數上限",
    "EA": "已超過抽獎次數上限",
    "FULL": "名額已經額滿",
    "NOT_USED": "活動暫不開放",
    "NOT_APP": "請在 momo APP 參加活動",
    "NOT_WEB": "請在 momo 網頁版參加活動",
    "INS": "登記成功",
    "shared": "今日已分享該活動",
    "linkedFriend": "已幫此好友獲得次數，無法重複獲得",
    "linked": "本週已有5位好友幫此用戶獲得轉盤獎勵",
    "notshared": "此連結已過期或今日尚未分享",
    "MAX": "活動期間被點擊次數已達上限",
    "E_LINK": "不能分享給自己",
    "ERR": "系統繁忙，請稍後再試",
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


def extract_ck_encust(cookie: str) -> str:
    m = re.search(r"ck_encust=([^;]+)", cookie)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    return ""


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


def promo_post(payload: dict, cookie: str, api_url: str = API_URL) -> dict:
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie.strip()

    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.post(
            api_url,
            json=payload,
            headers=hdrs,
            impersonate="chrome124",
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"status": f"HTTP_{resp.status_code}", "raw": resp.text[:200]}
    except ImportError:
        pass
    except Exception as e:
        return {"status": "ERR", "error": str(e)}

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(api_url, data=body, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"status": f"HTTP_{e.code}", "error": str(e)}
    except Exception as e:
        return {"status": "ERR", "error": str(e)}


def spin_account_until_blocked(acc: dict) -> tuple:
    """為單一帳號連續抽獎，直到本輪次數耗盡或需要分享解鎖。回傳 (won_prizes, can_need_share, expired)"""
    won_prizes = []
    cookie = acc["cookie"]
    name = acc["name"]

    infor = promo_post({"doAction": "infor"}, cookie)
    status = infor.get("status")
    if status == "L":
        print(f"[{name}] ❌ Cookie 已失效 (L)")
        return won_prizes, False, True
    if status not in ("OK", "0000"):
        msg = RETURN_MESSAGES.get(status, status)
        print(f"[{name}] 查詢轉盤資訊回應: {status} ({msg})")
        return won_prizes, False, False

    lottery_cnt = infor.get("lotteryCnt", 0)
    phase = infor.get("phase", 0)
    friend_cnt = infor.get("friendCnt", 0)
    print(f"[{name}] 狀態: 剩餘次數={lottery_cnt}, phase={phase}, 好友點擊={friend_cnt}")

    if lottery_cnt <= 0:
        return won_prizes, False, False

    needs_share = False
    for _ in range(5):
        res = promo_post({"doAction": "lottery"}, cookie)
        r_status = res.get("status")
        prize = res.get("prize")
        end_prize = res.get("end_prize")
        rem = res.get("lotteryCnt", lottery_cnt)

        if r_status == "L":
            print(f"[{name}] ❌ Cookie 已失效 (L)")
            return won_prizes, False, True

        if r_status in ("OK", "0000") and prize:
            p_name = GIFT_NAMES.get(prize, prize)
            won_prizes.append(p_name)
            print(f"[{name}] 🎉 轉盤中獎: {p_name} (剩餘次數: {rem})")
            if end_prize:
                ep_name = GIFT_NAMES.get(end_prize, end_prize)
                won_prizes.append(f"5輪加碼: {ep_name}")
                print(f"[{name}] 🎁 5輪額外獎勵: {ep_name}")
            if rem <= 0:
                break
            time.sleep(0.8)
            continue

        if (not r_status or r_status in ("OK", "0000")) and not prize:
            # phaseCnt > 0 時，回傳無 prize，需要分享讓好友點擊
            if rem > 0:
                print(f"[{name}] 🔒 需完成分享與好友點擊以解鎖下一輪 (剩餘次數={rem})")
                needs_share = True
            else:
                print(f"[{name}] 本週抽獎次數已達上限 (rem={rem})")
            break

        msg = RETURN_MESSAGES.get(r_status, str(res))
        print(f"[{name}] 抽獎停止: {r_status} ({msg})")
        if rem > 0 and r_status not in ("A", "A_EX", "EA", "D", "W", "NOT_USED", "FULL"):
            needs_share = True
        break

    return won_prizes, needs_share, False


def try_share_and_link(sharer: dict, all_accounts: list) -> bool:
    """觸發分享並嘗試由其他帳號協助點擊連結。成功解鎖回傳 True"""
    sharer_name = sharer["name"]
    sharer_cookie = sharer["cookie"]
    emp_id = sharer["ck_encust"]

    if not emp_id:
        print(f"[{sharer_name}] ⚠️ Cookie 缺少 ck_encust，無法產生專屬連結。")
        return False

    share_res = promo_post({"doAction": "share", "shareBy": "line"}, sharer_cookie)
    s_status = share_res.get("status")
    if s_status not in ("OK", "0000", "shared"):
        msg = RETURN_MESSAGES.get(s_status, str(share_res))
        print(f"[{sharer_name}] 分享呼叫回應: {s_status} ({msg})")
        if s_status == "L":
            return False
    else:
        print(f"[{sharer_name}] 📣 分享狀態確認 ({s_status})，準備由其他帳號互助點擊...")

    for helper in all_accounts:
        if helper["cookie"] == sharer_cookie:
            continue
        helper_name = helper["name"]
        link_res = promo_post({"doAction": "link", "employeeID": emp_id}, helper["cookie"])
        l_status = link_res.get("status")
        l_msg = RETURN_MESSAGES.get(l_status, str(link_res))
        print(f"  -> {helper_name} 點擊 {sharer_name} 連結: {l_status} ({l_msg})")

        if l_status in ("OK", "0000"):
            return True
        if l_status in ("linked", "MAX", "notshared"):
            # 此分享者已滿或今日未有效分享，不必再試其他 helper
            break
        # 若為 linkedFriend（此好友之前點過），換下一個好友帳號嘗試
        time.sleep(0.5)

    return False


def run_wheel(cookies: list, silent_if_limit: bool = False):
    accounts = []
    for idx, c in enumerate(cookies, 1):
        accounts.append({
            "idx": idx,
            "name": get_user_display_name(c, idx),
            "cookie": c,
            "ck_encust": extract_ck_encust(c),
            "prizes": [],
            "expired": False,
            "no_more_helpers": False,
        })

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🎡 開始執行 11月幸運大轉盤 ({len(accounts)} 組帳號)...")

    total_links = 0
    for round_no in range(1, 7):
        print(f"\n--- 第 {round_no} 輪掃描 ---")
        any_action = False
        need_share_list = []

        for acc in accounts:
            if acc["expired"]:
                continue
            prizes, needs_share, expired = spin_account_until_blocked(acc)
            if expired:
                acc["expired"] = True
                continue
            if prizes:
                acc["prizes"].extend(prizes)
                any_action = True
            if needs_share and not acc["no_more_helpers"]:
                need_share_list.append(acc)

        if len(accounts) >= 2 and need_share_list:
            for acc in need_share_list:
                if try_share_and_link(acc, accounts):
                    total_links += 1
                    any_action = True
                    time.sleep(0.8)
                else:
                    acc["no_more_helpers"] = True

        if not any_action:
            break

    # 彙整推播
    summary_lines = []
    has_expired = any(a["expired"] for a in accounts)
    for acc in accounts:
        if acc["expired"]:
            summary_lines.append(f"❌ {acc['name']}: Cookie 已失效")
        elif acc["prizes"]:
            summary_lines.append(f"🎉 {acc['name']}: " + ", ".join(acc["prizes"]))

    if total_links > 0:
        summary_lines.append(f"🤝 本次共完成 {total_links} 次帳號互助點擊解鎖")

    if summary_lines:
        print("\n=== 幸運大轉盤結果彙整 ===")
        for line in summary_lines:
            print(line)
        try:
            from notifier import send_bark
            send_bark("momo 幸運大轉盤結果", "\n".join(summary_lines))
        except Exception as e:
            print(f"發送推播異常: {e}")
    else:
        print("\n[幸運大轉盤] 本次無新增抽獎或解鎖紀錄。")
        if not silent_if_limit and has_expired:
            try:
                from notifier import send_bark
                send_bark("momo 幸運大轉盤提醒", "⚠️ 部分帳號 Cookie 已失效，請更新。")
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Momo 11月幸運大轉盤自動化與互助分享腳本")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    parser.add_argument("--silent-if-limit", action="store_true", help="若無新增抽獎結果則不發推播")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。")
        sys.exit(1)

    run_wheel(cookies, silent_if_limit=args.silent_if_limit)


if __name__ == "__main__":
    main()
