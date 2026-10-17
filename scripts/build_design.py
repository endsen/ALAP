"""Generate a reviewable combined design; modular docs remain the source."""

import argparse
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "ALAP_Engineering_Design_v3.1_完整合订本.md"


def build() -> str:
    paths = sorted((ROOT / "docs").glob("[0-9][0-9]_*.md"))
    sections = [
        "# ALAP Engineering Design v3.1 — 完整合订本\n\n"
        "> 开发基线：专用 Agent + 多供应商 LLM API + 实验执行平台。\n"
        "> 由 docs/01–22 自动生成；不是已运行产品或真机安全认证。\n"
        "> 原始 v3.0 保留；实施进度见 IMPLEMENTATION_STATUS.md。\n\n"
        "## 目录\n\n"
        + "\n".join(f"- {path.read_text(encoding='utf-8').splitlines()[0][2:]}" for path in paths)
    ]
    for path in paths:
        content = path.read_text(encoding="utf-8").strip()

        def relocate_link(match):
            label, target = match.groups()
            if "://" in target or target.startswith(("#", "/", "mailto:")):
                return match.group(0)
            return f"[{label}]({posixpath.normpath('docs/' + target)})"

        content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", relocate_link, content)
        sections.append(f"<!-- 来源: docs/{path.name} -->\n\n{content}")
    return "\n\n---\n\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = build()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != output:
            raise SystemExit("Design drift: run python scripts/build_design.py")
        print("PASS: combined v3.1 design is current")
    else:
        TARGET.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
