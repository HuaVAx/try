# 文件选择框和文件夹扫描共用的图片格式配置。
SUPPORTED_IMAGE_TYPES = (
    ("图片文件", "*.jpg *.jpeg *.png *.bmp"),
    ("JPG 图片", "*.jpg *.jpeg"),
    ("PNG 图片", "*.png"),
    ("BMP 图片", "*.bmp"),
    ("所有文件", "*.*"),
)
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}

# 主界面视图模式。
SINGLE_MODE = "single"
MULTI_MODE = "multi"
EDIT_MODE = "edit"

# 多图浏览布局配置。
MULTI_COLUMNS = 4
THUMBNAIL_SIZE = (160, 160)
