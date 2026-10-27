#!/usr/bin/env python3
"""Send weekly grant summary to Slack via incoming webhook.

Reads dashboard/data/opportunities.json, compares against the previous
week's sent IDs stored in notifications/last_sent.json, and posts:
  🆕 New this week — all relevant grants not seen in prior weeks
  📌 Still open — top 3 rolling reminders of previously-sent grants

Usage:
    SLACK_WEBHOOK_URL=https://hooks.slack.com/... python3 scripts/send_slack_notification.py
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import requests

DASHBOARD_URL = "https://rv-ship-it.github.io/life-sciences-grant-scout/"
DATA_PATH = Path("dashboard/data/opportunities.json")
STATE_PATH = Path("notifications/last_sent.json")
ROLLING_RECAP_COUNT = 3
# Cap stored IDs so the state file doesn't grow forever
MAX_STATE_IDS = 500


def load_data():
    if not DATA_PATH.exists():
        sys.exit(f"Data file not found: {DATA_PATH}")
    with open(DATA_PATH) as f:
        return json.load(f)


def load_state():
    """Load previously-sent grant IDs. Returns an empty set on first run."""
    if not STATE_PATH.exists():
        return set()
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
        return set(state.get("sent_ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_state(previously_sent: set, current_relevant_ids: list):
    """Persist the union of previously-sent and current-relevant IDs,
    bounded to MAX_STATE_IDS (most recent kept)."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep order: current first (most recent), then previously sent
    merged = list(current_relevant_ids)
    for sid in previously_sent:
        if sid not in merged:
            merged.append(sid)
    merged = merged[:MAX_STATE_IDS]
    payload = {
        "last_sent_at": date.today().isoformat(),
        "sent_ids": merged,
    }
    with open(STATE_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def format_deadline(deadline_str):
    if not deadline_str:
        return "Rolling / TBD"
    try:
        d = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        days_left = (d - date.today()).days
        if days_left < 0:
            return f"{deadline_str} (expired)"
        if days_left <= 14:
            return f"{deadline_str} :warning: ({days_left}d left)"
        return f"{deadline_str} ({days_left}d left)"
    except ValueError:
        return deadline_str


def format_funding(ceiling, currency):
    if not ceiling:
        return ""
    cur = currency or "USD"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur, cur + " ")
    if ceiling >= 1_000_000:
        return f"{symbol}{ceiling / 1_000_000:.1f}M"
    if ceiling >= 1_000:
        return f"{symbol}{ceiling / 1_000:.0f}K"
    return f"{symbol}{ceiling:,}"


def score_emoji(score: float) -> str:
    if score >= 30:
        return "🟢"
    if score >= 10:
        return "🟡"
    return "⚪"


def format_grant_section(opp: dict) -> dict:
    score = opp.get("combined_score", 0)
    title = opp.get("title", "Untitled")
    url = opp.get("url", "")
    deadline = format_deadline(opp.get("deadline"))
    funding = format_funding(opp.get("award_ceiling"), opp.get("currency"))
    topics = ", ".join(opp.get("matched_topics", [])[:3])
    emoji = score_emoji(score)

    meta_parts = [opp.get("source", ""), opp.get("agency", ""), f"📅 {deadline}"]
    if funding:
        meta_parts.append(f"💰 {funding}")
    meta = " · ".join(p for p in meta_parts if p)

    text = f"{emoji} *<{url}|{title}>*  `{score}`\n{meta}"
    if topics:
        text += f"\n_{topics}_"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_blocks(data: dict, previously_sent: set):
    opps = data.get("opportunities", [])
    total = len(opps)
    relevant = [o for o in opps if o.get("combined_score", 0) > 0]
    relevant_sorted = sorted(
        relevant, key=lambda o: o.get("combined_score", 0), reverse=True
    )
    high_priority = [o for o in opps if o.get("high_priority")]
    today = date.today().isoformat()

    new_relevant = [o for o in relevant_sorted if o["id"] not in previously_sent]
    rolling_recap = [
        o for o in relevant_sorted if o["id"] in previously_sent
    ][:ROLLING_RECAP_COUNT]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🧬 Grant Scout — Weekly Update"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Scan date:*\n{today}"},
                {"type": "mrkdwn", "text": f"*Total opportunities:*\n{total}"},
                {"type": "mrkdwn", "text": f"*New this week:*\n{len(new_relevant)}"},
                {"type": "mrkdwn", "text": f"*High priority:*\n{len(high_priority)}"},
            ],
        },
        {"type": "divider"},
    ]

    # 🆕 New this week
    if new_relevant:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🆕 New this week ({len(new_relevant)})*",
                },
            }
        )
        for opp in new_relevant:
            blocks.append(format_grant_section(opp))
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_🆕 No new relevant grants this week._",
                },
            }
        )

    # 📌 Still open — rolling reminders
    if rolling_recap:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📌 Still open — reminders ({len(rolling_recap)})*",
                },
            }
        )
        for opp in rolling_recap:
            blocks.append(format_grant_section(opp))

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🔗 <{DASHBOARD_URL}|Open full dashboard>",
            },
        }
    )
    return blocks, relevant_sorted


def main():
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        sys.exit("SLACK_WEBHOOK_URL environment variable not set")

    data = load_data()
    previously_sent = load_state()
    blocks, relevant_sorted = build_blocks(data, previously_sent)

    payload = {
        "text": "Grant Scout weekly update",  # fallback for notifications
        "blocks": blocks,
    }

    resp = requests.post(webhook, json=payload, timeout=30)
    if resp.status_code != 200:
        sys.exit(f"Slack webhook failed: {resp.status_code} {resp.text}")

    # On success, update state with current relevant IDs
    current_ids = [o["id"] for o in relevant_sorted]
    save_state(previously_sent, current_ids)

    new_count = sum(1 for o in relevant_sorted if o["id"] not in previously_sent)
    print(
        f"✓ Slack notification sent ({len(blocks)} blocks, "
        f"{new_count} new, {len(current_ids)} relevant total)"
    )


if __name__ == "__main__":
    main()
