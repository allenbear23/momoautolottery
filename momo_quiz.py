#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Momo 雙11 知識王 (10/23 - 10/31) 自動答題與賺 mo 幣腳本
支援多帳號、題庫持久化累積學習、時段預熱與精準啟動、獎勵兌換與 Bark 推播
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
import concurrent.futures

DEFAULT_EVENT_URL = "https://momo.dm/BreIZI"
QUIZ_ACTIVITY_ID = "3008445a-40b4-4227-a9cc-db0bdae289a5"
API_BASE = "https://event.momoshop.com.tw"

# 10/23-10/31 每日 6 個時段 (均為 11 分)
SLOTS = [
    (10, 11),
    (12, 11),
    (14, 11),
    (18, 11),
    (20, 11),
    (22, 11)
]
SCHEDULE_TIMES = [f"{h:02d}:{m:02d}" for h, m in SLOTS]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 momoShop",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/edm/cmmedm.jsp?npn=1vEJn4Ny1oqt&n=1"
}

DB_FILE = os.path.join(os.path.dirname(__file__), "quiz_db.json")


def load_quiz_db() -> dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"questions": {}}


def save_quiz_db(db: dict):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"儲存題庫異常: {e}")


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


def send_quiz_request(method: str, path: str, cookie: str, body: dict = None):
    url = f"{API_BASE}{path}"
    headers = dict(HEADERS)
    headers["Cookie"] = cookie.strip()
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            return e.code, err_data
        except Exception:
            return e.code, {"code": f"HTTP_ERROR_{e.code}"}
    except Exception as e:
        return 0, {"code": "NETWORK_ERROR", "detail": str(e)}


def prewarm_connection(cookie: str):
    """預熱連線"""
    try:
        send_quiz_request("GET", f"/quiz/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
    except Exception:
        pass


def get_gemini_api_keys(api_key: str = None) -> list:
    keys = []
    raw = ""
    if api_key:
        raw = api_key
    elif os.getenv("GEMINI_API_KEY"):
        raw = os.getenv("GEMINI_API_KEY", "")
    else:
        key_file = os.path.join(os.path.dirname(__file__), "gemini_key.txt")
        if os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    raw = f.read()
            except Exception:
                pass

    for line in raw.replace(",", "\n").splitlines():
        k = line.strip()
        if k and not k.startswith("#") and k not in keys:
            keys.append(k)
    return keys


def query_gemini(question_text: str, choices: list, api_key: str = None, question_image: str = None) -> str:
    """利用 Google Gemini API 進行即時智能判題 (支援圖文多模態)"""
    keys = get_gemini_api_keys(api_key)
    if not keys:
        return None

    options_list = []
    choice_image_parts = []
    for i, c in enumerate(choices):
        t = c.get('text', '').strip()
        img_url = c.get('image', '').strip()
        if not t and img_url:
            filename = os.path.basename(urllib.parse.urlparse(img_url).path)
            t = f"圖片選項 ({filename})"
        options_list.append(f"{i+1}. {t}")

        if img_url:
            try:
                c_img_data = None
                c_mime = "image/jpeg"
                if img_url.startswith("http"):
                    req_img = urllib.request.Request(img_url, headers=HEADERS)
                    with urllib.request.urlopen(req_img, timeout=3) as img_resp:
                        c_img_data = img_resp.read()
                        c_mime = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                elif os.path.exists(img_url):
                    with open(img_url, "rb") as f:
                        c_img_data = f.read()
                if c_img_data:
                    choice_image_parts.append({"text": f"【選項 {i+1} 圖片】："})
                    choice_image_parts.append({
                        "inlineData": {
                            "mimeType": c_mime,
                            "data": base64.b64encode(c_img_data).decode("utf-8")
                        }
                    })
            except Exception:
                pass

    options_str = "\n".join(options_list)

    try:
        from momo_knowledge_base import MOMO_KNOWLEDGE_CONTEXT
        momo_context = MOMO_KNOWLEDGE_CONTEXT
    except Exception:
        momo_context = ""

    prompt = (
        f"你是一個精通台灣 momo 購物網活動與商品通識的解題專家。\n\n"
        f"{momo_context}\n"
        f"請閱讀問題、參考附帶圖片 (含題目圖片與各選項圖片)，並比對選項，選出最可能正確的選項：\n\n"
        f"【問題】：{question_text}\n"
        f"【選項】：\n{options_str}\n\n"
        f"請只回答最正確選項的編號數字 (例如 1, 2, 3 或 4)，絕對不要輸出任何其他多餘文字。"
    )

    parts = []
    if question_image:
        try:
            img_data = None
            mime = "image/jpeg"
            if question_image.startswith("http"):
                req_img = urllib.request.Request(question_image, headers=HEADERS)
                with urllib.request.urlopen(req_img, timeout=4) as img_resp:
                    img_data = img_resp.read()
                    mime = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
            elif os.path.exists(question_image):
                with open(question_image, "rb") as f:
                    img_data = f.read()

            if img_data:
                b64_data = base64.b64encode(img_data).decode("utf-8")
                parts.append({"text": "【題目附圖】："})
                parts.append({
                    "inlineData": {
                        "mimeType": mime,
                        "data": b64_data
                    }
                })
        except Exception:
            pass

    if choice_image_parts:
        parts.extend(choice_image_parts)

    parts.append({"text": prompt})

    models = [
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-3.1-pro-preview",
        "gemini-pro-latest"
    ]

    for key in keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.0,
                    "maxOutputTokens": 600
                }
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    candidates = result.get("candidates", [])
                    if candidates:
                        parts_list = candidates[0].get("content", {}).get("parts", [])
                        non_thought = [p.get("text", "") for p in parts_list if not p.get("thought", False)]
                        text_out = " ".join(non_thought).strip() if non_thought else " ".join(p.get("text", "") for p in parts_list).strip()

                        m = re.search(r'\b([1-9])\b', text_out)
                        if m:
                            idx = int(m.group(1)) - 1
                            if 0 <= idx < len(choices):
                                print(f"[{model}] 解析選項為: {idx+1}. {choices[idx].get('text')}")
                                return choices[idx]["uuid"]
                        for idx, c in enumerate(choices):
                            if c.get("text") and c.get("text") in text_out:
                                print(f"[{model}] 命中關鍵字: {c.get('text')}")
                                return c["uuid"]
            except Exception:
                continue

    return None


def search_best_choice(question_text: str, choices: list, known_wrong: list) -> str:
    """利用關鍵字搜尋比對最佳選項"""
    filtered_choices = [c for c in choices if c["uuid"] not in known_wrong and c.get("text") not in known_wrong]
    if not filtered_choices:
        filtered_choices = choices

    if len(filtered_choices) == 1:
        return filtered_choices[0]["uuid"]

    # 嘗試 Wikipedia 搜尋比對
    try:
        clean_q = re.sub(r'[^\w\s]', ' ', question_text).strip()
        url = 'https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch=' + urllib.parse.quote(clean_q) + '&format=json'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            snippet = ' '.join(item['snippet'] for item in data.get('query', {}).get('search', []))
            best_choice = None
            max_cnt = -1
            for c in filtered_choices:
                t = c.get('text', '')
                if t:
                    cnt = snippet.count(t)
                    if cnt > max_cnt:
                        max_cnt = cnt
                        best_choice = c['uuid']
            if max_cnt > 0 and best_choice:
                return best_choice
    except Exception:
        pass

    # 預設回傳第一個合法選項
    return filtered_choices[0]["uuid"]


def get_question_key(question: dict) -> str:
    """產生題目唯一鍵值，若有圖片則結合圖片檔名以防同名題目覆蓋"""
    q_text = question.get("text", "").strip()
    q_img = question.get("image", "").strip()
    q_uuid = question.get("uuid", "").strip()
    if q_img:
        img_name = os.path.basename(urllib.parse.urlsplit(q_img).path)
        return f"{q_text}::img_{img_name}" if q_text else f"img_{img_name}"
    return q_text or q_uuid


def select_answer(question: dict, choices: list, db: dict, gemini_key: str = None) -> str:
    q_text = question.get("text", "").strip()
    key = get_question_key(question)

    record = db["questions"].get(key, {})
    # 兼顧舊格式 (若 key 為題目純文字)
    if not record and q_text:
        record = db["questions"].get(q_text, {})

    correct_val = record.get("correct")
    wrong_vals = record.get("wrong", [])

    # 1. 命中題庫已知正確答案
    if correct_val:
        target_uuid = correct_val.get("uuid") if isinstance(correct_val, dict) else correct_val
        target_text = correct_val.get("text") if isinstance(correct_val, dict) else correct_val
        target_img = correct_val.get("image", "") if isinstance(correct_val, dict) else ""
        for c in choices:
            c_uuid = c.get("uuid")
            c_text = c.get("text")
            c_img = c.get("image", "")
            if (c_uuid and c_uuid == target_uuid) or \
               (c_text and c_text == target_text) or \
               (c_img and target_img and os.path.basename(c_img) == os.path.basename(target_img)):
                print(f"[題庫命中] 選擇已確認之正確答案: {c_text or c_uuid}")
                return c_uuid

    # 2. 排除已知錯誤選項
    def is_wrong(c):
        for w in wrong_vals:
            w_uuid = w.get("uuid") if isinstance(w, dict) else w
            w_text = w.get("text") if isinstance(w, dict) else w
            w_img = w.get("image", "") if isinstance(w, dict) else ""
            if c.get("uuid") and c.get("uuid") == w_uuid:
                return True
            if c.get("text") and c.get("text") == w_text:
                return True
            if c.get("image") and w_img and os.path.basename(c.get("image")) == os.path.basename(w_img):
                return True
        return False

    candidate_choices = [c for c in choices if not is_wrong(c)]
    if not candidate_choices:
        candidate_choices = choices

    if len(candidate_choices) == 1:
        print(f"[排除法] 已排除其他錯誤選項，選取唯一剩餘選項: {candidate_choices[0].get('text') or candidate_choices[0]['uuid']}")
        return candidate_choices[0]["uuid"]

    # 3. 呼叫 Gemini AI 解題 (支援圖文多模態)
    gemini_choice_id = query_gemini(q_text, candidate_choices, gemini_key, question.get("image"))
    if gemini_choice_id:
        return gemini_choice_id

    # 4. 搜尋比對或排除法回退
    return search_best_choice(q_text, candidate_choices, wrong_vals)


def run_quiz_session(cookie: str, account_label: str = "", auto_claim: bool = True, gemini_key: str = None):
    prefix = f"[{account_label}] " if account_label else ""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. 檢查紀錄與今日是否已兌換
    status, rec = send_quiz_request("GET", f"/quiz/record/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
    today_str = datetime.now().strftime('%Y-%m-%d')
    has_claimed_today = False
    current_points = 0

    if status == 200:
        prize_records = rec.get("prizeRecords", [])
        for pr in prize_records:
            if pr.get("insertDate", "").startswith(today_str):
                has_claimed_today = True
                break
        point_records = rec.get("pointRecords", [])
        for p in point_records:
            if p.get("insertDate", "").startswith(today_str):
                current_points += p.get("point", 0)

    display_points = current_points * 10
    print(f"[{now_str}] {prefix}今日累計積分: {display_points} 分 (後端 {current_points} 分)，今日已兌換: {has_claimed_today}")

    if has_claimed_today:
        print(f"{prefix}今日獎勵已兌換，略過本日答題。")
        return {
            "account_label": account_label,
            "correct_count": 0,
            "total_points": display_points,
            "status": "今日已兌換",
            "prize_claimed": None
        }

    # 2. 開始遊戲
    status, start_res = send_quiz_request("POST", f"/quiz/start/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
    if status != 200:
        err_code = start_res.get("code", "")
        err_msg = start_res.get("detail", start_res.get("title", str(start_res)))
        if err_code == "ALREADY_STARTED":
            print(f"{prefix}本時段限玩 1 次，已經參加過囉！")
            return {"account_label": account_label, "correct_count": 0, "total_points": display_points, "status": "本時段已玩過", "prize_claimed": None}
        elif err_code in ("NOT_IN_PERIOD", "ACTIVITY_NOT_IN_PROGRESS"):
            print(f"{prefix}非開放時段或活動未開始: {err_msg}")
            return {"account_label": account_label, "correct_count": 0, "total_points": display_points, "status": "非開放時段", "prize_claimed": None}
        else:
            print(f"{prefix}開始遊戲失敗: {err_code} ({err_msg})")
            return {"account_label": account_label, "correct_count": 0, "total_points": display_points, "status": f"錯誤: {err_code}", "prize_claimed": None}

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}🚀 成功進入知識王遊戲！限時 60 秒...")

    db = load_quiz_db()
    correct_count = 0
    start_time = time.time()

    # 3. 循環答題
    while time.time() - start_time < 58:
        status, q_data = send_quiz_request("GET", f"/quiz/question/{QUIZ_ACTIVITY_ID}.PROMO", cookie)
        if status != 200:
            print(f"{prefix}取題結束: {q_data.get('code')}")
            break

        question = q_data.get("question", {})
        choices = q_data.get("choices", [])
        q_text = question.get("text", "")
        q_uuid = question.get("uuid", "")
        db_key = get_question_key(question)

        if not choices:
            break

        selected_choice_id = select_answer(question, choices, db, gemini_key=gemini_key)
        selected_choice_obj = next((c for c in choices if c["uuid"] == selected_choice_id), choices[0])
        choice_text = selected_choice_obj.get("text", "") or selected_choice_obj.get("uuid", "")
        choice_obj = {
            "uuid": selected_choice_obj.get("uuid", ""),
            "text": selected_choice_obj.get("text", ""),
            "image": selected_choice_obj.get("image", "")
        }

        print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}第 {correct_count+1} 題: {q_text} ➔ 選擇: {choice_text}")

        # 送出答案
        ans_body = {
            "activityId": QUIZ_ACTIVITY_ID,
            "questionId": q_uuid,
            "answerId": selected_choice_id
        }
        ans_status, ans_res = send_quiz_request("POST", "/quiz/answer.PROMO", cookie, ans_body)
        if ans_status != 200:
            print(f"{prefix}提交答案異常: {ans_res}")
            break

        is_correct = ans_res.get("isCorrect", False)
        if db_key not in db["questions"]:
            db["questions"][db_key] = {}

        q_record = db["questions"][db_key]
        q_record.update({
            "text": q_text,
            "image": question.get("image", ""),
            "uuid": q_uuid,
            "choices": choices,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        if is_correct:
            correct_count += 1
            print(f"🎉 {prefix}第 {correct_count} 題答對！(+10 分)")
            q_record["correct"] = choice_obj
            save_quiz_db(db)
            time.sleep(0.3)
        else:
            print(f"❌ {prefix}回答錯誤，本場時段結束。")
            wrongs = q_record.setdefault("wrong", [])
            if not any(
                (w.get("uuid") == choice_obj["uuid"] or (w.get("text") and w.get("text") == choice_obj["text"]))
                if isinstance(w, dict) else w == (choice_obj["text"] or choice_obj["uuid"])
                for w in wrongs
            ):
                wrongs.append(choice_obj)
            save_quiz_db(db)
            break

    total_display_points = (current_points + correct_count) * 10
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}🏁 答題結束！本場答對: {correct_count} 題，累計積分: {total_display_points} 分")

    # 4. 判斷兌換門檻 (若達到 60 分滿分兌換 $50 mo 點，或 22:11 最後一場達到 >= 30 分)
    prize_claimed = None
    if auto_claim and not has_claimed_today:
        now_hour = datetime.now().hour
        is_last_slot = (now_hour >= 22)
        should_claim = (total_display_points >= 60) or (is_last_slot and total_display_points >= 30)

        if should_claim:
            print(f"{prefix}滿足兌換門檻 ({total_display_points}分)，發動兌換獎勵...")
            claim_status, claim_res = send_quiz_request("POST", "/quiz/claim.PROMO", cookie, {"activityId": QUIZ_ACTIVITY_ID})
            if claim_status == 200:
                prize_name = claim_res.get("prize", {}).get("displayName", "獎項")
                prize_claimed = prize_name
                print(f"🎁 {prefix}兌換成功！獲得: {prize_name}")
            else:
                print(f"{prefix}兌換回應: {claim_res}")

    return {
        "account_label": account_label,
        "correct_count": correct_count,
        "total_points": total_display_points,
        "status": f"答對 {correct_count} 題",
        "prize_claimed": prize_claimed
    }


def get_current_slot_info(now: datetime = None):
    if now is None:
        now = datetime.now()

    best_slot = None
    min_future_diff = float("inf")

    for sh, sm in SLOTS:
        slot_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        diff = (slot_dt - now).total_seconds()
        # 開跑前 4 分鐘到開跑後 1 小時內鎖定
        if -3600 <= diff <= 240:
            best_slot = (sh, sm)
            break
        if diff > 0 and diff < min_future_diff:
            min_future_diff = diff
            best_slot = (sh, sm)

    if not best_slot:
        best_slot = SLOTS[0]

    slot_hour, slot_min = best_slot
    slot_time_str = f"{slot_hour:02d}:{slot_min:02d}"
    return slot_hour, slot_min, slot_time_str


def wait_until_slot_snipe(slot_hour: int, slot_minute: int, cookies: list, max_wait_seconds: int = 240):
    now = datetime.now()
    target_time = now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
    diff = (target_time - now).total_seconds()

    if diff <= 0 or diff > max_wait_seconds:
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 鎖定時段 {slot_hour:02d}:{slot_minute:02d}，距離開答剩 {diff:.1f} 秒，倒數中...")

    if diff > 3.5:
        time.sleep(diff - 3.5)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 剩餘 3.5 秒，預熱連線...")
    for c in cookies:
        prewarm_connection(c)

    rem = (target_time.timestamp() - 0.2) - time.time()
    if rem > 0:
        time.sleep(rem)

    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🚀 到達開搶點 (T-0.2s)，啟動答題流程！")


def run_session(cookies: list, slot_hour: int = None, slot_minute: int = None, silent_if_limit: bool = False, wait_snipe: bool = True, gemini_key: str = None):
    if slot_hour is not None and slot_minute is not None:
        target_hour = slot_hour
        target_min = slot_minute
        slot_time_str = f"{target_hour:02d}:{target_min:02d}"
    else:
        target_hour, target_min, slot_time_str = get_current_slot_info()

    if wait_snipe:
        wait_until_slot_snipe(target_hour, target_min, cookies)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 目標時段: {slot_time_str}，多帳號並行答題中...")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(cookies))) as executor:
        future_to_idx = {
            executor.submit(run_quiz_session, c, get_user_display_name(c, idx), True, gemini_key): idx
            for idx, c in enumerate(cookies, 1)
        }
        for fut in concurrent.futures.as_completed(future_to_idx):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"account_label": "帳號", "status": f"異常: {e}"})

    # 推播彙整
    report_lines = []
    has_meaningful = False
    for r in results:
        label = r.get("account_label", "")
        status = r.get("status", "")
        pts = r.get("total_points", 0)
        claimed = r.get("prize_claimed")
        line = f"👤 {label}：{status} (今日累計: {pts}分)"
        if claimed:
            line += f" ➔ 🎁 成功領取: {claimed}"
        report_lines.append(line)
        if "答對" in status or claimed:
            has_meaningful = True

    if silent_if_limit and not has_meaningful:
        print("所有帳號均已兌換、非開放時段或已答題過，略過推播。")
        return

    try:
        from notifier import send_bark
        body = f"【雙11 momo知識王 ({slot_time_str}) 報告】\n\n" + "\n".join(report_lines)
        send_bark(f"momo 知識王結果 ({slot_time_str})", body.strip())
    except Exception as e:
        print(f"推播通知異常: {e}")


def main():
    parser = argparse.ArgumentParser(description="Momo 雙11知識王自動答題搶 mo 幣")
    parser.add_argument("--cookie", help="Cookie 字串")
    parser.add_argument("--gemini-key", help="Google Gemini API Key")
    parser.add_argument("--now", action="store_true", help="立即執行搶答流程")
    parser.add_argument("--force", action="store_true", help="強制立即執行（無視時段窗口與開搶倒數）")
    parser.add_argument("--test-demo", action="store_true", help="執行示範題 AI 讀題測試")
    parser.add_argument("--query", action="store_true", help="查詢今日積分與兌換狀態")
    parser.add_argument("--silent-if-limit", action="store_true", help="略過重複推播")
    args = parser.parse_args()

    gemini_keys = get_gemini_api_keys(args.gemini_key)
    gemini_key = gemini_keys[0] if gemini_keys else ""

    if args.test_demo:
        demo_img = "/Users/allen/.gemini/antigravity-ide/brain/3b9f5804-fd76-44a9-bd44-dbde2ae057ec/.tempmediaStorage/media_1792682302310.png"
        if not os.path.exists(demo_img):
            demo_img = "https://img1.momoshop.com.tw/ecm/img/online/10/007/04/648/images/game_start.gif?t=1792670445872"

        demo_questions = [
            {
                "title": "示範題 1（圖文題：書桌與電腦椅）",
                "text": "圖中商品屬於哪一個館別？",
                "image": demo_img,
                "choices": [
                    {"uuid": "choice_1", "text": "3C家電館"},
                    {"uuid": "choice_2", "text": "日用清潔館"},
                    {"uuid": "choice_3", "text": "流行時尚館"},
                    {"uuid": "choice_4", "text": "家具寢飾/居家生活館"}
                ]
            },
            {
                "title": "示範題 2（活動常識題：代言人）",
                "text": "下列何者是本次活動的主視覺代言人？",
                "image": None,
                "choices": [
                    {"uuid": "c1", "text": "SUPER JUNIOR-83z"},
                    {"uuid": "c2", "text": "五月天"},
                    {"uuid": "c3", "text": "告五人"},
                    {"uuid": "c4", "text": "蔡依林"}
                ]
            }
        ]

        for dq in demo_questions:
            print(f"\n=== 【{dq['title']}】 ===")
            print(f"題目：{dq['text']}")
            if dq['image']:
                print(f"附圖：{dq['image']}")
            print("選項：")
            for i, c in enumerate(dq['choices'], 1):
                print(f"  {i}. {c['text']}")

            ans_id = query_gemini(dq['text'], dq['choices'], api_key=gemini_key, question_image=dq['image'])
            ans_obj = next((c for c in dq['choices'] if c['uuid'] == ans_id), None)
            if ans_obj:
                print(f"🎯 AI 判定答案：{ans_obj['text']} (UUID: {ans_id})")
            else:
                print("❌ AI 未能成功解析答案。")
            time.sleep(1.0)
        return

    cookies = load_all_cookies(args.cookie)
    if not cookies:
        print("錯誤: 未找到有效 Cookie。")
        sys.exit(1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 成功載入 {len(cookies)} 個會員帳號憑證：")
    for i, c in enumerate(cookies, 1):
        print(f"  • {get_user_display_name(c, i)}")
    if gemini_keys:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 已啟用 Google Gemini AI 解題引擎 (載入 {len(gemini_keys)} 組 Key)")

    if args.query:
        for i, c in enumerate(cookies, 1):
            name = get_user_display_name(c, i)
            status, rec = send_quiz_request("GET", f"/quiz/record/{QUIZ_ACTIVITY_ID}.PROMO", c)
            if status == 200:
                print(f"【{name}】紀錄查詢成功: {rec}")
            else:
                print(f"【{name}】查詢失敗: {rec}")
    elif args.now:
        now = datetime.now()
        sh, sm, slot_str = get_current_slot_info(now)
        slot_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        diff = (slot_dt - now).total_seconds()
        if args.force or (-3600 <= diff <= 240):
            wait_snipe = (not args.force) and (0 < diff <= 240)
            run_session(cookies, slot_hour=sh, slot_minute=sm, silent_if_limit=args.silent_if_limit, wait_snipe=wait_snipe, gemini_key=gemini_key)
        else:
            print(f"[{now.strftime('%H:%M:%S')}] 目前非活動時段窗口（距離最近時段 {slot_str} 尚有 {diff/60:.1f} 分鐘），略過執行。")


if __name__ == "__main__":
    main()
