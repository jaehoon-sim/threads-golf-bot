#!/usr/bin/env python3
"""오늘 쓸 주제와 제휴 글 여부를 정해준다. Claude 스케줄 작업이 글을 쓰기 전에 실행한다.

history.jsonl 과 topic_pool.yaml 의 cooldown_days 를 대조해 최근에 쓴 주제를 걸러내고,
weight 를 반영해 후보를 정렬한다. 쿠팡파트너스가 켜져 있으면 빈도 상한·간격·상품
쿨다운을 따져 오늘 제휴 글을 낼지, 낸다면 어떤 상품 후보가 있는지도 함께 출력한다.

사용법:
    python scripts/plan.py                 # 남은 슬롯 전부에 대한 후보
    python scripts/plan.py --slots 3       # 슬롯 수 지정
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
POOL = ROOT / "content" / "topic_pool.yaml"
PRODUCTS = ROOT / "content" / "products.yaml"
HISTORY = ROOT / "history" / "history.jsonl"
QUEUE = ROOT / "queue"
KST = dt.timezone(dt.timedelta(hours=9))
LINK_PREFIX = "https://link.coupang.com/"


def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _when(row: dict) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(row["published_at"])
    except (KeyError, ValueError):
        return None


def last_used(rows: list[dict], field: str) -> dict[str, dt.datetime]:
    seen: dict[str, dt.datetime] = {}
    for row in rows:
        key = row.get(field)
        when = _when(row)
        if not key or row.get("status") != "published" or when is None:
            continue
        if key not in seen or when > seen[key]:
            seen[key] = when
    return seen


def queued_items() -> list[dict]:
    items = []
    for path in QUEUE.glob("*.json"):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return items


def plan_affiliate(pool: dict, rows: list[dict], queued: list[dict], now: dt.datetime) -> dict:
    mon = pool.get("monetization") or {}
    if not mon.get("enabled"):
        return {"today": False, "reason": "monetization.enabled 가 false"}

    published = [r for r in rows if r.get("status") == "published"]
    organic = [r for r in published if not r.get("affiliate_product")]
    need = int(mon.get("start_after_posts", 0))
    if len(organic) < need:
        return {"today": False, "reason": f"일반 글 {len(organic)}/{need}건 — 신뢰 쌓는 구간"}

    if any(q.get("affiliate") for q in queued):
        return {"today": False, "reason": "큐에 이미 제휴 글이 있음"}

    aff = [r for r in published if r.get("affiliate_product") and _when(r)]
    week = [r for r in aff if now - _when(r) < dt.timedelta(days=7)]
    if len(week) >= int(mon.get("max_per_week", 3)):
        return {"today": False, "reason": f"최근 7일 제휴 글 {len(week)}건 — 주간 상한 도달"}

    if aff:
        latest = max(_when(r) for r in aff)
        gap = now - latest
        min_gap = dt.timedelta(days=int(mon.get("min_gap_days", 2)))
        if gap < min_gap:
            return {"today": False, "reason": f"마지막 제휴 글 후 {gap.days}일 — 최소 간격 미달"}

    if not PRODUCTS.exists():
        return {"today": False, "reason": "content/products.yaml 없음"}
    catalog = (yaml.safe_load(PRODUCTS.read_text(encoding="utf-8")) or {}).get("products") or []
    used = last_used(rows, "affiliate_product")
    cooldown = dt.timedelta(days=int(mon.get("product_cooldown_days", 21)))

    ready, skipped = [], []
    for p in catalog:
        if not p.get("active"):
            continue
        link = (p.get("link") or "").strip()
        if not link.startswith(LINK_PREFIX):
            skipped.append({"key": p.get("key"), "reason": "링크가 link.coupang.com 형식이 아님"})
            continue
        if not p.get("facts"):
            skipped.append({"key": p.get("key"), "reason": "facts 가 비어 있음 — 쓸 근거가 없음"})
            continue
        if p.get("key") in used and now - used[p["key"]] < cooldown:
            skipped.append({"key": p.get("key"), "reason": "상품 쿨다운 중"})
            continue
        ready.append({k: p.get(k) for k in ("key", "name", "link", "pillars", "fits", "facts")})

    if not ready:
        return {"today": False, "reason": "쓸 수 있는 상품 없음", "skipped": skipped}

    # 날짜 기반으로 고르게 돌린다
    ready.sort(key=lambda p: hashlib.md5(f"{p['key']}{now:%Y-%m-%d}".encode()).hexdigest())
    return {
        "today": True,
        "slot": mon.get("slot", "21:00"),
        "disclosure": mon.get("disclosure"),
        "link_placement": mon.get("link_placement", "first_reply"),
        "rules": mon.get("rules", []),
        "products": ready[:3],
        "skipped": skipped,
        "week_count": len(week),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=0, help="채울 슬롯 수 (0이면 전체)")
    args = ap.parse_args()

    pool = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    rows = load_history()
    seen = last_used(rows, "topic_key")
    now = dt.datetime.now(dt.timezone.utc)
    queued = queued_items()
    queued_topics = {q.get("topic_key") for q in queued}

    candidates, blocked = [], []
    for pillar in pool["pillars"]:
        key = pillar["key"]
        cooldown = dt.timedelta(days=pillar.get("cooldown_days", 3))
        used = seen.get(key)
        rest_days = 0.0
        if used and now - used < cooldown:
            rest_days = round((cooldown - (now - used)).total_seconds() / 86400, 1)
        if rest_days > 0 or key in queued_topics:
            blocked.append({"key": key, "name": pillar["name"],
                            "reason": "큐에 이미 있음" if key in queued_topics else f"쿨다운 {rest_days}일 남음"})
            continue
        # 같은 날 같은 순서가 나오지 않도록 날짜 기반으로 안정적으로 섞는다
        jitter = int(hashlib.md5(f"{key}{now:%Y-%m-%d}".encode()).hexdigest()[:6], 16) % 100
        score = pillar.get("weight", 1) * 100 + jitter
        candidates.append({
            "key": key, "name": pillar["name"], "angles": pillar.get("angles", []),
            "score": score,
            "days_since_used": round((now - used).total_seconds() / 86400, 1) if used else None,
        })

    candidates.sort(key=lambda c: -c["score"])
    slots = pool.get("slots", [])
    if args.slots:
        slots = slots[: args.slots]

    published = [r for r in rows if r.get("status") == "published"]
    out = {
        "generated_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "today_kst": dt.datetime.now(KST).strftime("%Y-%m-%d"),
        "voice": pool.get("voice", {}),
        "slots": slots,
        "candidates": candidates[: max(len(slots) * 3, 6)],
        "blocked": blocked,
        "affiliate": plan_affiliate(pool, rows, queued, now),
        "recent_posts": [
            {"id": r.get("id"), "topic_key": r.get("topic_key"), "text": (r.get("text") or "")[:80]}
            for r in published[-12:]
        ],
        "published_total": len(published),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
