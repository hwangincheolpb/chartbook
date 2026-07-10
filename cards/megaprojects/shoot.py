#!/usr/bin/env python3
"""megaprojects 카드 → 1080x1350 PNG (2x). 재사용 가능한 카드 캡처 스크립트."""
import sys, os
from playwright.sync_api import sync_playwright

URL = os.environ.get("CARD_URL", "http://localhost:8850/cards/megaprojects/index.html")
OUT = os.environ.get("CARD_OUT", os.path.join(os.path.dirname(__file__), "megaprojects-card.png"))

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=2)
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(1200)  # ECharts 애니메이션/폰트 안정화
    card = pg.locator("#card")
    card.screenshot(path=OUT)
    print("saved", OUT, "dpr=2 →", "2160x2700")
    b.close()
