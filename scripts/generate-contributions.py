"""Render a GitHub contribution calendar using the reference's isometric geometry.

Geometry adapted from lowlighter/metrics' isocalendar plugin (MIT).
See licenses/lowlighter-metrics.txt. Data comes from GitHub's public calendar.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


class ContributionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: dict[str, dict] = {}
        self.tooltips: dict[str, str] = {}
        self.tooltip_id: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("data-date") and values.get("data-level") is not None:
            identifier = values.get("id")
            if not identifier:
                raise ValueError("Contribution cell has no identifier")
            self.cells[identifier] = {
                "date": values["data-date"], "level": int(values["data-level"]),
            }
        if tag == "tool-tip":
            self.tooltip_id = values.get("for")
            if self.tooltip_id:
                self.tooltips[self.tooltip_id] = ""

    def handle_data(self, value: str) -> None:
        if self.tooltip_id:
            self.tooltips[self.tooltip_id] += value

    def handle_endtag(self, tag: str) -> None:
        if tag == "tool-tip":
            self.tooltip_id = None

    def days(self) -> list[dict]:
        days = []
        for identifier, cell in self.cells.items():
            tooltip = self.tooltips.get(identifier, "").strip()
            match = re.search(r"([\d,]+) contributions?\b", tooltip, re.IGNORECASE)
            if match:
                count = int(match.group(1).replace(",", ""))
            elif re.search(r"\bNo contributions\b", tooltip, re.IGNORECASE):
                count = 0
            else:
                raise ValueError(f"Could not read contribution count for {cell['date']}")
            if cell["level"] not in range(5) or (count == 0) != (cell["level"] == 0):
                raise ValueError(f"Inconsistent contribution cell for {cell['date']}")
            days.append({**cell, "count": count})
        days.sort(key=lambda item: item["date"])
        if len(days) < 180 or len({day["date"] for day in days}) != len(days):
            raise ValueError("GitHub returned an incomplete contribution calendar")
        for previous, current in zip(days, days[1:]):
            if date.fromisoformat(current["date"]) - date.fromisoformat(previous["date"]) != timedelta(days=1):
                raise ValueError("Contribution calendar has a date gap")
        return days


PALETTES = {
    "light": {"background": "#ffffff", "text": "#1f2328", "muted": "#59636e", "days": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]},
    "dark": {"background": "#0d1117", "text": "#f0f6fc", "muted": "#9198a1", "days": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]},
}


def render_svg(days: list[dict], login: str, theme: str, mobile: bool = False) -> str:
    palette = PALETTES[theme]
    start, end = date.fromisoformat(days[0]["date"]), date.fromisoformat(days[-1]["date"])
    weeks: dict[int, list[dict]] = defaultdict(list)
    for day in days:
        weeks[(date.fromisoformat(day["date"]) - start).days // 7].append(day)
    peak = max(day["count"] for day in days)
    total = sum(day["count"] for day in days)
    active = sum(day["count"] > 0 for day in days)
    metadata = {"user": login, "source": f"https://github.com/users/{login}/contributions", "from": start.isoformat(), "to": end.isoformat(), "days": len(days), "contributions": total, "active_days": active, "max_in_a_day": peak}
    width, height = (280, 270) if mobile else (480, 220)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * 2}" height="{height * 2}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="calendar-title calendar-description">',
        f'<title id="calendar-title">{escape(login)} 的近半年三维贡献日历</title>',
        f'<desc id="calendar-description">{start.isoformat()} 至 {end.isoformat()}，{total} 次贡献。每根柱子表示一天，柱高与贡献数成正比。</desc>',
        f'<metadata>{escape(json.dumps(metadata, ensure_ascii=False))}</metadata>',
        f'<rect width="{width}" height="{height}" fill="{palette["background"]}"/>',
        '<defs><filter id="left-shade"><feComponentTransfer><feFuncR type="linear" slope="0.6"/><feFuncG type="linear" slope="0.6"/><feFuncB type="linear" slope="0.6"/></feComponentTransfer></filter>',
        '<filter id="right-shade"><feComponentTransfer><feFuncR type="linear" slope="0.2"/><feFuncG type="linear" slope="0.2"/><feFuncB type="linear" slope="0.2"/></feComponentTransfer></filter></defs>',
        f'<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif" fill="{palette["text"]}">',
    ]
    if mobile:
        parts.extend([
            f'<text x="16" y="20" font-size="14" font-weight="600">{escape(login)}</text>',
            f'<text x="16" y="40" font-size="12" fill="{palette["muted"]}">{start.isoformat()} 至 {end.isoformat()}</text>',
            '</g><g transform="translate(18 62) scale(3.8) translate(12 0)">',
        ])
    else:
        parts.extend([
            f'<text x="24" y="24" font-size="12" font-weight="600">{escape(login)}</text>',
            f'<text x="456" y="24" text-anchor="end" font-size="10" fill="{palette["muted"]}">{start.isoformat()} 至 {end.isoformat()}</text>',
            '</g><g transform="translate(10 44) scale(4) translate(12 0)">',
        ])
    for index, week in sorted(weeks.items()):
        parts.append(f'<g transform="translate({index * 1.7:.2f} {index})">')
        for day in week:
            row = (date.fromisoformat(day["date"]).weekday() + 1) % 7
            ratio = day["count"] / peak if peak else 0
            height = ratio * 6
            color = palette["days"][day["level"]]
            parts.extend([
                f'<g data-date="{day["date"]}" data-count="{day["count"]}" transform="translate({row * -1.7:.2f} {row + (1 - ratio) * 6:.3f})">',
                f'<title>{day["date"]}: {day["count"]} contributions</title>',
                f'<path fill="{color}" d="M1.7 2 L0 1 L1.7 0 L3.4 1 Z"/>',
                f'<path fill="{color}" filter="url(#left-shade)" d="M0 1 L1.7 2 L1.7 {2 + height:.3f} L0 {1 + height:.3f} Z"/>',
                f'<path fill="{color}" filter="url(#right-shade)" d="M1.7 2 L3.4 1 L3.4 {1 + height:.3f} L1.7 {2 + height:.3f} Z"/>',
                '</g>',
            ])
        parts.append('</g>')
    parts.append('</g>')
    parts.append(f'<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif" fill="{palette["text"]}">')
    if mobile:
        for x, value, label in [(16, total, "次贡献"), (105, active, "活跃日"), (190, peak, "单日最高")]:
            parts.append(f'<text x="{x}" y="238" font-size="12"><tspan font-weight="600">{value:,}</tspan> {label}</text>')
        parts.append(f'<text x="16" y="264" font-size="11" fill="{palette["muted"]}">柱高对应每日贡献数</text>')
        parts.append(f'<text x="170" y="264" font-size="11" fill="{palette["muted"]}">少</text>')
        for index, color in enumerate(palette["days"]):
            parts.append(f'<rect x="{190 + index * 10}" y="254" width="8" height="10" rx="1" fill="{color}"/>')
        parts.append(f'<text x="246" y="264" font-size="11" fill="{palette["muted"]}">多</text></g></svg>')
        return "\n".join(parts) + "\n"
    for y, value, label in [(70, total, "区间贡献"), (111, active, "活跃天数"), (152, peak, "单日最高")]:
        parts.append(f'<text x="304" y="{y}" font-size="20" font-weight="600">{value:,}</text>')
        parts.append(f'<text x="304" y="{y + 15}" font-size="10" fill="{palette["muted"]}">{label}</text>')
    parts.append(f'<text x="24" y="207" font-size="9" fill="{palette["muted"]}">每根柱子代表一天，柱高对应贡献数</text>')
    parts.append(f'<text x="370" y="207" font-size="9" fill="{palette["muted"]}">少</text>')
    for index, color in enumerate(palette["days"]):
        parts.append(f'<rect x="{385 + index * 12}" y="198" width="9" height="9" rx="1" fill="{color}"/>')
    parts.append(f'<text x="449" y="207" font-size="9" fill="{palette["muted"]}">多</text></g></svg>')
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="Haven-mao")
    parser.add_argument("--input", type=Path, help="Saved public contribution calendar, for local previews")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "assets")
    parser.add_argument("--data-output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", args.user):
        raise ValueError("Invalid GitHub login")
    if args.input:
        html = args.input.read_text(encoding="utf-8")
    else:
        request = Request(f"https://github.com/users/{args.user}/contributions", headers={"User-Agent": "GitHub-Profile-Contribution-Calendar", "Accept-Language": "en-US"})
        with urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8")
    calendar = ContributionParser()
    calendar.feed(html)
    all_days = calendar.days()
    end = date.fromisoformat(all_days[-1]["date"])
    start = end - timedelta(days=180)
    start -= timedelta(days=(start.weekday() + 1) % 7)
    days = [day for day in all_days if date.fromisoformat(day["date"]) >= start]
    outputs = {}
    for theme in PALETTES:
        outputs[f"contributions-3d-{theme}.svg"] = render_svg(days, args.user, theme)
        outputs[f"contributions-3d-mobile-{theme}.svg"] = render_svg(days, args.user, theme, mobile=True)
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, svg in outputs.items():
        (args.output / filename).write_text(svg, encoding="utf-8")
    if args.data_output:
        args.data_output.parent.mkdir(parents=True, exist_ok=True)
        args.data_output.write_text(json.dumps({"user": args.user, "days": days}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"user": args.user, "from": days[0]["date"], "to": days[-1]["date"], "days": len(days), "contributions": sum(day["count"] for day in days), "max_in_a_day": max(day["count"] for day in days)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
