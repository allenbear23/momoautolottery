// ==UserScript==
// @name         Momo 桃金日好運抽抽樂自動定時抽 & mo幣到期提醒
// @namespace    http://tampermonkey.net/
// @version      1.1
// @description  定時 (09:00, 13:00, 16:00, 19:00, 21:00) 自動點擊抽獎按鈕兩次，並於當日提醒即將到期之 mo 幣
// @author       Antigravity
// @match        https://www.momoshop.com.tw/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // 1. 檢查今日是否有即將到期之 mo 幣 / mo 點
    function checkExpiringCoins() {
        const todayStr = new Date().toISOString().slice(0, 10).replace(/-/g, '/');
        const lastChecked = localStorage.getItem('momo_coin_last_checked');
        if (lastChecked === todayStr) {
            return; // 今日已檢查過
        }

        const payload = { flag: 3156, data: { currencyType: "1" } };
        fetch('/servlet/MemberCenterServ', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: 'data=' + encodeURIComponent(JSON.stringify(payload))
        })
        .then(res => res.json())
        .then(data => {
            if (data && data.expirationAmount) {
                const expAmount = parseFloat(String(data.expirationAmount).replace(/,/g, '')) || 0;
                const expDate = data.expirationDate || '';
                if (expAmount > 0 && expDate.includes(todayStr)) {
                    showExpiringToast(`⚠️ 提醒：您有 ${data.expirationAmount} 元 momo 幣將於今日到期！請記得折抵消費。`);
                }
            }
            localStorage.setItem('momo_coin_last_checked', todayStr);
        })
        .catch(() => {});
    }

    function showExpiringToast(msg) {
        const toast = document.createElement('div');
        toast.innerText = msg;
        toast.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999999;padding:14px 20px;background:#e6007e;color:#fff;border-radius:8px;font-size:15px;font-weight:bold;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 12000);
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', checkExpiringCoins);
    } else {
        checkExpiringCoins();
    }

    // 2. 抽抽樂活動頁面定時抽獎 (僅在抽抽樂 EDM 頁面作用)
    if (window.location.href.includes('lpn=O8dV4oaCUPZ') || window.location.href.includes('momoLottery')) {
        const SCHEDULE_HOURS = [9, 13, 16, 19, 21];
        let triggeredTodayHours = new Set();

        function log(msg) {
            console.log(`[MomoAutoDraw ${new Date().toLocaleTimeString()}] ${msg}`);
        }

        function executeDraws(count = 2) {
            log(`開始執行抽獎，預計抽取 ${count} 次`);
            let done = 0;

            function drawOnce() {
                if (done >= count) {
                    log('抽獎流程結束');
                    return;
                }
                if (typeof promoCloudConfig !== 'undefined' && promoCloudConfig.lotteryMahjong) {
                    log(`觸發第 ${done + 1} 次抽獎`);
                    promoCloudConfig.lotteryMahjong();
                    done++;
                    setTimeout(drawOnce, 4000);
                } else {
                    log('找不到 promoCloudConfig 物件');
                }
            }

            drawOnce();
        }

        // 每 20 秒檢查一次是否到達指定整點
        setInterval(() => {
            const now = new Date();
            const hour = now.getHours();
            const minute = now.getMinutes();
            const dateKey = `${now.toDateString()}_${hour}`;

            if (SCHEDULE_HOURS.includes(hour) && minute < 5 && !triggeredTodayHours.has(dateKey)) {
                triggeredTodayHours.add(dateKey);
                log(`到達活動時段 ${hour}:00，觸發自動抽獎`);
                executeDraws(2);
            }
        }, 20000);

        // 新增手動按鈕在頁面右上角方便即時測試
        window.addEventListener('load', () => {
            const btn = document.createElement('button');
            btn.innerText = '自動抽 2 次 (測試)';
            btn.style.cssText = 'position:fixed;top:10px;right:10px;z-index:999999;padding:8px 12px;background:#ed1dca;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:bold;';
            btn.onclick = () => executeDraws(2);
            document.body.appendChild(btn);
        });
    }
})();
