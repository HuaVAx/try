from pathlib import Path

from PIL import Image, ImageOps


def load_thumbnail(file_path, max_size, resampling):
    """快速加载缩略图，优先降低大图解码成本。"""
    image = Image.open(file_path)
    image.draft("RGB", max_size)
    image = ImageOps.exif_transpose(image)
    image.thumbnail(max_size, resampling)
    return image.copy()


def crop_rotated_rectangle(image_path, rectangle, output_dir):
    """按旋转矩形裁剪图片，并把裁剪结果保存到指定目录。"""
    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image).convert("RGB")

    center_x = rectangle["center_x"]
    center_y = rectangle["center_y"]
    width = max(rectangle["width"], 1)
    height = max(rectangle["height"], 1)
    angle = rectangle["angle"]

    aligned = image.rotate(-angle, center=(center_x, center_y), resample=Image.Resampling.BICUBIC)
    left = max(int(center_x - width / 2), 0)
    top = max(int(center_y - height / 2), 0)
    right = min(int(center_x + width / 2), aligned.width)
    bottom = min(int(center_y + height / 2), aligned.height)
    if right <= left or bottom <= top:
        return None

    output_dir.mkdir(exist_ok=True)
    tag = rectangle["tag"] or "untagged"
    safe_tag = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in tag)
    output_path = rectangle.get("crop_path")
    if output_path is not None:
        output_path = Path(output_path)
    if output_path is None or output_path.parent != output_dir:
        output_path = output_dir / f"{Path(image_path).stem}_{safe_tag}_{id(rectangle)}.png"
        rectangle["crop_path"] = output_path

    aligned.crop((left, top, right, bottom)).save(output_path)
    return output_path
