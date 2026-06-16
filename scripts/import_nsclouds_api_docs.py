#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Iterable


TOP_LEVEL_MAP = {
    "conversation": "dui-hua-jie-kou",
    "image-generations": "tu-xiang-sheng-cheng",
    "image-edits": "tu-xiang-bian-ji",
    "audio-transcriptions": "yin-pin-zhuan-lu",
}

ROOT_ROUTE = "/aillm.nscloud.ai/api-reference-cn"
OPENAPI_TARGET_DIR = "/openapi/global/zh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import generated GitBook markdown from nsclouds-api-docs into Mintlify MDX pages."
    )
    parser.add_argument(
        "--source",
        default="/Users/zhoudshu/gitlab/nsclouds-api-docs/docs/global/zh",
        help="Source docs directory.",
    )
    parser.add_argument(
        "--target",
        default="aillm.nscloud.ai/api-reference-cn",
        help="Target Mintlify directory.",
    )
    parser.add_argument(
        "--spec-source",
        default="/Users/zhoudshu/gitlab/nsclouds-api-docs/docs/bundled/global/zh",
        help="Source directory for bundled OpenAPI files.",
    )
    parser.add_argument(
        "--spec-target",
        default="openapi/global/zh",
        help="Target directory for bundled OpenAPI files.",
    )
    return parser.parse_args()


def extract_title_and_body(text: str) -> tuple[str, str]:
    match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError("Missing H1 heading in source page.")
    title = match.group(1).strip()
    body = text[: match.start()] + text[match.end() :]
    return title, body.lstrip()


def markdown_blockquote(prefix: str, content: str) -> str:
    lines = [f"> {prefix}", ">"]
    for line in content.strip().splitlines():
        lines.append(">" if not line.strip() else f"> {line}")
    return "\n".join(lines)


def convert_hint_blocks(text: str) -> str:
    pattern = re.compile(r"\{% hint style=\"(?P<style>[^\"]+)\" %\}\n(?P<body>.*?)\n\{% endhint %\}", re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        style = match.group("style")
        label = {
            "success": "Note",
            "info": "Note",
            "warning": "Warning",
            "danger": "Warning",
        }.get(style, "Note")
        return markdown_blockquote(f"{label}:", match.group("body"))

    return pattern.sub(repl, text)


OPENAPI_BLOCK_PATTERN = re.compile(
    r"\{% openapi-operation spec=\"(?P<spec>[^\"]+)\" path=\"(?P<path>[^\"]+)\" method=\"(?P<method>[^\"]+)\" %\}\n"
    r"(?P<link>\[[^\]]+\]\([^)]+\)\n)?"
    r"\{% endopenapi-operation %\}",
    re.DOTALL,
)


def extract_openapi_reference(text: str) -> tuple[str, str | None]:
    match = OPENAPI_BLOCK_PATTERN.search(text)
    if not match:
        return text, None

    spec = match.group("spec")
    method = match.group("method").upper()
    path = match.group("path")
    vendor = spec.split("-", 1)[0]
    openapi_ref = f'"{OPENAPI_TARGET_DIR}/{vendor}.bundled.yaml {method} {path}"'
    text = OPENAPI_BLOCK_PATTERN.sub("", text, count=1)
    text = re.sub(r"\n+#{2,6}\s+\d+\.\s+接口详情\s*$", "", text.strip(), flags=re.MULTILINE)
    return text.strip() + "\n", openapi_ref


def source_rel_to_route(rel_path: Path) -> str:
    parts = rel_path.parts
    if rel_path == Path("README.md"):
        return ""
    if parts[0] not in TOP_LEVEL_MAP:
        raise ValueError(f"Unsupported source path: {rel_path}")

    top = TOP_LEVEL_MAP[parts[0]]
    if rel_path.name.lower() == "summary.md":
        if len(parts) == 2:
            return top
        if len(parts) == 3:
            return f"{top}/{parts[1]}"
        raise ValueError(f"Unsupported summary depth: {rel_path}")

    if len(parts) == 2:
        stem = rel_path.stem
        if stem.lower() == "readme":
            return top
        return f"{top}/{stem}"

    if len(parts) == 3:
        vendor = parts[1]
        stem = rel_path.stem
        if stem.lower() == "readme":
            return f"{top}/{vendor}"
        return f"{top}/{vendor}/{stem}"

    raise ValueError(f"Unsupported source path depth: {rel_path}")


def source_rel_to_target(rel_path: Path, target_root: Path) -> Path:
    route = source_rel_to_route(rel_path)
    if not route:
        return target_root / "index.mdx"
    parts = route.split("/")
    if len(parts) == 1:
        return target_root / f"{parts[0]}.mdx"
    if len(parts) == 2 and parts[0] == TOP_LEVEL_MAP["conversation"]:
        return target_root / parts[0] / parts[1] / "index.mdx"
    if len(parts) == 2:
        return target_root / parts[0] / f"{parts[1]}.mdx"
    return target_root / parts[0] / parts[1] / f"{parts[2]}.mdx"


def absolute_route(route: str) -> str:
    return ROOT_ROUTE if not route else f"{ROOT_ROUTE}/{route}"


def rewrite_links_from_source_root(text: str, source_root: Path, current_rel: Path) -> str:
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    def repl(match: re.Match[str]) -> str:
        label, target = match.groups()
        if target.startswith(("http://", "https://", "mailto:")):
            return match.group(0)
        source_target = (source_root / current_rel.parent / target).resolve()
        rel_target = source_target.relative_to(source_root.resolve())
        route = source_rel_to_route(rel_target)
        return f"[{label}]({absolute_route(route)})"

    return pattern.sub(repl, text)


def build_frontmatter(title: str, openapi_ref: str | None) -> str:
    safe_title = title.replace('"', '\\"')
    lines = ["---", f'title: "{safe_title}"']
    if openapi_ref:
        lines.append(f"openapi: {openapi_ref}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def convert_page(text: str, source_root: Path, current_rel: Path) -> str:
    title, body = extract_title_and_body(text)
    body = rewrite_links_from_source_root(body, source_root, current_rel)
    body, openapi_ref = extract_openapi_reference(body)
    body = convert_hint_blocks(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    return build_frontmatter(title, openapi_ref) + body


def iter_source_pages(source_root: Path) -> Iterable[Path]:
    yield source_root / "README.md"
    for rel in (
        "conversation/SUMMARY.md",
        "image-generations/SUMMARY.md",
        "image-edits/SUMMARY.md",
        "audio-transcriptions/SUMMARY.md",
    ):
        path = source_root / rel
        if path.exists():
            yield path

    for path in sorted(source_root.rglob("*.md")):
        if path.name in {"README.md", "SUMMARY.md"}:
            continue
        if path.parent == source_root:
            continue
        yield path

    for path in sorted(source_root.rglob("SUMMARY.md")):
        if path.parent == source_root:
            continue
        if path.parent.name in TOP_LEVEL_MAP:
            continue
        yield path


def append_root_links(index_path: Path, category_routes: list[tuple[str, str]]) -> None:
    text = index_path.read_text(encoding="utf-8").rstrip() + "\n\n"
    text += "## API 分类\n\n"
    text += "\n".join(f"- [{label}]({absolute_route(route)})" for label, route in category_routes) + "\n"
    index_path.write_text(text, encoding="utf-8")


def copy_openapi_specs(spec_source_root: Path, spec_target_root: Path) -> int:
    spec_target_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    for source_path in sorted(spec_source_root.glob("*.bundled.yaml")):
        target_path = spec_target_root / source_path.name
        shutil.copyfile(source_path, target_path)
        copied += 1
    return copied


def main() -> None:
    args = parse_args()
    source_root = Path(args.source).resolve()
    target_root = Path(args.target).resolve()
    spec_source_root = Path(args.spec_source).resolve()
    spec_target_root = Path(args.spec_target).resolve()

    if target_root.exists():
        shutil.rmtree(target_root)
    if spec_target_root.exists():
        shutil.rmtree(spec_target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    rendered = 0
    for source_path in iter_source_pages(source_root):
        rel_path = source_path.relative_to(source_root)
        target_path = source_rel_to_target(rel_path, target_root)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        converted = convert_page(source_path.read_text(encoding="utf-8"), source_root, rel_path)
        target_path.write_text(converted, encoding="utf-8")
        rendered += 1

    append_root_links(
        target_root / "index.mdx",
        [
            ("对话接口", TOP_LEVEL_MAP["conversation"]),
            ("图像生成", TOP_LEVEL_MAP["image-generations"]),
            ("图像编辑", TOP_LEVEL_MAP["image-edits"]),
            ("音频转录", TOP_LEVEL_MAP["audio-transcriptions"]),
        ],
    )
    copied = copy_openapi_specs(spec_source_root, spec_target_root)
    print(f"Rendered {rendered} pages into {target_root}")
    print(f"Copied {copied} bundled specs into {spec_target_root}")


if __name__ == "__main__":
    main()
