#!/usr/bin/env python3
"""카드 이미지 렌더러 — 큐 아이템의 card 필드를 1080x1350 PNG로 굽는다.

제휴 게시물(affiliate 필드가 있는 항목)은 카드 우상단에 '광고 · 쿠팡파트너스'
표기가 자동으로 붙는다. 끌 수 없다.

사용법:
    python scripts/render_card.py queue/2026-08-25-0730.json
    python scripts/render_card.py --all
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "scripts" / "card_template.html").as_uri()
ASSETS = ROOT / "assets"
ACCENTS = ("fairway", "dawn", "sand", "clay")

W, H = 1080, 1350


def _fit(headline: str, body: str) -> tuple[int, int]:
    """글자 수에 따라 헤드라인/본문 크기를 줄여 넘침을 막는다."""
    n = len(headline)
    hsize = 104 if n <= 22 else 88 if n <= 34 else 74 if n <= 48 else 62
    b = len(body)
    bsize = 44 if b <= 110 else 38 if b <= 180 else 33
    return hsize, bsize


def render_one(page, item: dict) -> pathlib.Path:
    card = item.get("card") or {}
    headline = card.get("headline", "").strip()
    if not headline:
        raise ValueError(f"{item['id']}: card.headline 이 비어 있습니다")
    body = card.get("body", "").strip()
    kicker = card.get("kicker", "GOLF NOTE").strip()
    tag = card.get("tag", "#골프").strip()
    handle = card.get("handle", "@threads").strip()
    accent = card.get("accent")
    if accent not in ACCENTS:                      # 지정 없으면 id 해시로 고르게 분산
        accent = ACCENTS[sum(map(ord, item["id"])) % len(ACCENTS)]
    is_ad = "1" if item.get("affiliate") else "0"

    hsize, bsize = _fit(headline, body)
    page.goto(TEMPLATE, wait_until="networkidle")
    page.evaluate(
        """([h, b, k, t, hd, ac, hs, bs, ad]) => {
            document.body.dataset.accent = ac;
            document.body.dataset.ad = ad;
            document.body.style.setProperty('--hsize', hs + 'px');
            document.body.style.setProperty('--bsize', bs + 'px');
            document.getElementById('headline').textContent = h;
            document.getElementById('body').textContent = b;
            document.getElementById('kicker').textContent = k;
            document.getElementById('tag').textContent = t;
            document.getElementById('handle').textContent = hd;
        }""",
        [headline, body, kicker, tag, handle, accent, hsize, bsize, is_ad],
    )
    page.wait_for_timeout(400)                     # 웹폰트 적용 대기

    ASSETS.mkdir(exist_ok=True)
    out = ASSETS / f"{item['id']}.png"
    page.screenshot(path=str(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="큐 JSON 경로")
    ap.add_argument("--all", action="store_true", help="queue/*.json 전체 렌더")
    args = ap.parse_args()

    targets = [pathlib.Path(p) for p in args.paths]
    if args.all:
        targets = sorted((ROOT / "queue").glob("*.json"))
    if not targets:
        print("렌더할 큐 파일이 없습니다.", file=sys.stderr)
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for path in targets:
            item = json.loads(path.read_text(encoding="utf-8"))
            if not item.get("card"):
                print(f"skip (카드 없음): {path.name}")
                continue
            out = render_one(page, item)
            print(f"rendered: {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} KB)")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
