import json
from pathlib import Path


CONFIG_FILE_NAME = "图片标注配置.md"
JSON_BEGIN = "```json"
JSON_END = "```"


def _relative_path(path, base_dir):
    """Return a stable relative path for the Markdown config when possible."""
    try:
        return Path(path).resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def _extract_json_block(text):
    """Extract the JSON payload from the Markdown code block."""
    begin = text.find(JSON_BEGIN)
    if begin == -1:
        begin = text.find("{")
        end = text.rfind("}")
        return text[begin : end + 1] if begin != -1 and end != -1 and end >= begin else "{}"

    begin += len(JSON_BEGIN)
    end = text.find(JSON_END, begin)
    return text[begin:end].strip() if end != -1 else text[begin:].strip()


def _clean_tags(value):
    if not isinstance(value, list):
        return []
    return [str(tag).strip() for tag in value if str(tag).strip()]


def _clean_rectangle(value):
    if not isinstance(value, dict):
        return None
    try:
        return {
            "center_x": float(value.get("center_x", 0)),
            "center_y": float(value.get("center_y", 0)),
            "width": max(float(value.get("width", 1)), 1),
            "height": max(float(value.get("height", 1)), 1),
            "angle": float(value.get("angle", 0)),
            "tag": str(value.get("tag", "")).strip(),
        }
    except (TypeError, ValueError):
        return None


def load_annotation_config(config_path, image_paths, match_by_name=False):
    """Load image tags and rectangle annotations from the Markdown config."""
    config_path = Path(config_path)
    data = json.loads(_extract_json_block(config_path.read_text(encoding="utf-8")))
    image_lookup = {Path(path).resolve(): Path(path) for path in image_paths}
    name_lookup = {}
    if match_by_name:
        for path in image_paths:
            name_lookup.setdefault(Path(path).name.casefold(), Path(path))
    loaded_tags = {}
    loaded_rectangles = {}

    for item in data.get("images", []):
        if not isinstance(item, dict):
            continue
        stored_path = item.get("path")
        if not stored_path:
            continue
        absolute_path = Path(stored_path)
        if not absolute_path.is_absolute():
            absolute_path = config_path.parent / absolute_path

        image_path = image_lookup.get(absolute_path.resolve())
        if image_path is None and match_by_name:
            image_path = name_lookup.get(Path(stored_path).name.casefold())
        if image_path is None and match_by_name and item.get("name"):
            image_path = name_lookup.get(str(item["name"]).casefold())
        if image_path is None:
            continue

        tags = _clean_tags(item.get("tags", []))
        rectangles = [
            rectangle
            for rectangle in (_clean_rectangle(rectangle) for rectangle in item.get("rectangles", []))
            if rectangle is not None
        ]
        if tags:
            loaded_tags[image_path] = tags
        if rectangles:
            loaded_rectangles[image_path] = rectangles

    return loaded_tags, loaded_rectangles


def save_annotation_config(config_path, image_paths, image_tags, image_rectangles):
    """Write image annotation state to a readable Markdown config file."""
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    base_dir = config_path.parent
    existing_images = []
    if config_path.exists():
        try:
            existing_data = json.loads(_extract_json_block(config_path.read_text(encoding="utf-8")))
            existing_images = [item for item in existing_data.get("images", []) if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            existing_images = []

    current_items = [
        {
            "path": _relative_path(path, base_dir),
            "name": Path(path).name,
            "tags": list(image_tags.get(path, [])),
            "rectangles": [dict(rectangle) for rectangle in image_rectangles.get(path, [])],
        }
        for path in image_paths
    ]
    current_keys = {item["path"] for item in current_items}
    data = {
        "version": 1,
        "images": [item for item in existing_images if item.get("path") not in current_keys] + current_items,
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    config_path.write_text(
        "# 图片标注配置\n\n"
        "该文件由看图软件 demo 自动生成，用于记录图片标记和矩形框标注。\n\n"
        f"{JSON_BEGIN}\n{payload}\n{JSON_END}\n",
        encoding="utf-8",
    )
