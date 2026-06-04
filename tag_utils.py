def parse_tags(value):
    """解析用户输入的标记文本，支持多种中英文分隔符并去重。"""
    normalized = value
    for separator in ("，", "、", ";", "；"):
        normalized = normalized.replace(separator, ",")

    tags = []
    seen = set()
    for tag in normalized.split(","):
        tag = tag.strip()
        key = tag.casefold()
        if tag and key not in seen:
            tags.append(tag)
            seen.add(key)
    return tags


def format_tags(tags):
    """把标记列表格式化成界面中展示的文本。"""
    return ", ".join(tags)


def tags_match(image_tag_values, query_tag_values):
    """普通筛选：图片包含任意一个目标标记即命中。"""
    image_tag_keys = {tag.casefold() for tag in image_tag_values}
    return any(tag.casefold() in image_tag_keys for tag in query_tag_values)


def tags_exact_match(image_tag_values, query_tag_values):
    """精确筛选：图片标记集合必须和查询标记集合完全一致。"""
    image_tag_keys = {tag.casefold() for tag in image_tag_values}
    query_tag_keys = {tag.casefold() for tag in query_tag_values}
    return image_tag_keys == query_tag_keys
