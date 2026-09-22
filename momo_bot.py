#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 桃金日-好運抽抽樂 自動定時抽獎腳本
支援全自動掃描會場探測新活動網址 (lpn) 與代碼解析 (mPromoNo / dtPromoNo)
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
from concurrent.futures import ThreadPoolExecutor, as_completed

API_URL = "https://event.momoshop.com.tw/game/momoLottery.PROMO"
DEFAULT_EVENT_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O8dV4oaCUPZ&n=1"
DEFAULT_M_PROMO_NO = "U96091900001"
DEFAULT_DT_PROMO_NO = "D96091900001"

PORTAL_URLS = [
    "https://www.momoshop.com.tw/main/Main.jsp",
    "https://www.momoshop.com.tw/category/LgrpCategory.jsp?l_code=2000000000",
    "https://www.momoshop.com.tw/category/LgrpCategory.jsp?l_code=1000000000"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoshop/12.5.0"
}

RETURN_MESSAGES = {
    'OK': '成功',
    'D': '請於活動時間內參加活動',
    'W': '請於指定星期參加活動',
    'WP': '競標金額錯誤',
    'L': '請重新登入會員 (Cookie 已過期或無效)',
    'A': '已超過本時段抽獎次數上限！',
    'A_EX': '已超過本時段抽獎次數上限！',
    'EA': '已超過本時段抽獎次數上限！',
    'FULL': '名額已經額滿!!',
    'NOT_USED': '很抱歉，活動暫不開放',
    'NOT_APP': '請在momo APP參加活動',
    'NOT_WEB': '請在momo網頁版參加活動',
    'NOT_NC': '您非活動期間新客',
    'NOT_WFB': '您非活動期間首購',
    'NOT_APPFB': '您非活動期間APP首購',
    'NO_PT': '點數不足',
    'INS': '登記成功，感謝您對本活動的支持',
    'exchanged': '您今日已兌獎，恕無法再參加，請於明日再來~',
    'shared': '今日已分享該活動！',
    'linkedFriend': '已幫好友獲得金額1元！',
    'linked': '已有其他好友幫忙分享',
    'notshared': '此連結已過期，需請好友重新分享今日連結',
    'E_LINK': '不能分享給自己',
    'ERR': '很抱歉，目前系統繁忙，請稍後再試'
}

GIFT_NAMES = {
    "peach": "桃",
    "gold": "金",
    "day": "日",
    "mo_1": "1元",
    "mo_2": "2元",
    "mo_5": "5元",
    "mo_12": "12元",
    "mo_222": "222元"
}

SCHEDULE_TIMES = ["09:00", "13:00", "16:00", "19:00", "21:00"]

ACTIVE_CONFIG = {
    "url": DEFAULT_EVENT_URL,
    "m_promo_no": DEFAULT_M_PROMO_NO,
    "dt_promo_no": DEFAULT_DT_PROMO_NO,
    "title": "好運抽抽樂"
}


def fetch_page(url: str, timeout: int = 5) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def check_lpn(lpn: str):
    url = f"https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn={lpn}&n=1"
    content = fetch_page(url, timeout=4)
    if not content:
        return None, []

    if "gameConfig.js" in content and ("momoLottery" in content or "抽抽樂" in content):
        t = re.search(r"<title>([^<]+)</title>", content)
        title = t.group(1).strip() if t else ""
        return ("LOTTERY", url, title), []

    child_lpns = set(re.findall(r"lpn=([a-zA-Z0-9]+)", content))
    child_lpns.discard(lpn)
    return None, list(child_lpns)


def auto_detect_lottery_url() -> str:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 啟動全自動會場掃描，尋找最新抽抽樂活動網址...")
    initial_lpns = set()
    for portal in PORTAL_URLS:
        html = fetch_page(portal, timeout=8)
        found = re.findall(r"lpn=([a-zA-Z0-9]+)", html)
        initial_lpns.update(found)

    if not initial_lpns:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 未能從主會場取得活動清單。")
        return ""

    child_candidates = set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_lpn, lpn): lpn for lpn in initial_lpns}
        for future in as_completed(futures):
            res, children = future.result()
            if res and res[0] == "LOTTERY":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 第一層直接命中抽獎活動: {res[1]} ({res[2]})")
                return res[1]
            child_candidates.update(children)

    child_candidates.difference_update(initial_lpns)
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(check_lpn, lpn): lpn for lpn in child_candidates}
        for future in as_completed(futures):
            res, _ = future.result()
            if res and res[0] == "LOTTERY":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 第二層深度命中抽獎活動: {res[1]} ({res[2]})")
                return res[1]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 會場掃描結束，未發現進行中的抽抽樂活動。")
    return ""


def fetch_promo_config(edm_url: str):
    try:
        html = fetch_page(edm_url, timeout=10)
        js_match = re.search(r'src=[\"\']([^\"\']*gameConfig\.js[^\"\']*)[\"\']', html)
        if not js_match:
            return None

        js_url = js_match.group(1)
        if js_url.startswith("//"):
            js_url = "https:" + js_url

        js_content = fetch_page(js_url, timeout=10)
        m = re.search(r'mPromoNo\s*=\s*[\"\']([^\"\']+)[\"\']', js_content)
        dt = re.search(r'dtPromoNo\s*=\s*[\"\']([^\"\']+)[\"\']', js_content)
        t_m = re.search(r'gameConfig\.title\s*=\s*[\"\']([^\"\']+)[\"\']', js_content)
        st_m = re.search(r'gameConfig\.subtitle\s*=\s*[\"\']([^\"\']+)[\"\']', js_content)

        title = ((t_m.group(1) if t_m else "") + " " + (st_m.group(1) if st_m else "")).strip()
        m_no = m.group(1) if m else DEFAULT_M_PROMO_NO
        dt_no = dt.group(1) if dt else DEFAULT_DT_PROMO_NO

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 代碼解析成功: 活動='{title}', m_promo={m_no}, dt_promo={dt_no}")
        return {
            "url": edm_url,
            "m_promo_no": m_no,
            "dt_promo_no": dt_no,
            "title": title
        }
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 解析代碼異常: {e}")
        return None


def get_headers(cookie: str):
    return {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://www.momoshop.com.tw",
        "Referer": ACTIVE_CONFIG["url"],
        "Cookie": cookie.strip()
    }


def send_request(action: str, cookie: str):
    payload = {
        "doAction": action,
        "m_promo_no": ACTIVE_CONFIG["m_promo_no"],
        "dt_promo_no": ACTIVE_CONFIG["dt_promo_no"]
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=data, headers=get_headers(cookie), method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        return {"status": f"HTTP_ERROR_{e.code}"}
    except Exception as e:
        return {"status": f"ERROR_{str(e)}"}


def get_collection_summary(cookie: str):
    res = send_request("qry", cookie)
    if res.get("status") != "OK" or "data" not in res:
        return None
    data = res["data"]
    gift_codes = data.get("gift_code", [])
    insert_dates = data.get("insert_date", [])

    # 依時間由舊到新排序紀錄以計算輪次
    records = list(zip(insert_dates, gift_codes))
    records.sort(key=lambda x: x[0])

    completed_rounds = 0
    total_claimed_mo = 0
    current_round_mo = 0
    current_cards = {"peach": False, "gold": False, "day": False}

    for d, code in records:
        if code in current_cards:
            current_cards[code] = True
            # 當收集滿三個字（桃、金、日）時，該輪達成兌獎，金額與字卡歸零重新計算下一輪
            if all(current_cards.values()):
                completed_rounds += 1
                total_claimed_mo += current_round_mo
                current_round_mo = 0
                current_cards = {"peach": False, "gold": False, "day": False}
        elif code.startswith("mo_"):
            try:
                current_round_mo += int(code.split("_")[1])
            except Exception:
                pass

    collected = [GIFT_NAMES[k] for k, v in current_cards.items() if v]
    missing = [GIFT_NAMES[k] for k, v in current_cards.items() if not v]
    return {
        "total_draws": len(records),
        "total_mo": current_round_mo,
        "current_round_mo": current_round_mo,
        "completed_rounds": completed_rounds,
        "total_claimed_mo": total_claimed_mo,
        "collected": collected,
        "missing": missing,
        "is_complete": len(missing) == 0,
        "records": records
    }


def do_query(cookie: str):
    summary = get_collection_summary(cookie)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if not summary:
        print(f"[{now_str}] 查詢失敗或尚未有紀錄")
        return None

    collected_str = "".join(summary["collected"]) if summary["collected"] else "無"
    missing_str = "".join(summary["missing"]) if summary["missing"] else "無"
    print(f"[{now_str}] 檔期收集統計:")
    print(f"  • 累計抽獎次數: {summary['total_draws']} 次")
    if summary["completed_rounds"] > 0:
        print(f"  • 已集滿兌獎: {summary['completed_rounds']} 次 (累計已獲 {summary['total_claimed_mo']} 元)")
    print(f"  • 本輪累積 mo 點: {summary['current_round_mo']} 元")
    print(f"  • 本輪字卡進度: {len(summary['collected'])}/3 (已收集: {collected_str} | 缺: {missing_str})")
    print("  • 詳細紀錄:")
    for d, c in summary["records"]:
        print(f"    - {d}: {GIFT_NAMES.get(c, c)}")
    return summary


def do_draw(cookie: str):
    res = send_request("lottery", cookie)
    status = res.get("status")
    msg = RETURN_MESSAGES.get(status, status)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now_str}] 抽獎結果: 狀態={status} ({msg})")

    if status == "OK":
        prize = res.get("result", {}).get("prize", {})
        gift_code = prize.get("giftCode")
        gift_name = GIFT_NAMES.get(gift_code, gift_code)
        print(f"[{now_str}] 抽中: {gift_name}")
        if res.get("prizeStatus") == "PRIZE":
            total = res.get("total", "")
            print(f"[{now_str}] 集滿桃金日！獲得 mo 點: {total} 元")
    return res


def wait_until_slot_start(max_wait_seconds: int = 150):
    """
    若目前時間接近目標時段整點（例如 58 或 59 分），自動倒數至整點 :00:01 再發送抽獎請求
    """
    now = datetime.now()
    target_hours = [9, 13, 16, 19, 21]
    for th in target_hours:
        target_time = now.replace(hour=th, minute=0, second=1, microsecond=0)
        diff = (target_time - now).total_seconds()
        if 0 < diff <= max_wait_seconds:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 提早啟動，等待 {th:02d}:00:01 整點開放，倒數 {diff:.1f} 秒...")
            time.sleep(diff)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 整點已到，立即開始抽獎！")
            return


def run_session_draws(cookie: str, max_draws: int = 2, silent_if_limit: bool = False, wait_slot: bool = True):
    if wait_slot:
        wait_until_slot_start()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    time_slot = datetime.now().strftime('%H:%M')
    print(f"[{now_str}] 開始執行本時段抽獎...")
    draw_records = []

    for i in range(max_draws):
        res = do_draw(cookie)
        status = res.get("status")
        if status == "OK":
            prize = res.get("result", {}).get("prize", {})
            gift_name = GIFT_NAMES.get(prize.get("giftCode"), prize.get("giftCode"))
            draw_records.append(f"第 {i+1} 次：{gift_name}")
            if res.get("prizeStatus") == "PRIZE":
                total = res.get("total", "")
                draw_records.append(f"🎉 集滿桃金日！獲得 {total} mo點")
        elif status in ("A", "A_EX", "EA"):
            print("已達本時段上限，停止抽獎。")
            if not draw_records:
                draw_records.append("本時段次數已達上限")
            break
        elif status == "L":
            print("登入憑證失效，請更新 Cookie。")
            draw_records.append("⚠️ Cookie 已失效，請重新登入更新")
            break
        elif status in ("D", "NOT_USED"):
            print("活動未開放或已結束。")
            draw_records.append("活動未開放或已結束")
            break
        else:
            msg = RETURN_MESSAGES.get(status, status)
            draw_records.append(f"回應: {msg}")
            break
        if i < max_draws - 1:
            time.sleep(3)

    if silent_if_limit and draw_records == ["本時段次數已達上限"]:
        print("本時段已於先前抽獎完畢，備援排程略過推播。")
        return

    # 查詢檔期累積狀況
    time.sleep(1)
    summary = get_collection_summary(cookie)
    summary_lines = []
    if summary:
        col_str = "".join(summary["collected"]) if summary["collected"] else "無"
        mis_str = "".join(summary["missing"]) if summary["missing"] else "無"
        summary_lines.append("\n【本輪累積進度】")
        if summary.get("completed_rounds", 0) > 0:
            summary_lines.append(f"🏆 已集滿兌獎: {summary['completed_rounds']} 次 (累計已獲 {summary['total_claimed_mo']} 元)")
        summary_lines.append(f"💰 本輪累積 mo 點: {summary['current_round_mo']} 元")
        summary_lines.append(f"🃏 本輪字卡進度: {len(summary['collected'])}/3 ({col_str})")
        if summary['is_complete']:
            summary_lines.append("🎉 桃金日三字已集滿！")
        else:
            summary_lines.append(f"🔍 尚缺字卡: {mis_str}")

    # 發送 Bark 通知
    try:
        from notifier import send_bark
        body_text = f"【本時段 {time_slot}】\n" + "\n".join(draw_records) + ("\n" + "\n".join(summary_lines) if summary_lines else "")
        send_bark(f"momo 抽抽樂結果 ({time_slot})", body_text.strip())
    except Exception as e:
        print(f"發送推播通知異常: {e}")


def sync_active_config(event_url: str = None, force_scan: bool = False):
    """
    同步活動網址與代碼：
    1. 若未指定網址或指定網址已失效/force_scan，自動啟動會場掃描尋找最新活動
    2. 解析該活動代碼
    """
    target_url = event_url or os.getenv("MOMO_EVENT_URL", "")

    # 如果有指定網址且不強制掃描，先測試解析
    if target_url and not force_scan:
        parsed = fetch_promo_config(target_url)
        if parsed:
            ACTIVE_CONFIG.update(parsed)
            return

    # 嘗試全自動掃描會場
    detected_url = auto_detect_lottery_url()
    if detected_url:
        parsed = fetch_promo_config(detected_url)
        if parsed:
            ACTIVE_CONFIG.update(parsed)
            return

    # 若掃描無果但有預設網址，作為最後備用
    fallback_url = target_url or DEFAULT_EVENT_URL
    parsed = fetch_promo_config(fallback_url)
    if parsed:
        ACTIVE_CONFIG.update(parsed)


def run_scheduler(cookie: str, event_url: str):
    print(f"定時抽獎服務已啟動。預定觸發時段: {', '.join(SCHEDULE_TIMES)}")
    last_triggered_date_hour = ""

    while True:
        now = datetime.now()
        current_hm = now.strftime("%H:%M")
        current_dh = now.strftime("%Y-%m-%d_%H")

        if current_hm in SCHEDULE_TIMES and current_dh != last_triggered_date_hour:
            last_triggered_date_hour = current_dh
            sync_active_config(event_url)
            run_session_draws(cookie, max_draws=2)
            try:
                from momo_checkin import run_daily_checkin
                run_daily_checkin(cookie)
            except Exception as e:
                print(f"執行天天簽到異常: {e}")

        time.sleep(20)


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
    parser = argparse.ArgumentParser(description="Momo 桃金日抽抽樂自動腳本 (支援全自動活動探測)")
    parser.add_argument("--cookie", help="Momo 網站 Cookie 字串")
    parser.add_argument("--url", help="活動 EDM 網址 (留空則自動掃描會場尋找最新活動)")
    parser.add_argument("--scan", action="store_true", help="強制重新掃描全站活動會場尋找抽抽樂新網址")
    parser.add_argument("--now", action="store_true", help="立即執行一次抽獎流程 (最多抽 2 次)")
    parser.add_argument("--query", action="store_true", help="查詢當前抽獎與點數紀錄")
    parser.add_argument("--schedule", action="store_true", help="啟動定時輪詢 (09:00, 13:00, 16:00, 19:00, 21:00)")
    parser.add_argument("--silent-if-limit", action="store_true", help="若本時段已無抽獎額度則略過推播")
    parser.add_argument("--bark", help="Bark 推播 Key 或 URL")
    args = parser.parse_args()

    if args.bark:
        os.environ["BARK_KEY"] = args.bark

    cookie = load_cookie(args.cookie)
    if not cookie:
        print("錯誤: 未找到 Cookie。請透過 --cookie 指定，或將 Cookie 寫入同目錄下的 cookie.txt。")
        sys.exit(1)

    sync_active_config(event_url=args.url, force_scan=args.scan)

    if args.query:
        do_query(cookie)
    elif args.now:
        run_session_draws(cookie, max_draws=2, silent_if_limit=args.silent_if_limit)
    else:
        run_scheduler(cookie, args.url)


if __name__ == "__main__":
    main()
