// ==UserScript==
// @name         Momo 桃金日好運抽抽樂自動定時抽
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  定時 (09:00, 13:00, 16:00, 19:00, 21:00) 自動點擊抽獎按鈕兩次
// @author       Antigravity
// @match        https://www.momoshop.com.tw/edm/cmmedm.jsp?*lpn=O8dV4oaCUPZ*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

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
})();
