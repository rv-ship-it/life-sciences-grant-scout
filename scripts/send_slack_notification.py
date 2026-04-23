#!/usr/bin/env python3
"""Send weekly grant summary to Slack via incoming webhook.

Reads dashboard/data/opportunities.json and posts a formatted summary
of the top relevant grants, counts, and a link to the dashboard.

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
TOP_N = 10


def load_data():
    if not DATA_PATH.exists():
        sys.exit(f"Data file not found: {DATA_PATH}")
    with open(DATA_PATH) as f:
        return json.load(f)


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


def build_blocks(data):
    opps = data.get("opportunities", [])
    total = len(opps)
    relevant = [o for o in opps if o.get("combined_score", 0) > 0]
    high_priority = [o for o in opps if o.get("high_priority")]
    today = date.today().isoformat()

    top = sorted(relevant, key=lambda o: o.get("combined_score", 0), reverse=True)[:TOP_N]

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
                {"type": "mrkdwn", "text": f"*Relevant (scored):*\n{len(relevant)}"},
                {"type": "mrkdwn", "text": f"*High priority:*\n{len(high_priority)}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top {len(top)} relevant grants*"},
        },
    ]

    for o in top:
        score = o.get("combined_score", 0)
        title = o.get("title", "Untitled")
        source = o.get("source", "")
        agency = o.get("agency", "")
        url = o.get("url", "")
        deadline = format_deadline(o.get("deadline"))
        funding = format_funding(o.get("award_ceiling"), o.get("currency"))
        topics = ", ".join(o.get("matched_topics", [])[:3])

        # Score emoji
        if score >= 30:
            emoji = "🟢"
        elif score >= 10:
            emoji = "🟡"
        else:
            emoji = "⚪"

        meta_parts = [source, agency, f"📅 {deadline}"]
        if funding:
            meta_parts.append(f"💰 {funding}")
        meta = " · ".join(p for p in meta_parts if p)

        text = f"{emoji} *<{url}|{title}>*  `{score}`\n{meta}"
        if topics:
            text += f"\n_{topics}_"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    if not top:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No relevant grants this week._"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"🔗 <{DASHBOARD_URL}|Open full dashboard>"},
    })

    return blocks


def main():
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        sys.exit("SLACK_WEBHOOK_URL environment variable not set")

    data = load_data()
    blocks = build_blocks(data)

    payload = {
        "text": "Grant Scout weekly update",  # fallback for notifications
        "blocks": blocks,
    }

    resp = requests.post(webhook, json=payload, timeout=30)
    if resp.status_code != 200:
        sys.exit(f"Slack webhook failed: {resp.status_code} {resp.text}")

    print(f"✓ Slack notification sent ({len(blocks)} blocks)")


if __name__ == "__main__":
    main()
