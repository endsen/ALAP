"""Generate the complete transition reference from executable domain rules."""

import argparse
from pathlib import Path

from alap.domain.lifecycle import RULES, STATE_TYPES

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/21_STATE_MACHINES.md"
BEGIN = "<!-- BEGIN GENERATED TRANSITIONS -->"
END = "<!-- END GENERATED TRANSITIONS -->"


def render():
    sections = []
    for kind, enum in STATE_TYPES.items():
        sections.append(f"### {enum.__name__}\n\n状态：" + "、".join(f"`{s.value}`" for s in enum))
        rows = ["| 起始状态 | 事件 → 目标 | 主体 | 必需证据事实 | effects |\n|---|---|---|---|---|"]
        groups = {}
        for rule in RULES:
            if rule.kind != kind:
                continue
            key = (rule.event, rule.target, rule.authorities, rule.facts, rule.effects)
            groups.setdefault(key, []).append(rule.source.value)
        for (event, target, authorities, facts, effects), sources in groups.items():
            rows.append(
                f"| {', '.join(sources)} | `{event}` → {target.value} | "
                f"{', '.join(sorted(authorities))} | {', '.join(sorted(facts))} | "
                f"{', '.join(sorted(effects)) or '—'} |"
            )
        sections.append("\n".join(rows))
    return "\n\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = TARGET.read_text(encoding="utf-8")
    before, rest = content.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    output = before + BEGIN + "\n\n" + render() + "\n" + END + after
    if args.check:
        if content != output:
            raise SystemExit("Lifecycle reference drift: run scripts/build_lifecycle_reference.py")
        print(f"PASS: lifecycle reference covers {len(RULES)} transitions")
    else:
        TARGET.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
