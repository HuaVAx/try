import tkinter as tk
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from math import atan2, cos, degrees, radians, sin
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

from annotation_config import CONFIG_FILE_NAME, load_annotation_config, save_annotation_config
from app_config import (
    EDIT_MODE,
    MULTI_COLUMNS,
    MULTI_MODE,
    SINGLE_MODE,
    SUPPORTED_IMAGE_SUFFIXES,
    SUPPORTED_IMAGE_TYPES,
    THUMBNAIL_SIZE,
)
from image_utils import load_thumbnail
from tag_utils import format_tags, parse_tags, tags_exact_match, tags_match


def main():
    root = tk.Tk()
    root.title("Simple UI")
    root.geometry("1200x800")
    root.configure(bg="#ffffff")
    root.minsize(1000, 650)
    root.option_add("*Font", ("Microsoft YaHei UI", 9))

    def style_button(button, kind="default"):
        colors = {
            "default": ("#f4f7fb", "#1f2937", "#e8eef7", "#d6deea"),
            "primary": ("#e8f1ff", "#1358b7", "#d8e8ff", "#aac8f7"),
            "danger": ("#fff1f0", "#b42318", "#ffe4e2", "#ffccc7"),
        }
        background, foreground, active_background, border = colors.get(kind, colors["default"])
        button.configure(
            bg=background,
            fg=foreground,
            activebackground=active_background,
            activeforeground=foreground,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor="#8bb7f0",
            padx=12,
            pady=6,
            cursor="hand2",
            takefocus=True,
        )

    def style_entry(entry):
        entry.configure(
            bg="#ffffff",
            fg="#111827",
            insertbackground="#2563eb",
            relief=tk.SOLID,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#d6deea",
            highlightcolor="#8bb7f0",
        )

    all_image_paths = []
    image_paths = []
    image_tags = {}
    image_rectangles = {}
    edit_undo_stack = []
    multi_select_undo_stack = []
    selected_image_paths = set()
    thumbnail_images = []
    thumbnail_buttons = {}
    thumbnail_click_job = {"id": None}
    thumbnail_queue = Queue()
    multi_render_generation = tk.IntVar(value=0)
    multi_grid_dirty = tk.BooleanVar(value=False)
    current_image_index = tk.IntVar(value=-1)
    view_mode = tk.StringVar(value=SINGLE_MODE)
    multi_select_mode = tk.BooleanVar(value=False)
    filter_active = tk.BooleanVar(value=False)
    last_multi_position = tk.DoubleVar(value=0.0)
    last_multi_top_index = tk.IntVar(value=0)
    can_return_to_multi = tk.BooleanVar(value=False)
    edit_state = {
        "image": None,
        "photo": None,
        "preview_photo": None,
        "scale": 1.0,
        "offset_x": 0,
        "offset_y": 0,
        "drawing": False,
        "rotating": False,
        "resizing": False,
        "moving_rectangle": False,
        "resize_anchor": None,
        "resize_angle": 0.0,
        "move_start_x": 0,
        "move_start_y": 0,
        "move_origin_x": 0,
        "move_origin_y": 0,
        "active_index": None,
        "start_x": 0,
        "start_y": 0,
        "draw_enabled": False,
        "rectangle_started": False,
        "panning": False,
        "pan_x": 0,
        "pan_y": 0,
        "pan_start_x": 0,
        "pan_start_y": 0,
        "pan_moved": False,
        "last_drag_release": 0.0,
        "path": None,
        "suspend_render": False,
    }
    object_list_updating = tk.BooleanVar(value=False)
    single_load_generation = {"value": 0}
    active_config_path = {"path": None}
    config_save_error_shown = {"value": False}
    executor = ThreadPoolExecutor(max_workers=4)

    bottom_bar = tk.Frame(root, bg="#ffffff")
    bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
    tk.Frame(bottom_bar, bg="#cfe6ff", height=1).pack(fill=tk.X, padx=12, pady=(0, 8))
    toolbar = tk.Frame(bottom_bar, bg="#ffffff")
    toolbar.pack(fill=tk.X, padx=12, pady=(0, 8))

    right_actions = tk.Frame(toolbar, bg="#ffffff")
    multi_select_frame = tk.Frame(toolbar, bg="#ffffff")
    multi_select_button = tk.Button(multi_select_frame, text="多选")
    select_all_button = tk.Button(multi_select_frame, text="全选")
    mode_button = tk.Button(right_actions, text="多图浏览")
    selected_add_tag_button = tk.Button(right_actions, text="添加标记")
    selected_clear_tag_button = tk.Button(right_actions, text="清除标记")
    multi_undo_button = tk.Button(right_actions, text="撤销")
    filter_button = tk.Button(right_actions, text="筛选")
    delete_button = tk.Button(right_actions, text="删除图片")

    for button in (
        multi_select_button,
        select_all_button,
        multi_undo_button,
        selected_add_tag_button,
        selected_clear_tag_button,
        filter_button,
    ):
        style_button(button)
    style_button(mode_button, "primary")
    style_button(delete_button, "danger")

    multi_select_frame.pack(side=tk.LEFT)
    multi_select_button.pack(side=tk.LEFT)
    select_all_button.pack(side=tk.LEFT, padx=(6, 0))
    right_actions.pack(side=tk.RIGHT)
    mode_button.pack(side=tk.LEFT, padx=(0, 6))
    selected_add_tag_button.pack(side=tk.LEFT, padx=(0, 6))
    selected_clear_tag_button.pack(side=tk.LEFT, padx=(0, 6))
    multi_undo_button.pack(side=tk.LEFT, padx=(0, 6))
    filter_button.pack(side=tk.LEFT, padx=(0, 6))
    delete_button.pack(side=tk.LEFT)

    content = tk.Frame(root, bg="#ffffff")
    content.pack(fill=tk.BOTH, expand=True)

    single_frame = tk.Frame(content, bg="#ffffff")
    single_frame.pack(fill=tk.BOTH, expand=True)

    image_label = tk.Label(single_frame, bg="#ffffff")
    image_label.pack(expand=True)
    edit_canvas = tk.Canvas(
        single_frame,
        bg="#ffffff",
        highlightthickness=1,
        highlightbackground="#cfe6ff",
        highlightcolor="#cfe6ff",
    )
    single_name_label = tk.Label(
        single_frame,
        bg="#e8f1ff",
        fg="#1358b7",
        padx=10,
        pady=6,
        font=("Microsoft YaHei UI", 10, "bold"),
    )

    object_panel = tk.Frame(single_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#cfe6ff", width=220)
    tk.Label(object_panel, text="矩形框对象", bg="#e8f1ff", fg="#1358b7", padx=10, pady=6).pack(fill=tk.X)
    object_list_container = tk.Frame(object_panel, bg="#ffffff")
    object_list_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 6))
    rectangle_listbox = tk.Listbox(
        object_list_container,
        height=12,
        exportselection=False,
        relief=tk.SOLID,
        borderwidth=1,
        highlightthickness=1,
        highlightbackground="#d6deea",
        highlightcolor="#8bb7f0",
    )
    rectangle_list_scrollbar = tk.Scrollbar(object_list_container, orient=tk.VERTICAL, command=rectangle_listbox.yview)
    rectangle_listbox.configure(yscrollcommand=rectangle_list_scrollbar.set)
    rectangle_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    rectangle_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    rectangle_object_menu = tk.Menu(root, tearoff=0)
    object_list_buttons = tk.Frame(object_panel, bg="#ffffff")
    object_list_buttons.pack(fill=tk.X, padx=8, pady=(0, 8))
    rename_rectangle_button = tk.Button(object_list_buttons, text="改名")
    delete_rectangle_button = tk.Button(object_list_buttons, text="删除")
    rename_rectangle_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
    delete_rectangle_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
    object_panel.pack_propagate(False)
    rectangle_name_editor = {"entry": None, "index": None, "committing": False}
    rectangle_object_menu.add_command(label="改名标记", command=lambda: start_inline_rename_rectangle())
    rectangle_object_menu.add_command(label="清空标记", command=lambda: clear_active_rectangle_tag())
    rectangle_object_menu.add_separator()
    rectangle_object_menu.add_command(label="删除矩形框", command=lambda: delete_active_rectangle())

    controls = tk.Frame(root, bg="#ffffff")
    return_controls = tk.Frame(controls, bg="#ffffff")
    navigation_controls = tk.Frame(controls, bg="#ffffff")
    return_button = tk.Button(return_controls, text="返回")
    previous_button = tk.Button(navigation_controls, text="上一张")
    image_count_label = tk.Label(navigation_controls, bg="#ffffff", fg="#333333")
    next_button = tk.Button(navigation_controls, text="下一张")

    edit_controls = tk.Frame(root, bg="#ffffff")
    edit_mode_notice = tk.Label(
        edit_controls,
        text="编辑模式",
        bg="#1d4ed8",
        fg="#ffffff",
        padx=16,
        pady=7,
        font=("Microsoft YaHei UI", 11, "bold"),
    )
    edit_label = tk.Label(edit_controls, text="图片标记", bg="#ffffff", fg="#333333")
    tag_entry = tk.Entry(edit_controls, width=18)
    box_tag_label = tk.Label(edit_controls, text="矩形标记", bg="#ffffff", fg="#333333")
    box_tag_entry = tk.Entry(edit_controls, width=18)
    angle_label = tk.Label(edit_controls, text="旋转", bg="#ffffff", fg="#333333")
    angle_scale = tk.Scale(
        edit_controls,
        from_=-180,
        to=180,
        orient=tk.HORIZONTAL,
        length=140,
        resolution=1,
        showvalue=True,
        bg="#ffffff",
        highlightthickness=0,
    )
    save_tag_button = tk.Button(edit_controls, text="保存标记")
    draw_box_button = tk.Button(edit_controls, text="画矩形框")
    edit_previous_button = tk.Button(edit_controls, text="上一张")
    edit_info_label = tk.Label(
        edit_controls,
        bg="#e8f1ff",
        fg="#1358b7",
        font=("Microsoft YaHei UI", 9, "bold"),
        anchor=tk.CENTER,
        wraplength=360,
        justify=tk.CENTER,
        padx=8,
        pady=4,
    )
    edit_page_label = tk.Label(
        edit_controls,
        text="0 / 0",
        bg="#ffffff",
        fg="#1f2937",
        font=("Microsoft YaHei UI", 10, "bold"),
        width=10,
        anchor=tk.CENTER,
    )
    edit_next_button = tk.Button(edit_controls, text="下一张")
    undo_button = tk.Button(edit_controls, text="撤销")
    exit_edit_button = tk.Button(edit_controls, text="退出编辑")

    for button in (
        previous_button,
        next_button,
        save_tag_button,
        draw_box_button,
        edit_previous_button,
        edit_next_button,
        undo_button,
        rename_rectangle_button,
        delete_rectangle_button,
    ):
        style_button(button)
    style_button(return_button, "primary")
    style_button(exit_edit_button, "primary")
    for entry in (tag_entry, box_tag_entry):
        style_entry(entry)
    undo_button.configure(width=10)
    exit_edit_button.configure(width=10)
    angle_scale.configure(
        troughcolor="#eef2f7",
        activebackground="#d8e8ff",
        sliderrelief=tk.FLAT,
        borderwidth=0,
    )

    multi_frame = tk.Frame(content, bg="#ffffff")
    multi_canvas = tk.Canvas(multi_frame, bg="#ffffff", highlightthickness=0)
    multi_scrollbar = tk.Scrollbar(
        multi_frame,
        orient=tk.VERTICAL,
        command=multi_canvas.yview,
    )
    multi_grid = tk.Frame(multi_canvas, bg="#ffffff")
    multi_grid_window = multi_canvas.create_window((0, 0), window=multi_grid, anchor="nw")

    multi_canvas.configure(yscrollcommand=multi_scrollbar.set)
    multi_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    multi_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    context_menu = tk.Menu(root, tearoff=0)
    context_menu_target = {"path": None}

    # 清空当前显示状态，用于删除最后一张图片或重置界面。
    def clear_display():
        current_image_index.set(-1)
        edit_state["image"] = None
        edit_state["photo"] = None
        edit_state["path"] = None
        edit_canvas.delete("all")
        single_name_label.configure(text="")
        controls.pack_forget()

    # 将当前图片标记和矩形框状态写入 Markdown 配置文件。
    def persist_annotation_config():
        config_path = active_config_path["path"]
        if config_path is None:
            return
        try:
            save_annotation_config(config_path, all_image_paths, image_tags, image_rectangles)
            config_save_error_shown["value"] = False
        except OSError as error:
            if not config_save_error_shown["value"]:
                config_save_error_shown["value"] = True
                messagebox.showerror("配置文件保存失败", f"无法写入标注配置文件：\n{config_path}\n\n{error}")

    # 打开图片或文件夹时，导入已有 Markdown 配置；不存在时生成空配置。
    def load_or_create_annotation_config(base_dir):
        config_path = Path(base_dir) / CONFIG_FILE_NAME
        active_config_path["path"] = config_path
        image_tags.clear()
        image_rectangles.clear()
        config_save_error_shown["value"] = False

        if config_path.exists():
            try:
                loaded_tags, loaded_rectangles = load_annotation_config(config_path, all_image_paths)
            except (OSError, ValueError) as error:
                messagebox.showerror("配置文件读取失败", f"无法读取标注配置文件：\n{config_path}\n\n{error}")
                return
            image_tags.update(loaded_tags)
            image_rectangles.update(loaded_rectangles)
        else:
            persist_annotation_config()

    def rectangle_identity(rectangle):
        return (
            round(float(rectangle.get("center_x", 0)), 3),
            round(float(rectangle.get("center_y", 0)), 3),
            round(float(rectangle.get("width", 0)), 3),
            round(float(rectangle.get("height", 0)), 3),
            round(float(rectangle.get("angle", 0)), 3),
            rectangle.get("tag", ""),
        )

    def rotated_rectangle_image_points(rectangle):
        center_x = float(rectangle.get("center_x", 0))
        center_y = float(rectangle.get("center_y", 0))
        half_width = max(float(rectangle.get("width", 1)), 1) / 2
        half_height = max(float(rectangle.get("height", 1)), 1) / 2
        angle = radians(float(rectangle.get("angle", 0)))
        corners = (
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        )
        return [
            (
                center_x + x * cos(angle) - y * sin(angle),
                center_y + x * sin(angle) + y * cos(angle),
            )
            for x, y in corners
        ]

    def axis_bbox_from_rectangle(rectangle):
        points = rotated_rectangle_image_points(rectangle)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        left = min(xs)
        top = min(ys)
        right = max(xs)
        bottom = max(ys)
        return left, top, max(right - left, 1), max(bottom - top, 1)

    def merge_imported_annotations(imported_tags, imported_rectangles):
        matched_paths = set(imported_tags) | set(imported_rectangles)
        added_tag_count = 0
        added_rectangle_count = 0
        for path in matched_paths:
            existing_tags = list(image_tags.get(path, []))
            existing_tag_keys = {tag.casefold() for tag in existing_tags}
            for tag in imported_tags.get(path, []):
                if tag.casefold() not in existing_tag_keys:
                    existing_tags.append(tag)
                    existing_tag_keys.add(tag.casefold())
                    added_tag_count += 1
            if existing_tags:
                image_tags[path] = existing_tags

            existing_rectangles = image_rectangles.setdefault(path, [])
            existing_rectangle_keys = {rectangle_identity(rectangle) for rectangle in existing_rectangles}
            for rectangle in imported_rectangles.get(path, []):
                rectangle_key = rectangle_identity(rectangle)
                if rectangle_key not in existing_rectangle_keys:
                    existing_rectangles.append(dict(rectangle))
                    existing_rectangle_keys.add(rectangle_key)
                    added_rectangle_count += 1
            if not existing_rectangles:
                image_rectangles.pop(path, None)

        if matched_paths:
            multi_grid_dirty.set(True)
            persist_annotation_config()
            update_single_name_label()
            if view_mode.get() == MULTI_MODE:
                render_multi_grid()
            elif view_mode.get() in (SINGLE_MODE, EDIT_MODE):
                if view_mode.get() == EDIT_MODE:
                    update_edit_controls()
                    update_rectangle_object_list()
                render_canvas_image()
        return len(matched_paths), added_tag_count, added_rectangle_count

    # 导入外部 Markdown 配置：不替换当前配置文件，而是把匹配图片的标记和矩形框追加合并。
    def import_annotation_config():
        if not all_image_paths:
            messagebox.showinfo("导入配置", "请先打开图片或文件夹，再导入配置文件。")
            return

        config_file = filedialog.askopenfilename(
            title="导入配置文件",
            filetypes=(("Markdown 配置文件", "*.md"), ("所有文件", "*.*")),
        )
        if not config_file:
            return

        try:
            imported_tags, imported_rectangles = load_annotation_config(config_file, all_image_paths, match_by_name=True)
        except (OSError, ValueError) as error:
            messagebox.showerror("导入配置失败", f"无法读取配置文件：\n{config_file}\n\n{error}")
            return

        matched_count, added_tag_count, added_rectangle_count = merge_imported_annotations(imported_tags, imported_rectangles)
        if not matched_count:
            messagebox.showinfo("导入配置", "没有找到与当前图片匹配的配置内容。")
            return

        messagebox.showinfo(
            "导入配置",
            f"已匹配 {matched_count} 张图片，追加 {added_tag_count} 个图片标记、{added_rectangle_count} 个矩形框。",
        )

    # 删除磁盘文件后，同步清理列表、标记、矩形框和撤销栈里的引用。
    def remove_deleted_image_from_state(path):
        while path in image_paths:
            image_paths.remove(path)
        while path in all_image_paths:
            all_image_paths.remove(path)

        selected_image_paths.discard(path)
        image_tags.pop(path, None)
        image_rectangles.pop(path, None)
        edit_undo_stack[:] = [item for item in edit_undo_stack if item.get("path") != path]
        for previous_tags in multi_select_undo_stack:
            previous_tags.pop(path, None)
        multi_select_undo_stack[:] = [previous_tags for previous_tags in multi_select_undo_stack if previous_tags]

    # 删除后根据当前模式刷新界面，保持当前索引落在有效范围内。
    def refresh_after_delete(old_index):
        update_undo_button()
        update_multi_select_controls()

        if not image_paths:
            clear_display()
            render_multi_grid()
            return

        current_image_index.set(min(max(old_index, 0), len(image_paths) - 1))
        if view_mode.get() == MULTI_MODE:
            render_multi_grid()
        else:
            show_single_mode()
            update_single_name_label()

    # 删除鼠标所在或当前浏览的单张图片，文件会直接从磁盘移除。
    def delete_image(path):
        if path is None:
            return

        path = Path(path)
        if not messagebox.askyesno("删除图片", f"确定要从磁盘删除这张图片吗？\n{path}"):
            return

        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            messagebox.showerror("删除失败", f"无法删除图片文件：\n{error}")
            return

        old_index = current_image_index.get()
        remove_deleted_image_from_state(path)
        persist_annotation_config()
        refresh_after_delete(old_index)

    # 批量删除所有选中的图片，并在完成后统一刷新界面。
    def delete_selected_images():
        selected_paths = [path for path in image_paths if path in selected_image_paths]
        if not selected_paths:
            messagebox.showinfo("删除图片", "当前没有选中的图片。")
            return

        if not messagebox.askyesno("删除图片", f"确定要从磁盘删除选中的 {len(selected_paths)} 张图片吗？"):
            return

        old_index = current_image_index.get()
        failed_count = 0
        for path in selected_paths:
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                failed_count += 1
                continue
            remove_deleted_image_from_state(path)

        persist_annotation_config()
        refresh_after_delete(old_index)
        if failed_count:
            messagebox.showwarning("删除完成", f"{failed_count} 张图片删除失败。")

    # 底部“删除图片”按钮入口：单图删除当前图，多选时删除所有选中图。
    def delete_current_image():
        if view_mode.get() == MULTI_MODE and multi_select_mode.get() and selected_image_paths:
            delete_selected_images()
            return
        if view_mode.get() not in (SINGLE_MODE, EDIT_MODE):
            return
        delete_image(current_image_path())

    # 右键菜单命令包装：菜单创建早于部分功能函数定义，点击时再调用真实逻辑。
    def export_selected_images_from_context_menu():
        export_selected_images()

    def add_tags_from_context_menu():
        add_tags_to_selected_images_from_toolbar()

    def clear_tags_from_context_menu():
        clear_tags_from_selected_images()

    def toggle_multi_select_from_context_menu():
        toggle_multi_select_mode()

    def toggle_select_all_from_context_menu():
        toggle_select_all_images()

    CONTEXT_MULTI_SELECT_INDEX = 0
    CONTEXT_SELECT_ALL_INDEX = 1
    CONTEXT_ADD_TAG_INDEX = 3
    CONTEXT_CLEAR_TAG_INDEX = 4
    CONTEXT_EXPORT_SELECTED_INDEX = 6
    CONTEXT_DELETE_SELECTED_INDEX = 9

    # 根据当前选择状态动态启用/禁用右键菜单项，并同步“全选/取消全选”文字。
    def show_context_menu(event, path):
        context_menu_target["path"] = path
        has_selected = bool(selected_image_paths)
        selected_state = tk.NORMAL if has_selected else tk.DISABLED
        is_multi_mode = view_mode.get() == MULTI_MODE
        all_selected = bool(image_paths) and all(image_path in selected_image_paths for image_path in image_paths)
        context_menu.entryconfigure(
            CONTEXT_MULTI_SELECT_INDEX,
            label="退出多选" if multi_select_mode.get() else "多选",
            state=tk.NORMAL if is_multi_mode else tk.DISABLED,
        )
        context_menu.entryconfigure(
            CONTEXT_SELECT_ALL_INDEX,
            label="取消全选" if all_selected else "全选",
            state=tk.NORMAL if is_multi_mode and image_paths else tk.DISABLED,
        )
        for index in (CONTEXT_ADD_TAG_INDEX, CONTEXT_CLEAR_TAG_INDEX, CONTEXT_EXPORT_SELECTED_INDEX, CONTEXT_DELETE_SELECTED_INDEX):
            context_menu.entryconfigure(index, state=selected_state)
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    context_menu.add_command(
        label="多选",
        command=toggle_multi_select_from_context_menu,
    )
    context_menu.add_command(
        label="全选",
        command=toggle_select_all_from_context_menu,
    )
    context_menu.add_separator()
    context_menu.add_command(
        label="添加标记",
        command=add_tags_from_context_menu,
    )
    context_menu.add_command(
        label="清除标记",
        command=clear_tags_from_context_menu,
    )
    context_menu.add_separator()
    context_menu.add_command(
        label="导出选中图片",
        command=export_selected_images_from_context_menu,
    )
    context_menu.add_separator()
    context_menu.add_command(
        label="删除图片",
        command=lambda: delete_image(context_menu_target["path"]),
    )
    context_menu.add_command(
        label="删除所有选中图片",
        command=delete_selected_images,
    )

    # 刷新多选区域按钮状态，包括多选高亮、全选文字和撤销可用状态。
    def update_multi_select_controls():
        if view_mode.get() == MULTI_MODE:
            multi_select_frame.pack(side=tk.LEFT)
            all_selected = bool(image_paths) and all(path in selected_image_paths for path in image_paths)
            multi_select_button.configure(
                relief=tk.SUNKEN if multi_select_mode.get() else tk.RAISED,
                text="退出多选" if multi_select_mode.get() else "多选",
            )
            select_all_button.configure(text="取消全选" if all_selected else "全选")
            if multi_select_mode.get():
                multi_undo_button.configure(state=tk.NORMAL if multi_select_undo_stack else tk.DISABLED)
            else:
                multi_undo_button.configure(state=tk.NORMAL if multi_select_undo_stack else tk.DISABLED)
        else:
            multi_select_frame.pack_forget()

    # 根据图片是否被选中，更新缩略图边框和背景色。
    def update_thumbnail_selection(index):
        button = thumbnail_buttons.get(index)
        if button is None:
            return

        path = image_paths[index]
        selected = path in selected_image_paths
        button.configure(
            bg="#eaf4ff" if selected else "#ffffff",
            activebackground="#dbeeff" if selected else "#f2f2f2",
            highlightthickness=3 if selected else 1,
            highlightbackground="#9ecbff" if selected else "#ffffff",
            highlightcolor="#9ecbff" if selected else "#ffffff",
            relief=tk.SOLID if selected else tk.FLAT,
            borderwidth=2 if selected else 1,
        )

    # 多选模式下单击缩略图时，切换该图片的选中状态。
    def toggle_image_selection(index):
        if not 0 <= index < len(image_paths):
            return

        path = image_paths[index]
        if path in selected_image_paths:
            selected_image_paths.remove(path)
        else:
            selected_image_paths.add(path)
        update_thumbnail_selection(index)
        update_multi_select_controls()

    # 开启/退出多选模式；退出时清空已选图片，避免误操作。
    def toggle_multi_select_mode():
        multi_select_mode.set(not multi_select_mode.get())
        if not multi_select_mode.get():
            selected_image_paths.clear()
            multi_select_undo_stack.clear()
            for index in range(len(image_paths)):
                update_thumbnail_selection(index)
        update_multi_select_controls()

    # 全选按钮入口：必要时自动进入多选模式，并同步所有缩略图选中样式。
    def toggle_select_all_images():
        if view_mode.get() == MULTI_MODE and not multi_select_mode.get():
            multi_select_mode.set(True)
        all_selected = bool(image_paths) and all(path in selected_image_paths for path in image_paths)
        if all_selected:
            selected_image_paths.clear()
        else:
            selected_image_paths.update(image_paths)
        for index in range(len(image_paths)):
            update_thumbnail_selection(index)
        update_multi_select_controls()

    # 弹出批量添加标记输入框，返回用户输入的标记文本。
    def ask_selected_tags(title="添加标记", prompt="输入要添加的标记："):
        dialog = tk.Toplevel(root)
        dialog.title(title)
        dialog.configure(bg="#ffffff")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()

        result = {"confirmed": False, "text": ""}
        value = tk.StringVar()

        tk.Label(
            dialog,
            text=prompt,
            bg="#ffffff",
            fg="#333333",
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 8), sticky=tk.W)

        entry = tk.Entry(dialog, width=34, textvariable=value)
        style_entry(entry)
        entry.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky=tk.EW)

        buttons = tk.Frame(dialog, bg="#ffffff")
        buttons.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 16), sticky=tk.E)

        def confirm():
            result["confirmed"] = True
            result["text"] = value.get()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        confirm_button = tk.Button(buttons, text="确定", command=confirm)
        cancel_button = tk.Button(buttons, text="取消", command=cancel)
        style_button(confirm_button, "primary")
        style_button(cancel_button)
        confirm_button.pack(side=tk.LEFT, padx=(0, 8))
        cancel_button.pack(side=tk.LEFT)

        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: cancel())
        entry.focus_set()

        root.update_idletasks()
        x = root.winfo_rootx() + max((root.winfo_width() - dialog.winfo_reqwidth()) // 2, 0)
        y = root.winfo_rooty() + max((root.winfo_height() - dialog.winfo_reqheight()) // 2, 0)
        dialog.geometry(f"+{x}+{y}")
        root.wait_window(dialog)
        return result["text"] if result["confirmed"] else None

    # 给所有选中图片追加标记，同名标记去重，并记录到批量撤销栈。
    def add_tags_to_selected_images_from_toolbar():
        selected_paths = [path for path in image_paths if path in selected_image_paths]
        if not selected_paths:
            messagebox.showinfo("添加标记", "请先选择图片。")
            return

        tag_text = ask_selected_tags()
        if tag_text is None:
            return

        tags_to_add = parse_tags(tag_text)
        if not tags_to_add:
            messagebox.showinfo("添加标记", "请输入要添加的标记。")
            return

        previous_tags = {path: list(image_tags.get(path, [])) for path in selected_paths}
        changed = False
        for path in selected_paths:
            existing_tags = list(image_tags.get(path, []))
            existing_keys = {tag.casefold() for tag in existing_tags}
            for tag in tags_to_add:
                if tag.casefold() not in existing_keys:
                    existing_tags.append(tag)
                    existing_keys.add(tag.casefold())
                    changed = True
            if existing_tags:
                image_tags[path] = existing_tags

        if changed:
            multi_select_undo_stack.append(previous_tags)
            persist_annotation_config()
            render_multi_grid()
        update_multi_select_controls()

    # 清除所有选中图片的标记，并记录到批量撤销栈。
    def clear_tags_from_selected_images():
        selected_paths = [path for path in image_paths if path in selected_image_paths]
        if not selected_paths:
            messagebox.showinfo("清除标记", "请先选择图片。")
            return

        previous_tags = {path: list(image_tags.get(path, [])) for path in selected_paths}
        changed = False
        for path in selected_paths:
            if path in image_tags:
                image_tags.pop(path, None)
                changed = True

        if changed:
            multi_select_undo_stack.append(previous_tags)
            persist_annotation_config()
            render_multi_grid()
        update_multi_select_controls()

    # 撤销最近一次批量添加或清除标记操作。
    def undo_multi_select_tags():
        if not multi_select_undo_stack:
            return

        previous_tags = multi_select_undo_stack.pop()
        for path, tags in previous_tags.items():
            if tags:
                image_tags[path] = tags
            else:
                image_tags.pop(path, None)

        persist_annotation_config()
        render_multi_grid()
        update_multi_select_controls()

    # 多图网格尺寸变化后，刷新滚动区域。
    def update_multi_scroll_region(_event=None):
        multi_canvas.configure(scrollregion=multi_canvas.bbox("all"))

    def update_multi_grid_width(event):
        multi_canvas.itemconfigure(multi_grid_window, width=event.width)

    def scroll_multi_grid(event):
        if view_mode.get() != MULTI_MODE:
            return
        multi_canvas.yview_scroll(int(-3 * (event.delta / 120)), "units")

    multi_grid.bind("<Configure>", update_multi_scroll_region)
    multi_canvas.bind("<Configure>", update_multi_grid_width)
    multi_canvas.bind_all("<MouseWheel>", scroll_multi_grid)

    def get_display_size():
        return (
            max(root.winfo_width() - 40, 1),
            max(root.winfo_height() - 160, 1),
        )

    # 刷新单图底部的上一张/下一张、页码和返回按钮。
    def update_controls():
        total = len(image_paths)
        index = current_image_index.get()

        edit_controls.pack_forget()
        for widget in (return_controls, navigation_controls, return_button, previous_button, image_count_label, next_button):
            widget.pack_forget()

        if view_mode.get() != SINGLE_MODE:
            controls.pack_forget()
            return

        has_controls = False
        if total > 1:
            previous_button.configure(state=tk.NORMAL if index > 0 else tk.DISABLED)
            image_count_label.configure(text=f"{index + 1} / {total}")
            next_button.configure(state=tk.NORMAL if index < total - 1 else tk.DISABLED)
            previous_button.pack(side=tk.LEFT, padx=8)
            image_count_label.pack(side=tk.LEFT, padx=8)
            next_button.pack(side=tk.LEFT, padx=8)
            navigation_controls.pack()
            if can_return_to_multi.get():
                return_button.pack()
                return_controls.pack(pady=(6, 0))
            has_controls = True
        elif can_return_to_multi.get():
            return_button.pack()
            return_controls.pack()
            has_controls = True

        if has_controls:
            controls.pack(pady=(0, 16))
        else:
            controls.pack_forget()

    # 返回当前索引对应的图片路径；索引无效时返回 None。
    def current_image_path():
        index = current_image_index.get()
        if not 0 <= index < len(image_paths):
            return None
        return image_paths[index]

    def image_info_text(path):
        if path is None:
            return ""
        tag_text = format_tags(image_tags.get(path, []))
        return f"{Path(path).name}    ★ 标记：{tag_text}" if tag_text else Path(path).name

    def update_single_name_label():
        path = current_image_path()
        single_name_label.configure(text=image_info_text(path))

    # 将画布坐标转换成原图坐标，供画框、缩放和命中检测使用。
    def canvas_to_image(canvas_x, canvas_y):
        return (
            (canvas_x - edit_state["offset_x"]) / edit_state["scale"],
            (canvas_y - edit_state["offset_y"]) / edit_state["scale"],
        )

    # 将原图坐标转换成画布坐标，供矩形框绘制使用。
    def image_to_canvas(image_x, image_y):
        return (
            image_x * edit_state["scale"] + edit_state["offset_x"],
            image_y * edit_state["scale"] + edit_state["offset_y"],
        )

    # 计算旋转矩形四个角在画布上的坐标。
    def rotated_rectangle_points(rectangle):
        center_x, center_y = image_to_canvas(rectangle["center_x"], rectangle["center_y"])
        width = rectangle["width"] * edit_state["scale"]
        height = rectangle["height"] * edit_state["scale"]
        angle = radians(rectangle["angle"])
        half_width = width / 2
        half_height = height / 2
        corners = [
            (-half_width, -half_height),
            (half_width, -half_height),
            (half_width, half_height),
            (-half_width, half_height),
        ]
        points = []
        for x, y in corners:
            points.extend((
                center_x + x * cos(angle) - y * sin(angle),
                center_y + x * sin(angle) + y * cos(angle),
            ))
        return points

    def rotated_rectangle_corner_points(rectangle):
        points = rotated_rectangle_points(rectangle)
        return [(points[index], points[index + 1]) for index in range(0, len(points), 2)]

    # 计算旋转手柄位置，放在矩形框外侧避免遮挡框内图片。
    def rotation_handle_point(rectangle):
        center_x, center_y = image_to_canvas(rectangle["center_x"], rectangle["center_y"])
        height = rectangle["height"] * edit_state["scale"]
        angle = radians(rectangle["angle"])
        local_x = 0
        local_y = -height / 2 - 28
        return (
            center_x + local_x * cos(angle) - local_y * sin(angle),
            center_y + local_x * sin(angle) + local_y * cos(angle),
        )

    # 判断鼠标点是否落在某个旋转矩形内部。
    def point_in_rotated_rectangle(canvas_x, canvas_y, rectangle):
        center_x, center_y = image_to_canvas(rectangle["center_x"], rectangle["center_y"])
        angle = radians(-rectangle["angle"])
        dx = canvas_x - center_x
        dy = canvas_y - center_y
        local_x = dx * cos(angle) - dy * sin(angle)
        local_y = dx * sin(angle) + dy * cos(angle)
        half_width = rectangle["width"] * edit_state["scale"] / 2
        half_height = rectangle["height"] * edit_state["scale"] / 2
        return abs(local_x) <= half_width and abs(local_y) <= half_height

    # 从上层到下层查找鼠标命中的矩形框。
    def find_rectangle_at(canvas_x, canvas_y):
        path = current_image_path()
        if path is None:
            return None

        rectangles = image_rectangles.get(path, [])
        for index in range(len(rectangles) - 1, -1, -1):
            if point_in_rotated_rectangle(canvas_x, canvas_y, rectangles[index]):
                return index
        return None

    # 查找鼠标是否命中旋转手柄。
    def find_rotation_handle(canvas_x, canvas_y):
        path = current_image_path()
        if path is None:
            return None

        rectangles = image_rectangles.get(path, [])
        for index in range(len(rectangles) - 1, -1, -1):
            handle_x, handle_y = rotation_handle_point(rectangles[index])
            if (canvas_x - handle_x) ** 2 + (canvas_y - handle_y) ** 2 <= 12 ** 2:
                return index
        return None

    # 查找鼠标是否命中矩形四角的缩放控制点。
    def find_resize_handle(canvas_x, canvas_y):
        path = current_image_path()
        if path is None:
            return None

        rectangles = image_rectangles.get(path, [])
        handle_names = ("nw", "ne", "se", "sw")
        for index in range(len(rectangles) - 1, -1, -1):
            for handle_name, (handle_x, handle_y) in zip(handle_names, rotated_rectangle_corner_points(rectangles[index])):
                if abs(canvas_x - handle_x) <= 8 and abs(canvas_y - handle_y) <= 8:
                    return index, handle_name
        return None

    # 绘制所有矩形框、当前选中框的缩放控制点、旋转手柄和标记文字。
    def draw_edit_rectangles():
        edit_canvas.delete("rectangle")
        path = current_image_path()
        if path is None:
            return

        for index, rectangle in enumerate(image_rectangles.get(path, [])):
            color = "#d7263d" if index == edit_state["active_index"] else "#2f80ed"
            points = rotated_rectangle_points(rectangle)
            edit_canvas.create_polygon(
                points,
                outline=color,
                fill="",
                width=2,
                tags=("rectangle",),
            )
            if view_mode.get() == EDIT_MODE and index == edit_state["active_index"]:
                for handle_x, handle_y in rotated_rectangle_corner_points(rectangle):
                    edit_canvas.create_rectangle(
                        handle_x - 5,
                        handle_y - 5,
                        handle_x + 5,
                        handle_y + 5,
                        outline=color,
                        fill="#ffffff",
                        width=2,
                        tags=("rectangle",),
                    )
                handle_x, handle_y = rotation_handle_point(rectangle)
                edit_canvas.create_oval(
                    handle_x - 6,
                    handle_y - 6,
                    handle_x + 6,
                    handle_y + 6,
                    outline=color,
                    fill="#ffffff",
                    width=2,
                    tags=("rectangle",),
                )
            if rectangle["tag"]:
                label_x = points[0]
                label_y = max(points[1] - 12, 8)
                text_id = edit_canvas.create_text(
                    label_x,
                    label_y,
                    text=rectangle["tag"],
                    fill="#ffffff",
                    anchor=tk.SW,
                    font=("Microsoft YaHei UI", 10, "bold"),
                    tags=("rectangle",),
                )
                bbox = edit_canvas.bbox(text_id)
                if bbox is not None:
                    left, top, right, bottom = bbox
                    edit_canvas.create_rectangle(
                        left - 6,
                        top - 3,
                        right + 6,
                        bottom + 3,
                        fill=color,
                        outline="#ffffff",
                        width=1,
                        tags=("rectangle",),
                    )
                    edit_canvas.tag_raise(text_id)

    # 按当前缩放比例和偏移量绘制原图；编辑模式下同时叠加矩形框。
    def render_canvas_image():
        if edit_state["suspend_render"]:
            return False

        image = edit_state["image"]
        if image is None:
            return False

        display_size = (
            max(int(image.width * edit_state["scale"]), 1),
            max(int(image.height * edit_state["scale"]), 1),
        )
        display_image = image.resize(display_size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(display_image)
        edit_state["photo"] = photo

        edit_canvas.delete("all")
        edit_canvas.create_image(
            edit_state["offset_x"],
            edit_state["offset_y"],
            image=photo,
            anchor=tk.NW,
            tags=("image",),
        )
        if view_mode.get() in (SINGLE_MODE, EDIT_MODE):
            draw_edit_rectangles()
        return True

    # 将原图完整适配进当前画布，避免超出画布边界。
    def fit_canvas_image():
        image = edit_state["image"]
        if image is None:
            return False

        canvas_width, canvas_height = get_canvas_display_size()
        scale = min(canvas_width / image.width, canvas_height / image.height, 1)
        edit_state["scale"] = scale
        edit_state["offset_x"] = max((canvas_width - image.width * scale) / 2, 0)
        edit_state["offset_y"] = max((canvas_height - image.height * scale) / 2, 0)
        return render_canvas_image()

    # 获取画布可用显示区域，扣除边框和必要的单图文件名区域。
    def get_canvas_display_size():
        root.update_idletasks()
        canvas_width = max(edit_canvas.winfo_width() - 4, 1)
        canvas_height = max(edit_canvas.winfo_height() - 4, 1)
        if canvas_width <= 1 or canvas_height <= 1:
            reserved_height = single_name_label.winfo_reqheight() + 18 if view_mode.get() == SINGLE_MODE else 0
            canvas_width = max(single_frame.winfo_width() - 24, 1)
            canvas_height = max(single_frame.winfo_height() - reserved_height - 24, 1)
        return canvas_width, canvas_height

    # 单图切换时先显示适配后的缩略图，随后再加载原图替换。
    def render_canvas_preview(file_path):
        canvas_width, canvas_height = get_canvas_display_size()
        try:
            image = load_thumbnail(file_path, (canvas_width, canvas_height), Image.Resampling.NEAREST)
        except (OSError, ValueError):
            return False

        scale = min(canvas_width / image.width, canvas_height / image.height, 1)
        display_size = (
            max(int(image.width * scale), 1),
            max(int(image.height * scale), 1),
        )
        display_image = image.resize(display_size, Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(display_image)
        edit_state["preview_photo"] = photo

        offset_x = max((canvas_width - display_size[0]) / 2, 0)
        offset_y = max((canvas_height - display_size[1]) / 2, 0)
        edit_canvas.delete("all")
        edit_canvas.create_image(offset_x, offset_y, image=photo, anchor=tk.NW, tags=("preview",))
        return True

    # 延迟加载原图；generation 用来避免快速切图时旧任务覆盖新图片。
    def load_full_single_image(file_path, generation):
        if generation != single_load_generation["value"]:
            return
        if view_mode.get() != SINGLE_MODE or current_image_path() != file_path:
            return
        load_canvas_image(file_path, fit=True)

    # 加载原图到画布状态，可选择立即显示或仅缓存等待后续适配。
    def load_canvas_image(file_path, fit=True, display=True):
        path = current_image_path()
        if path is None and file_path is None:
            return False

        try:
            image = Image.open(file_path)
            image = ImageOps.exif_transpose(image).convert("RGB")
        except (OSError, ValueError):
            messagebox.showerror("打开失败", "请选择 JPG、PNG 或 BMP 格式的图片。")
            return False

        edit_state["image"] = image
        edit_state["path"] = file_path
        if not display:
            return True
        if fit:
            edit_state["suspend_render"] = True
            try:
                fit_canvas_image()
            finally:
                edit_state["suspend_render"] = False
            return render_canvas_image()
        return render_canvas_image()

    # 根据窗口宽度排布编辑模式工具条，避免按钮在窄窗口中被裁切。
    def layout_edit_controls():
        for column_index in range(8):
            edit_controls.grid_columnconfigure(column_index, weight=0, minsize=0)

        for widget in (
            edit_label,
            edit_mode_notice,
            tag_entry,
            box_tag_label,
            box_tag_entry,
            save_tag_button,
            draw_box_button,
            edit_previous_button,
            edit_info_label,
            edit_page_label,
            edit_next_button,
            undo_button,
            exit_edit_button,
        ):
            widget.grid_forget()

        tag_entry.configure(width=22)
        box_tag_entry.configure(width=22)
        edit_controls.grid_columnconfigure(3, minsize=36)
        edit_controls.grid_columnconfigure(6, weight=1)
        edit_controls.grid_columnconfigure(7, minsize=96)
        edit_mode_notice.grid(row=0, column=0, columnspan=8, padx=10, pady=(8, 6), sticky=tk.EW)

        edit_label.grid(row=1, column=0, padx=(10, 6), pady=5, sticky=tk.W)
        tag_entry.grid(row=1, column=1, padx=(0, 6), pady=5, sticky=tk.EW)
        save_tag_button.grid(row=1, column=2, padx=(0, 6), pady=5, sticky=tk.W)
        edit_info_label.grid(row=1, column=3, columnspan=3, padx=(10, 6), pady=5, sticky=tk.EW)
        undo_button.grid(row=1, column=7, padx=(10, 10), pady=5, sticky=tk.EW)

        box_tag_label.grid(row=2, column=0, padx=(10, 6), pady=5, sticky=tk.W)
        box_tag_entry.grid(row=2, column=1, padx=(0, 6), pady=5, sticky=tk.EW)
        draw_box_button.grid(row=2, column=2, padx=(0, 6), pady=5, sticky=tk.W)
        edit_previous_button.grid(row=2, column=3, padx=(10, 6), pady=5, sticky=tk.W)
        edit_page_label.grid(row=2, column=4, padx=(0, 6), pady=5, sticky=tk.W)
        edit_next_button.grid(row=2, column=5, padx=(0, 6), pady=5, sticky=tk.W)
        exit_edit_button.grid(row=2, column=7, padx=(10, 10), pady=5, sticky=tk.EW)

        edit_controls.pack(fill=tk.X, pady=(0, 12))

    # 进入编辑模式或切换选中矩形后，同步输入框和按钮状态。
    def update_edit_controls():
        path = current_image_path()
        tag_entry.delete(0, tk.END)
        if path is not None:
            tag_entry.insert(0, format_tags(image_tags.get(path, [])))
            edit_info_label.configure(text=image_info_text(path))
        else:
            edit_info_label.configure(text="")

        box_tag_entry.delete(0, tk.END)
        index = current_image_index.get()
        edit_page_label.configure(text=f"{index + 1} / {len(image_paths)}" if image_paths and index >= 0 else "0 / 0")
        edit_previous_button.configure(state=tk.NORMAL if index > 0 else tk.DISABLED)
        edit_next_button.configure(state=tk.NORMAL if 0 <= index < len(image_paths) - 1 else tk.DISABLED)

        layout_edit_controls()
        update_active_rectangle_controls()

    # 切换到单图浏览：先稳定布局并保持空白，再显示缩略图，最后替换原图。
    def show_single_mode():
        view_mode.set(SINGLE_MODE)
        edit_state["draw_enabled"] = False
        edit_state["rectangle_started"] = False
        edit_state["resizing"] = False
        edit_state["moving_rectangle"] = False
        edit_state["resize_anchor"] = None
        single_load_generation["value"] += 1
        generation = single_load_generation["value"]
        edit_state["image"] = None
        edit_state["photo"] = None
        edit_state["path"] = None
        edit_canvas.delete("all")
        edit_controls.pack_forget()
        image_label.pack_forget()
        object_panel.pack_forget()
        edit_canvas.pack_forget()
        edit_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        single_name_label.pack(fill=tk.X, padx=10, pady=(0, 8))
        multi_frame.pack_forget()
        single_frame.pack(fill=tk.BOTH, expand=True)
        mode_button.configure(text="多图浏览", state=tk.NORMAL)
        update_multi_select_controls()
        update_single_name_label()
        update_controls()
        root.update_idletasks()
        edit_canvas.delete("all")
        path = current_image_path()

        def show_adapted_preview_then_full(selected_path=path, load_generation=generation):
            if load_generation != single_load_generation["value"]:
                return
            if view_mode.get() != SINGLE_MODE or current_image_path() != selected_path:
                return
            edit_canvas.delete("all")
            if render_canvas_preview(selected_path):
                root.after(
                    30,
                    lambda full_path=selected_path, full_generation=load_generation: load_full_single_image(
                        full_path,
                        full_generation,
                    ),
                )

        if path is not None:
            root.after_idle(show_adapted_preview_then_full)
        root.focus_set()

    # 切换到多图浏览：先准备网格再显示，避免露出空白多图画布。
    def show_multi_mode(initial_position=None, initial_index=None, refresh=True):
        view_mode.set(MULTI_MODE)
        can_return_to_multi.set(False)
        mode_button.configure(text="单图浏览", state=tk.NORMAL)
        update_multi_select_controls()
        should_refresh_grid = refresh or not thumbnail_buttons or multi_grid_dirty.get()
        if should_refresh_grid:
            render_multi_grid()
            root.update_idletasks()
            update_multi_scroll_region()
            if initial_index is not None and initial_index in thumbnail_buttons:
                target_y = thumbnail_buttons[initial_index].winfo_y()
                scroll_region = multi_canvas.bbox("all")
                if scroll_region:
                    content_height = max(scroll_region[3] - scroll_region[1], 1)
                    canvas_height = max(multi_canvas.winfo_height(), 1)
                    max_scroll = max(content_height - canvas_height, 1)
                    multi_canvas.yview_moveto(min(max(target_y / max_scroll, 0), 1))
            elif initial_position is not None:
                multi_canvas.yview_moveto(initial_position)
        controls.pack_forget()
        edit_controls.pack_forget()
        edit_canvas.pack_forget()
        object_panel.pack_forget()
        image_label.pack_forget()
        single_name_label.pack_forget()
        single_frame.pack_forget()
        multi_frame.pack(fill=tk.BOTH, expand=True)
        root.focus_set()

    # 编辑模式工作区布局：宽窗口右侧显示对象列表，窄窗口放到底部避免画布被挤压。
    def layout_edit_workspace():
        if view_mode.get() != EDIT_MODE:
            return

        edit_canvas.pack_forget()
        object_panel.pack_forget()
        object_panel.configure(width=220, height=1)
        object_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=10)
        edit_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        root.after_idle(render_canvas_image)

    # 切换到编辑模式，保留当前图片缩放/偏移状态并隐藏文件名。
    def show_edit_mode():
        if current_image_path() is None:
            return
        view_mode.set(EDIT_MODE)
        edit_state["draw_enabled"] = False
        edit_state["rectangle_started"] = False
        edit_state["resizing"] = False
        edit_state["moving_rectangle"] = False
        edit_state["resize_anchor"] = None
        controls.pack_forget()
        multi_frame.pack_forget()
        single_frame.pack(fill=tk.BOTH, expand=True)
        image_label.pack_forget()
        single_name_label.pack_forget()
        edit_canvas.pack_forget()
        layout_edit_workspace()
        mode_button.configure(text="多图浏览", state=tk.DISABLED)
        update_multi_select_controls()
        update_edit_controls()
        update_rectangle_object_list()
        update_undo_button()
        root.after(50, render_canvas_image)

    # 获取多图模式当前视口左上角第一张图片，用于切换单图时定位。
    def get_first_visible_multi_index():
        root.update_idletasks()
        update_multi_scroll_region()

        top = multi_canvas.canvasy(0)
        bottom = multi_canvas.canvasy(max(multi_canvas.winfo_height(), 1))
        visible_items = []

        for index, button in thumbnail_buttons.items():
            button_top = button.winfo_y()
            button_bottom = button_top + button.winfo_height()
            if button_bottom >= top and button_top <= bottom:
                visible_items.append((button_top, button.winfo_x(), index))

        if not visible_items:
            return current_image_index.get()

        visible_items.sort()
        return visible_items[0][2]

    # 从单图返回多图时恢复进入单图前的滚动位置。
    def return_to_multi_mode():
        show_multi_mode(
            initial_position=last_multi_position.get(),
            initial_index=last_multi_top_index.get(),
            refresh=False,
        )

    # 底部单图/多图按钮入口，按当前模式执行切换或返回。
    def toggle_view_mode():
        if view_mode.get() == EDIT_MODE:
            exit_edit_mode()
        elif view_mode.get() == SINGLE_MODE:
            if can_return_to_multi.get():
                return_to_multi_mode()
            else:
                show_multi_mode()
        else:
            last_multi_position.set(multi_canvas.yview()[0])
            can_return_to_multi.set(True)
            visible_index = get_first_visible_multi_index()
            if 0 <= visible_index < len(image_paths):
                last_multi_top_index.set(visible_index)
            if 0 <= visible_index < len(image_paths):
                current_image_index.set(visible_index)
            show_single_mode()

    mode_button.configure(command=toggle_view_mode)

    # 弹出筛选窗口，收集标记文本和是否精确筛选。
    def ask_filter_options():
        dialog = tk.Toplevel(root)
        dialog.title("筛选")
        dialog.configure(bg="#ffffff")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()

        result = {
            "confirmed": False,
            "tag_text": "",
            "exact": False,
            "image_only": False,
            "rectangles_only": False,
        }
        tag_value = tk.StringVar()
        exact_value = tk.BooleanVar(value=False)
        image_only_value = tk.BooleanVar(value=False)
        rectangles_only_value = tk.BooleanVar(value=False)

        tk.Label(
            dialog,
            text="输入要筛选的标记：",
            bg="#ffffff",
            fg="#333333",
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 8), sticky=tk.W)

        entry = tk.Entry(dialog, width=36, textvariable=tag_value)
        style_entry(entry)
        entry.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 8), sticky=tk.EW)

        exact_check = tk.Checkbutton(
            dialog,
            text="精确筛选",
            variable=exact_value,
            bg="#ffffff",
            activebackground="#ffffff",
            fg="#333333",
            activeforeground="#333333",
            selectcolor="#ffffff",
            highlightthickness=0,
        )
        exact_check.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 12), sticky=tk.W)

        def select_image_only():
            if image_only_value.get():
                rectangles_only_value.set(False)

        def select_rectangles_only():
            if rectangles_only_value.get():
                image_only_value.set(False)

        image_only_check = tk.Checkbutton(
            dialog,
            text="只筛选图片标记",
            variable=image_only_value,
            command=select_image_only,
            bg="#ffffff",
            activebackground="#ffffff",
            fg="#333333",
            activeforeground="#333333",
            selectcolor="#ffffff",
            highlightthickness=0,
        )
        image_only_check.grid(row=3, column=0, columnspan=2, padx=16, pady=(0, 12), sticky=tk.W)

        rectangles_only_check = tk.Checkbutton(
            dialog,
            text="只筛选矩形框标记",
            variable=rectangles_only_value,
            command=select_rectangles_only,
            bg="#ffffff",
            activebackground="#ffffff",
            fg="#333333",
            activeforeground="#333333",
            selectcolor="#ffffff",
            highlightthickness=0,
        )
        rectangles_only_check.grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 12), sticky=tk.W)

        buttons = tk.Frame(dialog, bg="#ffffff")
        buttons.grid(row=5, column=0, columnspan=2, padx=16, pady=(0, 16), sticky=tk.E)

        def confirm():
            result["confirmed"] = True
            result["tag_text"] = tag_value.get()
            result["exact"] = exact_value.get()
            result["image_only"] = image_only_value.get()
            result["rectangles_only"] = rectangles_only_value.get()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        confirm_button = tk.Button(buttons, text="确定", command=confirm)
        cancel_button = tk.Button(buttons, text="取消", command=cancel)
        style_button(confirm_button, "primary")
        style_button(cancel_button)
        confirm_button.pack(side=tk.LEFT, padx=(0, 8))
        cancel_button.pack(side=tk.LEFT)

        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: cancel())
        entry.focus_set()

        root.update_idletasks()
        x = root.winfo_rootx() + max((root.winfo_width() - dialog.winfo_reqwidth()) // 2, 0)
        y = root.winfo_rooty() + max((root.winfo_height() - dialog.winfo_reqheight()) // 2, 0)
        dialog.geometry(f"+{x}+{y}")
        root.wait_window(dialog)
        return result if result["confirmed"] else None

    # 根据标记筛选图片；再次点击时取消筛选并恢复全部图片。
    def apply_tag_filter():
        if filter_active.get():
            filter_active.set(False)
            filter_button.configure(text="筛选")
            image_paths.clear()
            image_paths.extend(all_image_paths)
            current_image_index.set(0 if image_paths else -1)
            can_return_to_multi.set(False)
            show_multi_mode()
            root.after(50, lambda: multi_canvas.yview_moveto(0.0))
            return

        filter_options = ask_filter_options()
        if filter_options is None:
            return

        target_tags = parse_tags(filter_options["tag_text"])
        exact_filter = filter_options["exact"]
        image_only_filter = filter_options["image_only"]
        rectangles_only_filter = filter_options["rectangles_only"]
        if not target_tags:
            image_paths.clear()
            image_paths.extend(all_image_paths)
        else:
            def get_filter_tags(path):
                if image_only_filter or not rectangles_only_filter:
                    return image_tags.get(path, [])
                return [
                    rectangle.get("tag", "")
                    for rectangle in image_rectangles.get(path, [])
                    if rectangle.get("tag", "").strip()
                ]

            image_paths.clear()
            image_paths.extend(
                path
                for path in all_image_paths
                if (
                    tags_exact_match(get_filter_tags(path), target_tags)
                    if exact_filter
                    else tags_match(get_filter_tags(path), target_tags)
                )
            )

        current_image_index.set(0 if image_paths else -1)
        can_return_to_multi.set(False)

        if not image_paths:
            messagebox.showinfo("筛选结果", "没有找到该标记的图片。")
            image_paths.extend(all_image_paths)
            current_image_index.set(0 if image_paths else -1)
            filter_active.set(False)
            filter_button.configure(text="筛选")
        else:
            filter_active.set(bool(target_tags))
            filter_button.configure(text="取消筛选" if filter_active.get() else "筛选")

        show_multi_mode()
        root.after(50, lambda: multi_canvas.yview_moveto(0.0))

    # 生成不覆盖已有文件的导出路径，遇到同名文件自动添加后缀。
    def unique_export_path(target_folder, source_path):
        output_path = target_folder / source_path.name
        if not output_path.exists():
            return output_path

        stem = source_path.stem
        suffix = source_path.suffix
        counter = 1
        while True:
            output_path = target_folder / f"{stem}_{counter}{suffix}"
            if not output_path.exists():
                return output_path
            counter += 1

    # 导出前处理同名文件：询问覆盖，不覆盖则使用自动后缀。
    def resolve_export_path(target_folder, source_path):
        output_path = target_folder / source_path.name
        if not output_path.exists():
            return output_path

        overwrite = messagebox.askyesno(
            "文件已存在",
            f"目标文件已存在，是否覆盖？\n{output_path}\n\n选择“否”将自动添加后缀保存。",
        )
        if overwrite:
            return output_path
        return unique_export_path(target_folder, source_path)

    # 将指定图片列表导出到用户选择的目标文件夹。
    def export_images(paths, empty_message, include_annotation_config=False):
        if not paths:
            messagebox.showinfo("导出图片", empty_message)
            return

        folder_path = filedialog.askdirectory(title="选择导出目标文件夹")
        if not folder_path:
            return

        target_folder = Path(folder_path)
        exported_count = 0
        failed_count = 0
        exported_pairs = []

        for source_path in paths:
            try:
                output_path = resolve_export_path(target_folder, source_path)
                shutil.copy2(source_path, output_path)
                exported_pairs.append((source_path, output_path))
                exported_count += 1
            except OSError:
                failed_count += 1

        config_failed = False
        if include_annotation_config and exported_pairs:
            exported_paths = [output_path for _source_path, output_path in exported_pairs]
            exported_tags = {
                output_path: list(image_tags.get(source_path, []))
                for source_path, output_path in exported_pairs
            }
            exported_rectangles = {
                output_path: [dict(rectangle) for rectangle in image_rectangles.get(source_path, [])]
                for source_path, output_path in exported_pairs
            }
            try:
                save_annotation_config(
                    target_folder / CONFIG_FILE_NAME,
                    exported_paths,
                    exported_tags,
                    exported_rectangles,
                )
            except OSError:
                config_failed = True

        if failed_count:
            messagebox.showwarning(
                "导出完成",
                f"已导出 {exported_count} 张图片，{failed_count} 张导出失败。",
            )
        elif config_failed:
            messagebox.showwarning("导出完成", f"已导出 {exported_count} 张图片，但配置文件更新失败。")
        else:
            messagebox.showinfo("导出完成", f"已导出 {exported_count} 张图片。")

    def export_all_images():
        export_images(image_paths, "当前没有可导出的图片。", include_annotation_config=True)

    def export_selected_images():
        selected_paths = [path for path in image_paths if path in selected_image_paths]
        export_images(selected_paths, "当前没有选中的图片。", include_annotation_config=True)

    def image_size_for_export(path):
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                return image.size
        except (OSError, ValueError):
            return 0, 0

    def export_coco_config():
        if not image_paths:
            messagebox.showinfo("导出 COCO", "当前没有可导出的图片。")
            return

        output_file = filedialog.asksaveasfilename(
            title="导出 COCO 配置",
            defaultextension=".json",
            filetypes=(("COCO JSON", "*.json"), ("所有文件", "*.*")),
        )
        if not output_file:
            return

        category_names = sorted(
            {
                rectangle.get("tag", "").strip() or "untagged"
                for path in image_paths
                for rectangle in image_rectangles.get(path, [])
            },
            key=str.casefold,
        )
        category_id_by_name = {name: index + 1 for index, name in enumerate(category_names)}
        coco = {
            "images": [],
            "annotations": [],
            "categories": [{"id": category_id, "name": name} for name, category_id in category_id_by_name.items()],
        }

        annotation_id = 1
        for image_id, path in enumerate(image_paths, start=1):
            width, height = image_size_for_export(path)
            coco["images"].append(
                {
                    "id": image_id,
                    "file_name": Path(path).name,
                    "width": width,
                    "height": height,
                    "tags": list(image_tags.get(path, [])),
                }
            )
            for rectangle in image_rectangles.get(path, []):
                tag = rectangle.get("tag", "").strip() or "untagged"
                bbox = axis_bbox_from_rectangle(rectangle)
                points = rotated_rectangle_image_points(rectangle)
                coco["annotations"].append(
                    {
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": category_id_by_name[tag],
                        "bbox": [round(value, 3) for value in bbox],
                        "area": round(float(rectangle.get("width", 1)) * float(rectangle.get("height", 1)), 3),
                        "segmentation": [[round(coord, 3) for point in points for coord in point]],
                        "iscrowd": 0,
                        "attributes": {"angle": float(rectangle.get("angle", 0))},
                    }
                )
                annotation_id += 1

        try:
            Path(output_file).write_text(json.dumps(coco, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("导出 COCO", f"无法写入 COCO 配置文件：\n{error}")
            return

        messagebox.showinfo("导出 COCO", f"已导出 {len(coco['images'])} 张图片、{len(coco['annotations'])} 个矩形框。")

    def import_coco_config():
        if not all_image_paths:
            messagebox.showinfo("导入 COCO", "请先打开图片或文件夹，再导入 COCO 配置。")
            return

        config_file = filedialog.askopenfilename(
            title="导入 COCO 配置",
            filetypes=(("COCO JSON", "*.json"), ("所有文件", "*.*")),
        )
        if not config_file:
            return

        try:
            coco = json.loads(Path(config_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            messagebox.showerror("导入 COCO", f"无法读取 COCO 配置：\n{error}")
            return

        name_lookup = {Path(path).name.casefold(): Path(path) for path in all_image_paths}
        image_id_to_path = {}
        imported_tags = {}
        imported_rectangles = {}
        for item in coco.get("images", []):
            if not isinstance(item, dict):
                continue
            path = name_lookup.get(str(item.get("file_name", "")).casefold())
            if path is None:
                continue
            image_id_to_path[item.get("id")] = path
            tags = [str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()]
            if tags:
                imported_tags[path] = tags

        category_names = {
            category.get("id"): str(category.get("name", "untagged")).strip() or "untagged"
            for category in coco.get("categories", [])
            if isinstance(category, dict)
        }
        for annotation in coco.get("annotations", []):
            if not isinstance(annotation, dict):
                continue
            path = image_id_to_path.get(annotation.get("image_id"))
            bbox = annotation.get("bbox", [])
            if path is None or len(bbox) < 4:
                continue
            try:
                left, top, width, height = [float(value) for value in bbox[:4]]
            except (TypeError, ValueError):
                continue
            angle = 0.0
            attributes = annotation.get("attributes", {})
            if isinstance(attributes, dict):
                try:
                    angle = float(attributes.get("angle", 0))
                except (TypeError, ValueError):
                    angle = 0.0
            imported_rectangles.setdefault(path, []).append(
                {
                    "center_x": left + width / 2,
                    "center_y": top + height / 2,
                    "width": max(width, 1),
                    "height": max(height, 1),
                    "angle": angle,
                    "tag": category_names.get(annotation.get("category_id"), "untagged"),
                }
            )

        matched_count, added_tag_count, added_rectangle_count = merge_imported_annotations(imported_tags, imported_rectangles)
        messagebox.showinfo(
            "导入 COCO",
            f"已匹配 {matched_count} 张图片，追加 {added_tag_count} 个图片标记、{added_rectangle_count} 个矩形框。",
        )

    def yolo_class_names(paths):
        return sorted(
            {
                rectangle.get("tag", "").strip() or "untagged"
                for path in paths
                for rectangle in image_rectangles.get(path, [])
            },
            key=str.casefold,
        )

    def export_yolo_config():
        if not image_paths:
            messagebox.showinfo("导出 YOLO", "当前没有可导出的图片。")
            return

        folder_path = filedialog.askdirectory(title="选择 YOLO 导出目标文件夹")
        if not folder_path:
            return

        target_folder = Path(folder_path)
        labels_folder = target_folder / "labels"
        labels_folder.mkdir(parents=True, exist_ok=True)
        class_names = yolo_class_names(image_paths)
        class_id_by_name = {name: index for index, name in enumerate(class_names)}
        try:
            (target_folder / "classes.txt").write_text("\n".join(class_names), encoding="utf-8")
            exported_count = 0
            for path in image_paths:
                width, height = image_size_for_export(path)
                if width <= 0 or height <= 0:
                    continue
                lines = []
                for rectangle in image_rectangles.get(path, []):
                    tag = rectangle.get("tag", "").strip() or "untagged"
                    left, top, box_width, box_height = axis_bbox_from_rectangle(rectangle)
                    center_x = min(max((left + box_width / 2) / width, 0), 1)
                    center_y = min(max((top + box_height / 2) / height, 0), 1)
                    normalized_width = min(max(box_width / width, 0), 1)
                    normalized_height = min(max(box_height / height, 0), 1)
                    lines.append(
                        f"{class_id_by_name[tag]} {center_x:.6f} {center_y:.6f} {normalized_width:.6f} {normalized_height:.6f}"
                    )
                (labels_folder / f"{Path(path).stem}.txt").write_text("\n".join(lines), encoding="utf-8")
                exported_count += 1
        except OSError as error:
            messagebox.showerror("导出 YOLO", f"无法写入 YOLO 配置：\n{error}")
            return

        messagebox.showinfo("导出 YOLO", f"已导出 {exported_count} 个 YOLO 标注文件。")

    def import_yolo_config():
        if not all_image_paths:
            messagebox.showinfo("导入 YOLO", "请先打开图片或文件夹，再导入 YOLO 配置。")
            return

        folder_path = filedialog.askdirectory(title="选择 YOLO 配置文件夹")
        if not folder_path:
            return

        source_folder = Path(folder_path)
        labels_folder = source_folder / "labels"
        if not labels_folder.exists():
            labels_folder = source_folder
        classes_file = source_folder / "classes.txt"
        if not classes_file.exists() and labels_folder != source_folder:
            classes_file = labels_folder / "classes.txt"
        class_names = []
        if classes_file.exists():
            class_names = [line.strip() for line in classes_file.read_text(encoding="utf-8").splitlines() if line.strip()]

        stem_lookup = {Path(path).stem.casefold(): Path(path) for path in all_image_paths}
        imported_rectangles = {}
        for label_file in labels_folder.glob("*.txt"):
            if label_file.name.casefold() == "classes.txt":
                continue
            path = stem_lookup.get(label_file.stem.casefold())
            if path is None:
                continue
            image_width, image_height = image_size_for_export(path)
            if image_width <= 0 or image_height <= 0:
                continue
            for line in label_file.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    class_id = int(float(parts[0]))
                    center_x, center_y, width, height = [float(value) for value in parts[1:5]]
                except (TypeError, ValueError):
                    continue
                tag = class_names[class_id] if 0 <= class_id < len(class_names) else f"class_{class_id}"
                imported_rectangles.setdefault(path, []).append(
                    {
                        "center_x": center_x * image_width,
                        "center_y": center_y * image_height,
                        "width": max(width * image_width, 1),
                        "height": max(height * image_height, 1),
                        "angle": 0.0,
                        "tag": tag,
                    }
                )

        matched_count, added_tag_count, added_rectangle_count = merge_imported_annotations({}, imported_rectangles)
        messagebox.showinfo(
            "导入 YOLO",
            f"已匹配 {matched_count} 张图片，追加 {added_tag_count} 个图片标记、{added_rectangle_count} 个矩形框。",
        )

    def safe_export_name(value):
        safe_value = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value.strip())
        return safe_value or "untagged"

    def resolve_export_file_path(target_folder, file_name):
        output_path = target_folder / file_name
        if not output_path.exists():
            return output_path

        overwrite = messagebox.askyesno(
            "文件已存在",
            f"目标文件已存在，是否要覆盖？\n{output_path}\n\n选择“否”将自动添加后缀保存。",
        )
        if overwrite:
            return output_path
        return unique_export_path(target_folder, output_path)

    def crop_rectangle_to_file(image_path, rectangle, output_path):
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
            return False

        aligned.crop((left, top, right, bottom)).save(output_path)
        return True

    def export_rectangles_by_tag():
        tag_text = ask_selected_tags("导出矩形框", "输入要导出的矩形框标记：")
        if tag_text is None:
            return

        target_tags = parse_tags(tag_text)
        if not target_tags:
            messagebox.showinfo("导出矩形框", "请输入要导出的矩形框标记。")
            return

        target_keys = {tag.casefold() for tag in target_tags}
        matches = []
        for image_path in image_paths:
            for rectangle_index, rectangle in enumerate(image_rectangles.get(image_path, []), start=1):
                rectangle_tag = rectangle.get("tag", "").strip()
                if rectangle_tag.casefold() in target_keys:
                    matches.append((image_path, rectangle_index, rectangle, rectangle_tag))

        if not matches:
            messagebox.showinfo("导出矩形框", "没有找到指定标记的矩形框。")
            return

        folder_path = filedialog.askdirectory(title="选择导出目标文件夹")
        if not folder_path:
            return

        target_folder = Path(folder_path)
        exported_paths = []
        exported_tags = {}
        exported_count = 0
        failed_count = 0
        for image_path, rectangle_index, rectangle, rectangle_tag in matches:
            safe_tag = safe_export_name(rectangle_tag)
            file_name = f"{Path(image_path).stem}_{safe_tag}_{rectangle_index}.png"
            try:
                output_path = resolve_export_file_path(target_folder, file_name)
                if crop_rectangle_to_file(image_path, rectangle, output_path):
                    exported_paths.append(output_path)
                    exported_tags[output_path] = [rectangle_tag]
                    exported_count += 1
                else:
                    failed_count += 1
            except OSError:
                failed_count += 1

        if exported_paths:
            try:
                save_annotation_config(target_folder / CONFIG_FILE_NAME, exported_paths, exported_tags, {})
            except OSError as error:
                messagebox.showwarning("导出矩形框", f"裁剪图片已导出，但标注配置保存失败：\n{error}")

        if failed_count:
            messagebox.showwarning(
                "导出矩形框",
                f"已导出 {exported_count} 张裁剪图片，{failed_count} 个矩形框导出失败。",
            )
        else:
            messagebox.showinfo("导出矩形框", f"已导出 {exported_count} 张裁剪图片。")

    filter_button.configure(command=apply_tag_filter)

    def show_image(file_path):
        return load_canvas_image(file_path, fit=True)

    # 根据编辑撤销栈状态启用或禁用编辑模式撤销按钮。
    def update_undo_button():
        undo_button.configure(state=tk.NORMAL if edit_undo_stack else tk.DISABLED)

    # 保存整图标记；必要时记录撤销信息。
    def save_current_tag(record_undo=True):
        path = current_image_path()
        if path is None:
            return

        previous_tags = list(image_tags.get(path, []))
        tags = parse_tags(tag_entry.get())
        tags_changed = previous_tags != tags
        if record_undo and tags_changed:
            edit_undo_stack.append(
                {
                    "type": "image_tags",
                    "path": path,
                    "previous_tags": previous_tags,
                }
            )

        if tags:
            image_tags[path] = tags
        else:
            image_tags.pop(path, None)
        if tags_changed:
            multi_grid_dirty.set(True)

        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, [])
        if active_index is not None and 0 <= active_index < len(rectangles):
            rectangles[active_index]["tag"] = box_tag_entry.get().strip()
            draw_edit_rectangles()

        if tags_changed or (active_index is not None and 0 <= active_index < len(rectangles)):
            persist_annotation_config()
        if view_mode.get() == EDIT_MODE:
            edit_info_label.configure(text=image_info_text(path))
        update_undo_button()

    # 撤销编辑模式中最近一次整图标记或矩形框创建操作。
    def undo_last_edit():
        if not edit_undo_stack:
            return

        operation = edit_undo_stack.pop()
        operation_type = operation["type"]
        path = operation["path"]

        if operation_type == "image_tags":
            previous_tags = operation["previous_tags"]
            if previous_tags:
                image_tags[path] = previous_tags
            else:
                image_tags.pop(path, None)
            if path == current_image_path():
                tag_entry.delete(0, tk.END)
                tag_entry.insert(0, format_tags(previous_tags))

        elif operation_type == "rectangle":
            rectangles = image_rectangles.get(path, [])
            rectangle = operation["rectangle"]
            if rectangle in rectangles:
                rectangles.remove(rectangle)
            if path == current_image_path():
                edit_state["active_index"] = None
                update_active_rectangle_controls()
                draw_edit_rectangles()

        elif operation_type == "delete_rectangle":
            rectangles = image_rectangles.setdefault(path, [])
            rectangle = operation["rectangle"]
            index = min(max(operation["index"], 0), len(rectangles))
            rectangles.insert(index, rectangle)
            if path == current_image_path():
                edit_state["active_index"] = index
                update_active_rectangle_controls()
                draw_edit_rectangles()

        elif operation_type == "rectangle_tag":
            rectangles = image_rectangles.get(path, [])
            index = operation["index"]
            if 0 <= index < len(rectangles):
                rectangles[index]["tag"] = operation["previous_tag"]
            if path == current_image_path():
                edit_state["active_index"] = index if 0 <= index < len(rectangles) else None
                update_active_rectangle_controls()
                draw_edit_rectangles()

        persist_annotation_config()
        update_undo_button()

    # 保存编辑结果，然后回到单图浏览模式；矩形框只作为标注保留，不再自动裁剪生成图片。
    def exit_edit_mode():
        save_current_tag()
        image_paths.clear()
        image_paths.extend(all_image_paths)
        show_single_mode()

    # 刷新右侧矩形对象列表，并同步当前选中的矩形项。
    def update_rectangle_object_list():
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []

        object_list_updating.set(True)
        rectangle_listbox.delete(0, tk.END)
        for index, rectangle in enumerate(rectangles):
            name = rectangle["tag"] or "未命名矩形框"
            rectangle_listbox.insert(tk.END, f"{index + 1}. {name}")

        if active_index is not None and 0 <= active_index < len(rectangles):
            rectangle_listbox.selection_set(active_index)
            rectangle_listbox.activate(active_index)
            rectangle_listbox.see(active_index)
        object_list_updating.set(False)

        has_active = active_index is not None and 0 <= active_index < len(rectangles)
        state = tk.NORMAL if has_active else tk.DISABLED
        rename_rectangle_button.configure(state=state)
        delete_rectangle_button.configure(state=state)

    # 点击对象列表时，选中对应矩形并在画布中高亮。
    def select_rectangle_from_list(_event=None):
        if object_list_updating.get():
            return
        selection = rectangle_listbox.curselection()
        if not selection:
            return
        select_rectangle(selection[0])

    # 删除当前选中的矩形框，并记录撤销信息。
    def delete_active_rectangle():
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if active_index is None or not 0 <= active_index < len(rectangles):
            return

        rectangle = rectangles.pop(active_index)
        multi_grid_dirty.set(True)
        edit_undo_stack.append(
            {
                "type": "delete_rectangle",
                "path": path,
                "rectangle": rectangle,
                "index": active_index,
            }
        )
        edit_state["active_index"] = None
        update_active_rectangle_controls()
        update_rectangle_object_list()
        draw_edit_rectangles()
        persist_annotation_config()
        update_undo_button()

    def apply_rectangle_tag_change(path, index, new_tag):
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not 0 <= index < len(rectangles):
            return

        rectangle = rectangles[index]
        previous_tag = rectangle["tag"]
        rectangle["tag"] = new_tag.strip()
        if previous_tag != rectangle["tag"]:
            edit_undo_stack.append(
                {
                    "type": "rectangle_tag",
                    "path": path,
                    "index": index,
                    "previous_tag": previous_tag,
                }
            )
            multi_grid_dirty.set(True)
        edit_state["active_index"] = index
        update_active_rectangle_controls()
        update_rectangle_object_list()
        draw_edit_rectangles()
        persist_annotation_config()
        update_undo_button()

    def close_rectangle_name_editor(save=False):
        entry = rectangle_name_editor["entry"]
        if entry is None or rectangle_name_editor["committing"]:
            return

        rectangle_name_editor["committing"] = True
        index = rectangle_name_editor["index"]
        value = entry.get()
        entry.destroy()
        rectangle_name_editor["entry"] = None
        rectangle_name_editor["index"] = None
        rectangle_name_editor["committing"] = False

        if save:
            apply_rectangle_tag_change(current_image_path(), index, value)

    # 在对象列表当前行上直接编辑矩形标记。
    def start_inline_rename_rectangle(index=None):
        path = current_image_path()
        active_index = edit_state["active_index"] if index is None else index
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if active_index is None or not 0 <= active_index < len(rectangles):
            return

        edit_state["active_index"] = active_index
        update_active_rectangle_controls()
        close_rectangle_name_editor(save=False)

        bbox = rectangle_listbox.bbox(active_index)
        if bbox is None:
            rectangle_listbox.see(active_index)
            root.update_idletasks()
            bbox = rectangle_listbox.bbox(active_index)
        if bbox is None:
            return

        x, y, width, height = bbox
        entry = tk.Entry(rectangle_listbox)
        style_entry(entry)
        entry.insert(0, rectangles[active_index]["tag"])
        entry.select_range(0, tk.END)
        entry.place(x=x + 2, y=y, width=max(width - 4, 40), height=height)
        rectangle_name_editor["entry"] = entry
        rectangle_name_editor["index"] = active_index
        entry.focus_set()
        entry.bind("<Return>", lambda _event: close_rectangle_name_editor(save=True))
        entry.bind("<Escape>", lambda _event: close_rectangle_name_editor(save=False))
        entry.bind("<FocusOut>", lambda _event: close_rectangle_name_editor(save=True))

    # 按钮入口：对当前选中的矩形框进行行内改名。
    def rename_active_rectangle():
        start_inline_rename_rectangle()

    # 右键菜单入口：清空当前矩形框标记，但保留矩形框对象。
    def clear_active_rectangle_tag():
        path = current_image_path()
        active_index = edit_state["active_index"]
        if active_index is None:
            return
        apply_rectangle_tag_change(path, active_index, "")

    def show_rectangle_object_menu(event):
        index = rectangle_listbox.nearest(event.y)
        path = current_image_path()
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not 0 <= index < len(rectangles):
            return

        select_rectangle(index)
        rectangle_object_menu.tk_popup(event.x_root, event.y_root)
        rectangle_object_menu.grab_release()

    # 选中矩形变化后，把该矩形标记同步到输入框。
    def update_active_rectangle_controls():
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        box_tag_entry.delete(0, tk.END)
        if active_index is None or not 0 <= active_index < len(rectangles):
            update_rectangle_object_list()
            return

        rectangle = rectangles[active_index]
        box_tag_entry.insert(0, rectangle["tag"])
        update_rectangle_object_list()

    # 编辑矩形标记输入框时，实时更新当前选中矩形。
    def update_active_rectangle_tag(_event=None):
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if active_index is None or not 0 <= active_index < len(rectangles):
            return

        rectangles[active_index]["tag"] = box_tag_entry.get().strip()
        multi_grid_dirty.set(True)
        update_rectangle_object_list()
        draw_edit_rectangles()
        persist_annotation_config()

    # 开始绘制一个新的矩形框。
    def start_rectangle(event):
        path = current_image_path()
        if path is None or edit_state["image"] is None:
            return
        if edit_state["rectangle_started"]:
            return

        edit_state["rectangle_started"] = True

        image_x, image_y = canvas_to_image(event.x, event.y)
        image_x = min(max(image_x, 0), edit_state["image"].width)
        image_y = min(max(image_y, 0), edit_state["image"].height)
        rectangle = {
            "center_x": image_x,
            "center_y": image_y,
            "width": 1,
            "height": 1,
            "angle": 0.0,
            "tag": box_tag_entry.get().strip(),
        }
        image_rectangles.setdefault(path, []).append(rectangle)
        edit_state["active_index"] = len(image_rectangles[path]) - 1
        edit_state["drawing"] = True
        edit_state["start_x"] = image_x
        edit_state["start_y"] = image_y
        update_active_rectangle_controls()
        draw_edit_rectangles()

    # 鼠标拖动时更新正在绘制的矩形框尺寸。
    def update_rectangle(event):
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not edit_state["drawing"] or active_index is None or not 0 <= active_index < len(rectangles):
            return

        image_x, image_y = canvas_to_image(event.x, event.y)
        image_x = min(max(image_x, 0), edit_state["image"].width)
        image_y = min(max(image_y, 0), edit_state["image"].height)
        start_x = edit_state["start_x"]
        start_y = edit_state["start_y"]
        rectangle = rectangles[active_index]
        rectangle["center_x"] = (start_x + image_x) / 2
        rectangle["center_y"] = (start_y + image_y) / 2
        rectangle["width"] = abs(image_x - start_x)
        rectangle["height"] = abs(image_y - start_y)
        rectangle["tag"] = box_tag_entry.get().strip()
        draw_edit_rectangles()

    # 完成矩形绘制，尺寸有效时压入撤销栈，尺寸过小时丢弃。
    def finish_rectangle(_event):
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        created_rectangle = rectangles[active_index] if active_index is not None and 0 <= active_index < len(rectangles) else None

        edit_state["drawing"] = False
        save_current_tag(record_undo=False)
        if created_rectangle is not None and created_rectangle["width"] > 1 and created_rectangle["height"] > 1:
            edit_undo_stack.append(
                {
                    "type": "rectangle",
                    "path": path,
                    "rectangle": created_rectangle,
                }
            )
            update_undo_button()
            multi_grid_dirty.set(True)
        elif created_rectangle is not None:
            rectangles.remove(created_rectangle)
            edit_state["active_index"] = None
            update_rectangle_object_list()
            draw_edit_rectangles()
        edit_state["draw_enabled"] = False
        edit_state["rectangle_started"] = False
        draw_box_button.configure(relief=tk.RAISED, text="画矩形框")
        persist_annotation_config()

    # 开始拖动旋转手柄。
    def start_rotation(index):
        edit_state["active_index"] = index
        edit_state["rotating"] = True
        update_active_rectangle_controls()
        draw_edit_rectangles()

    def select_rectangle(index):
        edit_state["active_index"] = index
        update_active_rectangle_controls()
        draw_edit_rectangles()

    # 根据鼠标位置更新当前矩形旋转角度。
    def update_rotation(event):
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if active_index is None or not 0 <= active_index < len(rectangles):
            return

        rectangle = rectangles[active_index]
        center_x, center_y = image_to_canvas(rectangle["center_x"], rectangle["center_y"])
        angle = degrees(atan2(event.y - center_y, event.x - center_x)) + 90
        rectangle["angle"] = ((angle + 180) % 360) - 180
        draw_edit_rectangles()

    def finish_rotation(_event):
        edit_state["rotating"] = False
        multi_grid_dirty.set(True)
        persist_annotation_config()

    # 开始拖动矩形角点调整大小，记录对角锚点和原旋转角。
    def start_resize(index, handle_name):
        path = current_image_path()
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not 0 <= index < len(rectangles):
            return

        rectangle = rectangles[index]
        signs = {
            "nw": (-1, -1),
            "ne": (1, -1),
            "se": (1, 1),
            "sw": (-1, 1),
        }
        sign_x, sign_y = signs[handle_name]
        angle = radians(rectangle["angle"])
        anchor_local_x = -sign_x * rectangle["width"] / 2
        anchor_local_y = -sign_y * rectangle["height"] / 2
        anchor_x = rectangle["center_x"] + anchor_local_x * cos(angle) - anchor_local_y * sin(angle)
        anchor_y = rectangle["center_y"] + anchor_local_x * sin(angle) + anchor_local_y * cos(angle)

        edit_state["active_index"] = index
        edit_state["resizing"] = True
        edit_state["resize_anchor"] = (anchor_x, anchor_y)
        edit_state["resize_angle"] = rectangle["angle"]
        update_active_rectangle_controls()
        draw_edit_rectangles()

    # 拖动角点时按原旋转角重新计算矩形中心和宽高。
    def update_resize(event):
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not edit_state["resizing"] or active_index is None or not 0 <= active_index < len(rectangles):
            return
        if edit_state["image"] is None or edit_state["resize_anchor"] is None:
            return

        image_x, image_y = canvas_to_image(event.x, event.y)
        image_x = min(max(image_x, 0), edit_state["image"].width)
        image_y = min(max(image_y, 0), edit_state["image"].height)
        anchor_x, anchor_y = edit_state["resize_anchor"]
        angle = radians(-edit_state["resize_angle"])
        dx = image_x - anchor_x
        dy = image_y - anchor_y
        local_x = dx * cos(angle) - dy * sin(angle)
        local_y = dx * sin(angle) + dy * cos(angle)

        rectangle = rectangles[active_index]
        angle = radians(edit_state["resize_angle"])
        center_local_x = local_x / 2
        center_local_y = local_y / 2
        rectangle["center_x"] = anchor_x + center_local_x * cos(angle) - center_local_y * sin(angle)
        rectangle["center_y"] = anchor_y + center_local_x * sin(angle) + center_local_y * cos(angle)
        rectangle["width"] = max(abs(local_x), 1)
        rectangle["height"] = max(abs(local_y), 1)
        rectangle["angle"] = edit_state["resize_angle"]
        rectangle["tag"] = box_tag_entry.get().strip()
        draw_edit_rectangles()

    def finish_resize(_event):
        edit_state["resizing"] = False
        edit_state["resize_anchor"] = None
        multi_grid_dirty.set(True)
        persist_annotation_config()

    def start_move_rectangle(index, event):
        path = current_image_path()
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not 0 <= index < len(rectangles):
            return

        rectangle = rectangles[index]
        image_x, image_y = canvas_to_image(event.x, event.y)
        edit_state["active_index"] = index
        edit_state["moving_rectangle"] = True
        edit_state["move_start_x"] = image_x
        edit_state["move_start_y"] = image_y
        edit_state["move_origin_x"] = rectangle["center_x"]
        edit_state["move_origin_y"] = rectangle["center_y"]
        update_active_rectangle_controls()
        draw_edit_rectangles()

    def update_move_rectangle(event):
        path = current_image_path()
        active_index = edit_state["active_index"]
        rectangles = image_rectangles.get(path, []) if path is not None else []
        if not edit_state["moving_rectangle"] or active_index is None or not 0 <= active_index < len(rectangles):
            return
        if edit_state["image"] is None:
            return

        image_x, image_y = canvas_to_image(event.x, event.y)
        delta_x = image_x - edit_state["move_start_x"]
        delta_y = image_y - edit_state["move_start_y"]
        rectangle = rectangles[active_index]
        half_width = rectangle["width"] / 2
        half_height = rectangle["height"] / 2
        rectangle["center_x"] = min(max(edit_state["move_origin_x"] + delta_x, half_width), edit_state["image"].width - half_width)
        rectangle["center_y"] = min(max(edit_state["move_origin_y"] + delta_y, half_height), edit_state["image"].height - half_height)
        draw_edit_rectangles()

    def finish_move_rectangle(_event):
        edit_state["moving_rectangle"] = False
        multi_grid_dirty.set(True)
        persist_annotation_config()

    # 切换画框按钮状态；开启时清空矩形标记输入框。
    def toggle_draw_rectangle():
        enabled = not edit_state["draw_enabled"]
        edit_state["draw_enabled"] = enabled
        edit_state["drawing"] = False
        edit_state["resizing"] = False
        edit_state["moving_rectangle"] = False
        edit_state["resize_anchor"] = None
        edit_state["rectangle_started"] = False
        if enabled:
            box_tag_entry.delete(0, tk.END)
        draw_box_button.configure(
            relief=tk.SUNKEN if enabled else tk.RAISED,
            text="正在画框" if enabled else "画矩形框",
        )

    # 开始拖动画布图片，并记录拖动起点用于双击保护。
    def start_pan(event):
        edit_state["panning"] = True
        edit_state["pan_x"] = event.x
        edit_state["pan_y"] = event.y
        edit_state["pan_start_x"] = event.x
        edit_state["pan_start_y"] = event.y
        edit_state["pan_moved"] = False

    # 根据鼠标位移更新图片偏移量。
    def update_pan(event):
        if not edit_state["panning"]:
            return

        delta_x = event.x - edit_state["pan_x"]
        delta_y = event.y - edit_state["pan_y"]
        total_dx = event.x - edit_state["pan_start_x"]
        total_dy = event.y - edit_state["pan_start_y"]
        if total_dx * total_dx + total_dy * total_dy > 16:
            edit_state["pan_moved"] = True
        edit_state["offset_x"] += delta_x
        edit_state["offset_y"] += delta_y
        edit_state["pan_x"] = event.x
        edit_state["pan_y"] = event.y
        render_canvas_image()

    # 结束拖动；如果确实发生位移，记录时间防止误触发双击编辑。
    def finish_pan(_event):
        if edit_state["pan_moved"]:
            edit_state["last_drag_release"] = time.monotonic()
        edit_state["panning"] = False

    # 以鼠标位置为中心缩放图片。
    def zoom_canvas(event):
        if view_mode.get() not in (SINGLE_MODE, EDIT_MODE) or edit_state["image"] is None:
            return

        old_scale = edit_state["scale"]
        zoom_factor = 1.15 if event.delta > 0 else 1 / 1.15
        new_scale = min(max(old_scale * zoom_factor, 0.05), 8.0)
        if new_scale == old_scale:
            return

        image_x, image_y = canvas_to_image(event.x, event.y)
        edit_state["scale"] = new_scale
        edit_state["offset_x"] = event.x - image_x * new_scale
        edit_state["offset_y"] = event.y - image_y * new_scale
        render_canvas_image()

    # 左键按下入口：按当前模式决定画框、缩放矩形、旋转、选择或拖图。
    def handle_canvas_press(event):
        if view_mode.get() == EDIT_MODE and edit_state["draw_enabled"] and event.num == 1:
            start_rectangle(event)
        elif view_mode.get() == EDIT_MODE and event.num == 1:
            resize_handle = find_resize_handle(event.x, event.y)
            if resize_handle is not None:
                start_resize(*resize_handle)
            else:
                handle_index = find_rotation_handle(event.x, event.y)
                if handle_index is not None:
                    start_rotation(handle_index)
                else:
                    rectangle_index = find_rectangle_at(event.x, event.y)
                    if rectangle_index is not None:
                        start_move_rectangle(rectangle_index, event)
                    else:
                        start_pan(event)
        else:
            start_pan(event)

    def handle_canvas_motion(event):
        if edit_state["drawing"]:
            update_rectangle(event)
        elif edit_state["rotating"]:
            update_rotation(event)
        elif edit_state["resizing"]:
            update_resize(event)
        elif edit_state["moving_rectangle"]:
            update_move_rectangle(event)
        else:
            update_pan(event)

    def handle_canvas_release(event):
        if edit_state["drawing"]:
            finish_rectangle(event)
        elif edit_state["rotating"]:
            finish_rotation(event)
        elif edit_state["resizing"]:
            finish_resize(event)
        elif edit_state["moving_rectangle"]:
            finish_move_rectangle(event)
        else:
            finish_pan(event)

    # 中键拖动只负责移动图片，不干扰正在绘制或编辑的矩形框。
    def handle_middle_pan_press(event):
        if view_mode.get() in (SINGLE_MODE, EDIT_MODE):
            start_pan(event)

    def handle_middle_pan_motion(event):
        if view_mode.get() in (SINGLE_MODE, EDIT_MODE):
            update_pan(event)

    def handle_middle_pan_release(_event):
        if view_mode.get() in (SINGLE_MODE, EDIT_MODE):
            finish_pan(_event)

    # 双击进入编辑模式；刚拖动过图片时忽略，避免误触发。
    def enter_edit_mode_from_double_click(_event):
        if time.monotonic() - edit_state["last_drag_release"] < 0.35:
            return
        show_edit_mode()

    # 打开指定索引图片进入单图浏览；从多图进入时记录返回位置。
    def show_image_at(index, from_multi=False):
        if not 0 <= index < len(image_paths):
            return

        if from_multi:
            last_multi_position.set(multi_canvas.yview()[0])
            visible_index = get_first_visible_multi_index()
            if 0 <= visible_index < len(image_paths):
                last_multi_top_index.set(visible_index)
            can_return_to_multi.set(True)

        current_image_index.set(index)
        show_single_mode()

    # 双击缩略图时直接加载原图并进入编辑模式。
    def edit_image_at(index, from_multi=False):
        if thumbnail_click_job["id"] is not None:
            root.after_cancel(thumbnail_click_job["id"])
            thumbnail_click_job["id"] = None

        if not 0 <= index < len(image_paths):
            return

        if from_multi:
            last_multi_position.set(multi_canvas.yview()[0])
            visible_index = get_first_visible_multi_index()
            if 0 <= visible_index < len(image_paths):
                last_multi_top_index.set(visible_index)
            can_return_to_multi.set(True)

        current_image_index.set(index)
        if show_image(image_paths[index]):
            show_edit_mode()

    # 多图单击使用短延迟，避免和双击进入编辑互相抢事件。
    def schedule_thumbnail_open(index):
        if thumbnail_click_job["id"] is not None:
            root.after_cancel(thumbnail_click_job["id"])

        if multi_select_mode.get():
            toggle_image_selection(index)
            return

        def open_selected():
            thumbnail_click_job["id"] = None
            show_image_at(index, from_multi=True)

        thumbnail_click_job["id"] = root.after(220, open_selected)

    def show_previous_image():
        show_image_at(current_image_index.get() - 1)

    def show_next_image():
        show_image_at(current_image_index.get() + 1)

    def show_edit_image_at(index):
        if not 0 <= index < len(image_paths):
            return
        close_rectangle_name_editor(save=True)
        save_current_tag()
        edit_state["active_index"] = None
        edit_undo_stack.clear()
        update_undo_button()
        current_image_index.set(index)
        if load_canvas_image(image_paths[index], fit=True):
            update_edit_controls()
            update_rectangle_object_list()
            render_canvas_image()
            root.focus_set()

    def show_previous_edit_image():
        show_edit_image_at(current_image_index.get() - 1)

    def show_next_edit_image():
        show_edit_image_at(current_image_index.get() + 1)

    def handle_left_key(_event):
        if view_mode.get() == SINGLE_MODE:
            show_previous_image()
        elif view_mode.get() == EDIT_MODE:
            show_previous_edit_image()
        elif view_mode.get() == MULTI_MODE:
            multi_canvas.yview_scroll(-1, "pages")

    def handle_right_key(_event):
        if view_mode.get() == SINGLE_MODE:
            show_next_image()
        elif view_mode.get() == EDIT_MODE:
            show_next_edit_image()
        elif view_mode.get() == MULTI_MODE:
            multi_canvas.yview_scroll(1, "pages")

    # Ctrl+Z 统一入口：编辑模式撤销编辑，否则撤销批量标记。
    def handle_undo_shortcut(_event):
        if view_mode.get() == EDIT_MODE:
            undo_last_edit()
        elif multi_select_undo_stack:
            undo_multi_select_tags()
        return "break"

    previous_button.configure(command=show_previous_image)
    next_button.configure(command=show_next_image)
    return_button.configure(command=return_to_multi_mode)
    delete_button.configure(command=delete_current_image)
    selected_add_tag_button.configure(command=add_tags_to_selected_images_from_toolbar)
    selected_clear_tag_button.configure(command=clear_tags_from_selected_images)
    multi_select_button.configure(command=toggle_multi_select_mode)
    select_all_button.configure(command=toggle_select_all_images)
    multi_undo_button.configure(command=undo_multi_select_tags, state=tk.DISABLED)
    save_tag_button.configure(command=save_current_tag)
    draw_box_button.configure(command=toggle_draw_rectangle)
    edit_previous_button.configure(command=show_previous_edit_image)
    edit_next_button.configure(command=show_next_edit_image)
    undo_button.configure(command=undo_last_edit, state=tk.DISABLED)
    exit_edit_button.configure(command=exit_edit_mode)
    rename_rectangle_button.configure(command=rename_active_rectangle, state=tk.DISABLED)
    delete_rectangle_button.configure(command=delete_active_rectangle, state=tk.DISABLED)
    edit_canvas.bind("<Double-Button-1>", enter_edit_mode_from_double_click)
    edit_canvas.bind("<ButtonPress-1>", handle_canvas_press)
    edit_canvas.bind("<B1-Motion>", handle_canvas_motion)
    edit_canvas.bind("<ButtonRelease-1>", handle_canvas_release)
    edit_canvas.bind("<ButtonPress-2>", handle_middle_pan_press)
    edit_canvas.bind("<B2-Motion>", handle_middle_pan_motion)
    edit_canvas.bind("<ButtonRelease-2>", handle_middle_pan_release)
    edit_canvas.bind("<Button-3>", lambda event: show_context_menu(event, current_image_path()))
    edit_canvas.bind("<MouseWheel>", zoom_canvas)
    edit_canvas.bind("<Configure>", lambda _event: render_canvas_image() if view_mode.get() in (SINGLE_MODE, EDIT_MODE) else None)
    rectangle_listbox.bind("<<ListboxSelect>>", select_rectangle_from_list)
    rectangle_listbox.bind("<Double-Button-1>", lambda _event: start_inline_rename_rectangle(rectangle_listbox.nearest(_event.y)))
    rectangle_listbox.bind("<Button-3>", show_rectangle_object_menu)
    box_tag_entry.bind("<KeyRelease>", update_active_rectangle_tag)
    root.bind("<Configure>", lambda _event: (layout_edit_controls(), layout_edit_workspace()) if view_mode.get() == EDIT_MODE else None)
    root.bind("<Left>", handle_left_key)
    root.bind("<Right>", handle_right_key)
    root.bind("<Control-z>", handle_undo_shortcut)
    root.bind("<Control-Z>", handle_undo_shortcut)

    placeholder_image = ImageTk.PhotoImage(Image.new("RGB", THUMBNAIL_SIZE, "#f4f4f4"))

    # 清空多图网格和缩略图引用。
    def clear_multi_grid():
        thumbnail_images.clear()
        thumbnail_buttons.clear()
        for child in multi_grid.winfo_children():
            child.destroy()

    # 把异步加载好的缩略图更新到对应按钮；generation 防止旧任务覆盖新网格。
    def set_thumbnail(index, generation, image):
        if generation != multi_render_generation.get():
            return
        if index not in thumbnail_buttons:
            return

        photo = ImageTk.PhotoImage(image)
        thumbnail_images.append(photo)
        thumbnail_buttons[index].configure(image=photo)

    # 主线程轮询缩略图队列，把后台线程结果安全更新到 Tk 控件。
    def process_thumbnail_queue():
        while True:
            try:
                index, generation, image = thumbnail_queue.get_nowait()
            except Empty:
                break
            set_thumbnail(index, generation, image)

        root.after(50, process_thumbnail_queue)

    def draw_thumbnail_rectangles(image, rectangles, source_path):
        if not rectangles:
            return image

        try:
            with Image.open(source_path) as original:
                original = ImageOps.exif_transpose(original)
                original_width, original_height = original.size
        except (AttributeError, OSError, ValueError):
            return image

        scale_x = image.width / max(original_width, 1)
        scale_y = image.height / max(original_height, 1)
        draw = ImageDraw.Draw(image)
        for rectangle in rectangles:
            color = "#d7263d" if rectangle.get("tag") else "#2f80ed"
            center_x = rectangle["center_x"] * scale_x
            center_y = rectangle["center_y"] * scale_y
            width = rectangle["width"] * scale_x
            height = rectangle["height"] * scale_y
            angle = radians(rectangle["angle"])
            half_width = width / 2
            half_height = height / 2
            corners = [
                (-half_width, -half_height),
                (half_width, -half_height),
                (half_width, half_height),
                (-half_width, half_height),
            ]
            points = [
                (
                    center_x + x * cos(angle) - y * sin(angle),
                    center_y + x * sin(angle) + y * cos(angle),
                )
                for x, y in corners
            ]
            draw.line(points + [points[0]], fill=color, width=2)
            tag = rectangle.get("tag", "")
            if tag:
                text_x, text_y = points[0]
                text_y = max(text_y - 12, 2)
                text_bbox = draw.textbbox((text_x, text_y), tag)
                draw.rectangle(
                    (text_bbox[0] - 3, text_bbox[1] - 2, text_bbox[2] + 3, text_bbox[3] + 2),
                    fill=color,
                    outline="white",
                )
                draw.text((text_x, text_y), tag, fill="white")
        return image

    # 提交缩略图后台加载任务，先快速低质量，再延迟高清替换。
    def queue_thumbnail(index, path, generation, resampling, delay_ms):
        rectangles = [dict(rectangle) for rectangle in image_rectangles.get(path, [])]

        def load_and_apply():
            try:
                image = load_thumbnail(path, THUMBNAIL_SIZE, resampling)
            except (OSError, ValueError):
                return
            image = draw_thumbnail_rectangles(image, rectangles, path)
            thumbnail_queue.put((index, generation, image))

        root.after(delay_ms, lambda: executor.submit(load_and_apply))

    # 渲染多图网格：先放占位图，再异步加载缩略图。
    def render_multi_grid():
        multi_render_generation.set(multi_render_generation.get() + 1)
        generation = multi_render_generation.get()
        multi_grid_dirty.set(False)
        clear_multi_grid()

        if not image_paths:
            return

        for index, path in enumerate(image_paths):
            tag = format_tags(image_tags.get(path, []))
            label_text = path.name if not tag else f"{path.name}\n★ 标记：{tag}"
            button = tk.Button(
                multi_grid,
                image=placeholder_image,
                text=label_text,
                compound=tk.TOP,
                bg="#ffffff",
                fg="#1358b7" if tag else "#1f2937",
                activebackground="#f2f2f2",
                activeforeground="#1358b7" if tag else "#1f2937",
                font=("Microsoft YaHei UI", 9, "bold" if tag else "normal"),
                relief=tk.FLAT,
                borderwidth=1,
                command=lambda selected=index: schedule_thumbnail_open(selected),
            )
            button.bind(
                "<Double-Button-1>",
                lambda _event, selected=index: edit_image_at(selected, from_multi=True),
            )
            button.bind(
                "<Button-3>",
                lambda event, selected_path=path: show_context_menu(event, selected_path),
            )
            button.grid(row=index // MULTI_COLUMNS, column=index % MULTI_COLUMNS, padx=10, pady=10)
            thumbnail_buttons[index] = button
            update_thumbnail_selection(index)

            queue_thumbnail(index, path, generation, Image.Resampling.NEAREST, 10 + index * 3)
            queue_thumbnail(index, path, generation, Image.Resampling.LANCZOS, 300 + index * 10)

        thumbnail_images.append(placeholder_image)

        for column in range(MULTI_COLUMNS):
            multi_grid.columnconfigure(column, weight=1, uniform="images")

        update_multi_select_controls()
        update_multi_scroll_region()

    # 关闭软件时停止缩略图线程池，并清理运行期裁剪临时目录。
    def close_app():
        if view_mode.get() == EDIT_MODE:
            save_current_tag(record_undo=False)
        else:
            persist_annotation_config()
        executor.shutdown(wait=False, cancel_futures=True)
        root.destroy()

    # 菜单“打开图片”：加载单张图片并进入单图浏览。
    def open_image():
        file_path = filedialog.askopenfilename(
            title="打开图片",
            filetypes=SUPPORTED_IMAGE_TYPES,
        )
        if not file_path:
            return

        all_image_paths.clear()
        all_image_paths.append(Path(file_path))
        image_paths.clear()
        image_paths.extend(all_image_paths)
        load_or_create_annotation_config(Path(file_path).parent)
        selected_image_paths.clear()
        multi_select_undo_stack.clear()
        multi_select_mode.set(False)
        filter_active.set(False)
        filter_button.configure(text="筛选")
        update_multi_select_controls()
        edit_undo_stack.clear()
        update_undo_button()
        current_image_index.set(0)
        can_return_to_multi.set(False)

        show_single_mode()

    # 菜单“打开文件夹”：扫描并加载文件夹内所有支持格式图片。
    def open_folder():
        folder_path = filedialog.askdirectory(title="打开文件夹")
        if not folder_path:
            return

        folder = Path(folder_path)
        paths = sorted(
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
        )

        if not paths:
            messagebox.showinfo("没有图片", "该文件夹中没有 JPG、PNG 或 BMP 图片。")
            return

        all_image_paths.clear()
        all_image_paths.extend(paths)
        image_paths.clear()
        image_paths.extend(all_image_paths)
        load_or_create_annotation_config(folder)
        selected_image_paths.clear()
        multi_select_undo_stack.clear()
        multi_select_mode.set(False)
        filter_active.set(False)
        filter_button.configure(text="筛选")
        update_multi_select_controls()
        edit_undo_stack.clear()
        update_undo_button()
        current_image_index.set(0)
        can_return_to_multi.set(False)
        show_multi_mode()
        root.after(50, lambda: multi_canvas.yview_moveto(0.0))

    # Windows 右键打开方式入口：根据命令行参数打开图片或文件夹。
    def open_startup_path(startup_path):
        path = Path(startup_path)
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
            all_image_paths.clear()
            all_image_paths.append(path)
            image_paths.clear()
            image_paths.extend(all_image_paths)
            load_or_create_annotation_config(path.parent)
            selected_image_paths.clear()
            multi_select_undo_stack.clear()
            multi_select_mode.set(False)
            filter_active.set(False)
            filter_button.configure(text="筛选")
            update_multi_select_controls()
            edit_undo_stack.clear()
            update_undo_button()
            current_image_index.set(0)
            can_return_to_multi.set(False)
            show_single_mode()
        elif path.is_dir():
            paths = sorted(
                image_path
                for image_path in path.iterdir()
                if image_path.is_file() and image_path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
            )
            if paths:
                all_image_paths.clear()
                all_image_paths.extend(paths)
                image_paths.clear()
                image_paths.extend(all_image_paths)
                load_or_create_annotation_config(path)
                selected_image_paths.clear()
                multi_select_undo_stack.clear()
                multi_select_mode.set(False)
                filter_active.set(False)
                filter_button.configure(text="筛选")
                update_multi_select_controls()
                edit_undo_stack.clear()
                update_undo_button()
                current_image_index.set(0)
                can_return_to_multi.set(False)
                show_multi_mode()

    # 菜单“帮助 > 使用手册”：用系统默认程序打开说明文本。
    def open_user_manual():
        base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        manual_path = base_dir / "使用手册.txt"
        if not manual_path.exists():
            messagebox.showerror("使用手册", f"未找到使用手册文件：\n{manual_path}")
            return
        try:
            os.startfile(manual_path)
        except OSError as error:
            messagebox.showerror("使用手册", f"无法打开使用手册：\n{error}")

    # 工具 > 简单统计：汇总每个类别对应的图片数、矩形框数和未标注图片数。
    def show_simple_statistics():
        if not all_image_paths:
            messagebox.showinfo("简单统计", "请先打开图片或文件夹。")
            return

        category_image_paths = {}
        category_box_counts = {}
        unannotated_count = 0
        total_boxes = 0
        tagged_boxes = 0

        for path in all_image_paths:
            image_tag_values = [tag for tag in image_tags.get(path, []) if tag.strip()]
            tagged_rectangle_values = []

            for rectangle in image_rectangles.get(path, []):
                total_boxes += 1
                rectangle_tag = rectangle.get("tag", "").strip()
                if not rectangle_tag:
                    continue
                tagged_boxes += 1
                tagged_rectangle_values.append(rectangle_tag)
                category_box_counts[rectangle_tag] = category_box_counts.get(rectangle_tag, 0) + 1

            for tag in set(image_tag_values + tagged_rectangle_values):
                category_image_paths.setdefault(tag, set()).add(path)

            if not image_tag_values and not tagged_rectangle_values:
                unannotated_count += 1

        category_names = sorted(
            set(category_image_paths) | set(category_box_counts),
            key=lambda value: value.casefold(),
        )

        dialog = tk.Toplevel(root)
        dialog.title("简单统计")
        dialog.configure(bg="#ffffff")
        dialog.geometry("560x460")
        dialog.minsize(460, 360)
        dialog.transient(root)

        summary = tk.Frame(dialog, bg="#e8f1ff", highlightthickness=1, highlightbackground="#cfe6ff")
        summary.pack(fill=tk.X, padx=14, pady=(14, 10))

        summary_items = (
            ("总图片", len(all_image_paths)),
            ("未标注图片", unannotated_count),
            ("总矩形框", total_boxes),
            ("已标记矩形框", tagged_boxes),
        )
        for label, value in summary_items:
            item = tk.Frame(summary, bg="#e8f1ff")
            item.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=8)
            tk.Label(item, text=label, bg="#e8f1ff", fg="#334155").pack()
            tk.Label(item, text=str(value), bg="#e8f1ff", fg="#1358b7", font=("Microsoft YaHei UI", 14, "bold")).pack()

        table_frame = tk.Frame(dialog, bg="#ffffff")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))

        columns = ("category", "images", "boxes")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        tree.heading("category", text="类别")
        tree.heading("images", text="图片数")
        tree.heading("boxes", text="矩形框数")
        tree.column("category", width=260, anchor=tk.W)
        tree.column("images", width=90, anchor=tk.CENTER)
        tree.column("boxes", width=100, anchor=tk.CENTER)

        scrollbar = tk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for category in category_names:
            tree.insert(
                "",
                tk.END,
                values=(
                    category,
                    len(category_image_paths.get(category, set())),
                    category_box_counts.get(category, 0),
                ),
            )

        if not category_names:
            tree.insert("", tk.END, values=("暂无类别", 0, 0))

        buttons = tk.Frame(dialog, bg="#ffffff")
        buttons.pack(fill=tk.X, padx=14, pady=(0, 14))
        close_button = tk.Button(buttons, text="关闭", command=dialog.destroy)
        style_button(close_button, "primary")
        close_button.pack(side=tk.RIGHT)

    menu_bar = tk.Menu(root)

    file_menu = tk.Menu(menu_bar, tearoff=0)
    file_menu.add_command(label="打开图片", command=open_image)
    file_menu.add_command(label="打开文件夹", command=open_folder)
    file_menu.add_separator()
    file_menu.add_command(label="退出", command=close_app)
    menu_bar.add_cascade(label="文件", menu=file_menu)

    import_menu = tk.Menu(menu_bar, tearoff=0)
    import_menu.add_command(label="导入md配置文件", command=import_annotation_config)
    import_menu.add_separator()
    import_menu.add_command(label="导入COCO配置文件", command=import_coco_config)
    import_menu.add_command(label="导入YOLO配置文件夹", command=import_yolo_config)
    menu_bar.add_cascade(label="导入", menu=import_menu)

    tool_menu = tk.Menu(menu_bar, tearoff=0)
    tool_menu.add_command(label="简单统计", command=show_simple_statistics)
    menu_bar.add_cascade(label="工具", menu=tool_menu)

    export_menu = tk.Menu(menu_bar, tearoff=0)
    export_menu.add_command(label="导出当前全部图片", command=export_all_images)
    export_menu.add_command(label="导出选中图片", command=export_selected_images)
    export_menu.add_separator()
    export_menu.add_command(label="导出COCO配置文件", command=export_coco_config)
    export_menu.add_command(label="导出YOLO配置文件夹", command=export_yolo_config)
    export_menu.add_separator()
    export_menu.add_command(label="导出特定标记矩形框", command=export_rectangles_by_tag)
    menu_bar.add_cascade(label="导出", menu=export_menu)

    about_menu = tk.Menu(menu_bar, tearoff=0)
    about_menu.add_command(
        label="关于",
        command=lambda: messagebox.showinfo("关于", "该小工具软件针对工业视觉检测现场，\n可以快速高效的浏览图像，\n并具有一定的处理图像能力。"),
    )
    menu_bar.add_cascade(label="关于", menu=about_menu)

    help_menu = tk.Menu(menu_bar, tearoff=0)
    help_menu.add_command(label="使用手册", command=open_user_manual)
    menu_bar.add_cascade(label="帮助", menu=help_menu)

    root.config(menu=menu_bar)
    root.protocol("WM_DELETE_WINDOW", close_app)
    update_multi_select_controls()
    process_thumbnail_queue()
    if len(sys.argv) > 1:
        root.after(100, lambda: open_startup_path(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
