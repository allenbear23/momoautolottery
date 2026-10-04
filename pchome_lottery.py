#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PChome 24h【幸運抽籤】最高搶188P幣 (~10/31) 自動搶抽腳本
活動網址: https://24h.pchome.com.tw/activity/AC78080335
支援檔期自動解析、上限預檢、輪詢開獎、中獎紀錄查詢與 Bark 即時推播
"""

import sys
import os
import time
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime

DEFAULT_ACTIVITY_ID = "AC78080335"
START_DATE = "2026/9/25"
END_DATE = "2026/11/7"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 PChome24h",
    "Origin": "https://24h.pchome.com.tw",
    "Referer": f"https://24h.pchome.com.tw/activity/{DEFAULT_ACTIVITY_ID}",
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


def get_activity_config(act_id: str = DEFAULT_ACTIVITY_ID):
    url = f"https://ecapi.pchome.com.tw/marketing/luckydraw/v1/activity/{act_id}?startDate={START_DATE}&endDate={END_DATE}&_callback=json_activity_data&_={int(time.time()*1000)}"
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            if text.startswith("json_activity_data(") and text.endswith(")"):
                text = text[len("json_activity_data("):-1]
            return json.loads(text)
    except Exception as e:
        print(f"[PChome] 取得活動資訊失敗: {e}")
        return None


def check_limit_reached(act_no: str, cookie: str) -> bool:
    url = f"https://ecapi.pchome.com.tw/marketing/luckydraw/v1/activity/{act_no}/isLimitReached"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, bool):
                return data
            if isinstance(data, dict):
                if data.get("code") == "400-001":
                    print("[PChome] 帳號尚未登入或 Cookie 無效")
                    return True
                return data.get("isLimitReached", False)
            return False
    except Exception as e:
        print(f"[PChome] 檢查次數上限異常: {e}")
        return False


def get_game_records(act_id: str, cookie: str):
    url = f"https://ecapi.pchome.com.tw/marketing/luckydraw/v1/winnerData/{act_id}?startDate={START_DATE}&endDate={END_DATE}&_callback=json_winner_data&_={int(time.time()*1000)}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            if text.startswith("json_winner_data(") and text.endswith(")"):
                text = text[len("json_winner_data("):-1]
            data = json.loads(text)
            return data
    except Exception as e:
        print(f"[PChome] 查詢獲獎紀錄異常: {e}")
        return None


def execute_draw(act_no: str, cookie: str, recaptcha_token: str = ""):
    url = f"https://ecapi.pchome.com.tw/marketing/luckydraw/v1/activity/{act_no}/lottery?_callback=json_lottery&_={int(time.time()*1000)}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie
    payload = {"reCaptchaToken": recaptcha_token}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(body)
        except Exception:
            return {"status": "fail", "code": str(e.code), "msg": body}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def query_winning_result(act_no: str, record_id: str, cookie: str, max_retries: int = 5):
    url = f"https://ecapi.pchome.com.tw/marketing/luckydraw/v1/activity/{act_no}/winning?id={record_id}&callback=json_lottery_activity&_={int(time.time()*1000)}"
    hdrs = dict(HEADERS)
    hdrs["Cookie"] = cookie

    for i in range(max_retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8")
                if text.startswith("json_lottery_activity(") and text.endswith(")"):
                    text = text[len("json_lottery_activity("):-1]
                data = json.loads(text)
                if data.get("status") == "init":
                    time.sleep(2)
                    continue
                return data
        except Exception as e:
            print(f"[PChome] 查詢結果重試 ({i+1}/{max_retries}): {e}")
            time.sleep(2)
    return {"status": "init_timeout"}


def run_account_lottery(account_idx: int, cookie: str, act_cfg: dict, act_id: str, notifier=None):
    tag = f"[帳號{account_idx}]"
    act_no = act_cfg.get("actNo")

    print(f"\n{tag} 開始執行 PChome 幸運抽籤...")

    # 1. 檢查是否達抽獎上限
    if check_limit_reached(act_no, cookie):
        print(f"{tag} ℹ️ 今日已抽過或已達活動抽籤上限，自動略過。")
        return

    # 2. 發送抽籤請求
    resp = execute_draw(act_no, cookie)
    status = resp.get("status")
    code = resp.get("code")
    msg = resp.get("msg", "")

    code_map = {
        "400-001": "尚未登入或 Cookie 已失效",
        "400-002": "設備不支援",
        "400-003": "活動已結束或未開啟",
        "400-004": "無參加資格",
        "400-005": "今日已抽過 (isPlayed)",
        "400-006": "餘額不足",
        "400-007": "活動尚未開始",
        "400-008": "reCAPTCHA 驗證失敗",
        "400-902": "獎項已全數抽完",
        "400-618": "系統繁忙"
    }

    if status != "done":
        desc = code_map.get(code, f"代碼: {code} / 訊息: {msg}")
        print(f"{tag} ❌ 抽籤失敗: {desc}")
        if notifier:
            notifier.send(
                title=f"PChome 抽籤失敗 ({tag})",
                body=f"原因: {desc}\n時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                group="pchome_lottery"
            )
        return

    record_id = resp.get("data", {}).get("id")
    print(f"{tag} 抽籤請求成功 (ID: {record_id})，正在確認中獎結果...")

    # 3. 輪詢確認最終中獎獎項
    win_res = query_winning_result(act_no, record_id, cookie)
    win_data = win_res.get("data", {})
    prize_name = win_data.get("pname", "未知名稱")
    prize_val = win_data.get("value", "0")

    if prize_val == "-1" or "銘謝" in prize_name:
        result_str = "銘謝惠顧，再接再厲！"
        print(f"{tag} 🎲 結果: {result_str}")
    else:
        result_str = f"🎉 恭喜抽中【{prize_name}】！"
        print(f"{tag} {result_str}")

    if notifier:
        notifier.send(
            title=f"PChome 幸運抽籤結果 ({tag})",
            body=f"{result_str}\n檔期: {act_no}\n時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            group="pchome_lottery"
        )


def main():
    parser = argparse.ArgumentParser(description="PChome 24h【幸運抽籤】最高搶188P幣自動搶抽腳本")
    parser.add_argument("--cookie", type=str, help="指定 PChome Cookie")
    parser.add_argument("--activity", type=str, default=DEFAULT_ACTIVITY_ID, help="活動代碼 (預設: AC78080335)")
    parser.add_argument("--query", action="store_true", help="僅查詢活動資訊與歷史獲獎紀錄")
    args = parser.parse_args()

    # 載入 notifier
    try:
        from notifier import Notifier
        notifier = Notifier()
    except Exception:
        notifier = None

    print("=" * 60)
    print("🎲 PChome 24h【幸運抽籤】最高搶188P幣 自動抽籤工具")
    print("=" * 60)

    # 取得當前活動配置
    act_cfg = get_activity_config(args.activity)
    if not act_cfg or not act_cfg.get("actNo"):
        print("[PChome] 無法取得目前檔期資訊，請稍後再試。")
        sys.exit(1)

    act_no = act_cfg.get("actNo")
    start_dt = act_cfg.get("startDateTime")
    end_dt = act_cfg.get("endDateTime")
    prizes = act_cfg.get("prize", [])

    print(f"📌 目前檔期編號: {act_no}")
    print(f"⏰ 有效時段: {start_dt} ~ {end_dt}")
    print("🎁 檔期獎項清單:")
    for p in prizes:
        print(f"   - {p.get('pname')} (價值: {p.get('value')})")

    # 載入所有帳號 Cookie
    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("\n⚠️ 找不到任何 PChome Cookie！")
        print("請在 pchome_cookie.txt 貼入 Cookie，或設定環境變數 PCHOME_COOKIE。")
        sys.exit(0)

    print(f"\n👥 成功載入 {len(cookies)} 組 PChome 帳號 Cookie。")

    # 若為純查詢模式
    if args.query:
        for idx, ck in enumerate(cookies, 1):
            print(f"\n--- [帳號{idx}] 歷史中獎紀錄 ---")
            records = get_game_records(args.activity, ck)
            if not records:
                print("查無中獎紀錄或 Cookie 已失效。")
            elif isinstance(records, list):
                if len(records) == 0:
                    print("目前尚無中獎紀錄。")
                for r in records:
                    print(f"   • {r.get('CreateDate', '')}: {r.get('PrizeName', '')}")
            else:
                print(f"紀錄回應: {records}")
        return

    # 執行各帳號抽籤
    for idx, ck in enumerate(cookies, 1):
        run_account_lottery(idx, ck, act_cfg, args.activity, notifier)


if __name__ == "__main__":
    main()
