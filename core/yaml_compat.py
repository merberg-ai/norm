from __future__ import annotations

import re
from typing import Any

try:  # Prefer real PyYAML when installed.
    import yaml as _pyyaml  # type: ignore
except Exception:  # noqa: BLE001
    _pyyaml = None


class SimpleYamlError(ValueError):
    pass


def safe_load(text: str) -> Any:
    if _pyyaml is not None:
        return _pyyaml.safe_load(text)
    return _simple_yaml_load(text)


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
    return line


def _prepare_lines(text: str) -> list[tuple[int, str]]:
    prepared: list[tuple[int, str]] = []
    for raw in text.splitlines():
        raw = _strip_comment(raw).rstrip()
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2 != 0:
            raise SimpleYamlError(f"Only 2-space YAML indentation is supported by fallback parser: {raw!r}")
        prepared.append((indent, raw.strip()))
    return prepared


def _simple_yaml_load(text: str) -> Any:
    lines = _prepare_lines(text)
    if not lines:
        return None
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise SimpleYamlError(f"Unexpected YAML content near: {lines[index]}")
    return value


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, content = lines[index]
    if current_indent != indent:
        raise SimpleYamlError(f"Expected indent {indent}, got {current_indent}: {content!r}")
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_dict(lines, index, indent)


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"Unexpected nested list content: {content!r}")
        if not content.startswith("- "):
            break
        item_text = content[2:].strip()
        if not item_text:
            child, index = _parse_block(lines, index + 1, indent + 2)
            result.append(child)
            continue
        if ":" in item_text and not _looks_like_quoted_scalar(item_text):
            # Basic support for '- key: value' objects.
            key, value_text = item_text.split(":", 1)
            item: dict[str, Any] = {key.strip(): _parse_scalar(value_text.strip()) if value_text.strip() else {}}
            index += 1
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_dict(lines, index, indent + 2)
                item = _merge_dicts(item, child)
            result.append(item)
        else:
            result.append(_parse_scalar(item_text))
            index += 1
    return result, index


def _parse_dict(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"Unexpected nested mapping content: {content!r}")
        if content.startswith("- "):
            break
        if ":" not in content:
            raise SimpleYamlError(f"Expected key/value mapping: {content!r}")
        key, value_text = content.split(":", 1)
        key = key.strip()
        value_text = value_text.strip()
        if not key:
            raise SimpleYamlError(f"Empty YAML key: {content!r}")
        index += 1
        if value_text:
            result[key] = _parse_scalar(value_text)
        else:
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, indent + 2)
                result[key] = child
            else:
                result[key] = {}
    return result, index


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "yes", "on"}:
        return True
    if lower in {"false", "no", "off"}:
        return False
    if lower in {"null", "none", "~"}:
        return None
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if re.fullmatch(r"[-+]?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(\d+\.\d*|\d*\.\d+)", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value


def _looks_like_quoted_scalar(value: str) -> bool:
    return (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))


def _merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    out.update(b)
    return out
