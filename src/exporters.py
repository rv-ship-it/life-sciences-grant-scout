import csv
import json
from datetime import date
from pathlib import Path


def export_json(opportunities: list, output_path: str, run_log: dict | None = None):
    data = {
        "metadata": run_log or {},
        "generated_at": date.today().isoformat(),
        "count": len(opportunities),
        "opportunities": [opp.to_dict() for opp in opportunities],
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def export_csv(opportunities: list, output_path: str):
    fieldnames = [
        "id", "source", "title", "agency", "activity_type",
        "posted_date", "deadline", "award_ceiling", "currency",
        "startup_eligible", "consortium_eligible",
        "keyword_score", "semantic_score", "combined_score",
        "matched_topics", "high_priority", "url",
    ]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for opp in opportunities:
            row = opp.to_dict()
            topics = row.get("matched_topics", [])
            row["matched_topics"] = "; ".join(topics) if isinstance(topics, list) else str(topics)
            writer.writerow(row)


def export_markdown(opportunities: list, output_path: str, top_n: int = 25):
    lines = [f"# Grant Scout Report -- {date.today().isoformat()}\n"]

    sources_count = len(set(o.source for o in opportunities))
    hp_count = sum(1 for o in opportunities if o.high_priority)
    startup_count = sum(1 for o in opportunities if o.startup_eligible)
    consortium_count = sum(1 for o in opportunities if o.consortium_eligible)

    lines.append("## Summary\n")
    lines.append(f"- **Total**: {len(opportunities)} opportunities across {sources_count} sources")
    lines.append(f"- **High priority**: {hp_count} opportunities")
    lines.append(f"- **Startup-eligible**: {startup_count}")
    lines.append(f"- **Consortium-eligible**: {consortium_count}\n")

    lines.append("## Top Opportunities\n")
    for i, opp in enumerate(opportunities[:top_n], 1):
        badges = ""
        if opp.high_priority:
            badges += " **[HIGH PRIORITY]**"
        if opp.startup_eligible:
            badges += " **[STARTUP]**"
        if opp.consortium_eligible:
            badges += " **[CONSORTIUM]**"

        lines.append(f"### {i}. {opp.title}{badges}")
        lines.append(
            f"- **Score**: {opp.combined_score}/100 | "
            f"**Source**: {opp.source.value} | "
            f"**Agency**: {opp.agency}"
        )
        deadline_str = opp.deadline.isoformat() if opp.deadline else "Rolling/TBD"
        lines.append(f"- **Deadline**: {deadline_str}")

        if opp.award_ceiling:
            lines.append(f"- **Max award**: {opp.currency} {opp.award_ceiling:,}")

        lines.append(
            f"- **Startup eligible**: {'Yes' if opp.startup_eligible else 'No'} | "
            f"**Consortium**: {'Yes' if opp.consortium_eligible else 'No'}"
        )
        topics = ", ".join(opp.matched_topics[:5]) if opp.matched_topics else "None"
        lines.append(f"- **Topics**: {topics}")
        lines.append(f"- {opp.description[:300]}...")
        lines.append(f"- [View full announcement]({opp.url})\n")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
