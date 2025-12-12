import os
from pathlib import Path
import argparse
import re
import json
import logging
import shutil
import filetype
import subprocess
from datetime import datetime
import pytz
import pprint
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 全局变量 ---
# 设置本地时区
local_timezone = pytz.timezone("Asia/Shanghai")

# 文件扩展名
image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw'}
video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.mts', '.m2ts'}
media_extensions = image_extensions | video_extensions
json_extensions = {'.json'}

# --- 辅助函数 ---
# 获取输入的前45个字符
def get_file_name_cut(any_str, length=45):
    return any_str[:length]  # 返回文件的前45个字符，包括扩展名


# 更新json中的title值, 把title值更新为现在media的full_name
def update_json_key_title(media_path, json_path):
    '''
    update_json_key_title 的 Docstring
    给定媒体文件路径和对应的 JSON 文件路径，更新 JSON 文件中的 title 字段为媒体文件的完整文件名
    '''
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))  # 从json中读取数据
        data["title"] = Path(media_path).name  # 草稿更改title值的扩展名
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")  # 把草稿数据写入文件
    except Exception as e:
        logging.error(f"- 更新json {Path(json_path).name} 的title时出错: {e}")


# 修改文件系统时间 (兼容 Windows 创建时间)
def set_file_times(file_path, timestamp):
    '''
    set_file_times 的 Docstring
    给定一个文件路径和时间戳，修改该文件的访问时间、修改时间和创建时间
    '''
    try:
        # 修改访问时间和修改时间 (跨平台)
        os.utime(file_path, (timestamp, timestamp))
        # Windows下修改创建时间需要特殊处理
        if os.name == 'nt':
            try:
                from ctypes import windll, wintypes, byref
                # 转换时间戳为 Windows FileTime (100纳秒间隔，自1601年1月1日)
                timestamp_int = int(timestamp * 10000000) + 116444736000000000
                ctime = wintypes.FILETIME(timestamp_int & 0xFFFFFFFF, timestamp_int >> 32)
                
                # 打开文件句柄
                handle = windll.kernel32.CreateFileW(str(file_path), 256, 0, None, 3, 128, None)
                if handle != -1:
                    # 设置创建时间，最后两个 None 是访问时间和修改时间(上面utime已经改了，这里不用动)
                    windll.kernel32.SetFileTime(handle, byref(ctime), None, None)
                    windll.kernel32.CloseHandle(handle)
            except Exception as e:
                logging.error(f"{file_path}Windows创建时间修改失败: {e}")
    except Exception as e:
        logging.error(f"{file_path}时间戳修改失败: {e}")


# 阶段 1: 遍历所有文件, 建立文件列表
def collect_all_files(directory, extensions):
    '''
    collect_all_files 的 Docstring
    遍历目录，收集指定扩展名的所有文件
    '''
    all_files = []
    for root, _, names in os.walk(directory):
        for name in names:
            file_path = Path(root) / name
            suffix = file_path.suffix.lower()
            if suffix in extensions:
                all_files.append(file_path)
    return all_files

def get_media_name_part_cut(media_file):
    '''
    get_media_name_part_cut 的 Docstring
    给定一个媒体文件路径, 提取可能的媒体文件名部分及其前45个字符
    '''
    media_fullname = media_file.name  # 带扩展名的完整文件名
    media_stem = media_file.stem  # 不带扩展名的文件名
    media_ext = media_file.suffix  # 文件扩展名
    # 获取前45个字符
    media_fullname_cut = get_file_name_cut(media_fullname)  # 获取媒体文件前45个字符，包括扩展名
    media_stem_cut = get_file_name_cut(media_stem)  #  获取媒体文件基名前45个字符
    # 处理去重编号
    media_dup_suffix = re.search(r"\(\d{1,2}\)$", media_stem)  # 查找文件名末尾的去重编号（如(1), (2)）
    media_fullname_no_dup_cut = ""
    media_stem_no_dup_cut = ""
    if media_dup_suffix:
        media_dup_suffix = media_dup_suffix.group(0)  # 提取匹配的去重编号字符串
        media_fullname_no_dup = media_stem[:-len(media_dup_suffix)] + media_ext  # 从完整文件名里去掉去重编号，获取剩余文件名
        media_stem_no_dup = media_stem[:-len(media_dup_suffix)]  # 从基名里去掉去重编号，获取剩余基名
        media_fullname_no_dup_cut = get_file_name_cut(media_fullname_no_dup)  #  从上面的文件名里获取前45个字符
        media_stem_no_dup_cut = get_file_name_cut(media_stem_no_dup)  #  从上面的基名里获取前45个字符
    return (media_fullname_cut, media_stem_cut, media_dup_suffix, media_fullname_no_dup_cut, media_stem_no_dup_cut)


def get_json_media_name_part_cut(json_file):
    '''
    get_json_media_name_parts 的 Docstring
    给定一个 JSON 文件路径, 提取可能的媒体文件名部分及其前45个字符
    '''
    json_stem = json_file.stem  # 不带扩展名的文件名
    json_stem_no_dup = json_stem
    json_dup_suffix = re.search(r"\(\d{1,2}\)$", json_stem)  # 查找 JSON 文件名末尾的去重编号
    if json_dup_suffix:
        json_dup_suffix = json_dup_suffix.group(0)  # 提取匹配的去重编号字符串
        json_stem_no_dup = json_stem[:-len(json_dup_suffix)]  # 从基名里去掉去重编号，获取剩余基名
    json_stem_no_dup_parts = json_stem_no_dup.split('.')  # 用"."分割去重后的基名
    if len(json_stem_no_dup_parts) >= 2 and ("."+json_stem_no_dup_parts[1].lower()) in media_extensions:
        ext_in_stem = "." + json_stem_no_dup_parts[1]  # 标记扩展名在基名中
        json_media_name_part = json_stem_no_dup_parts[0] + ext_in_stem  # 可能的媒体文件名部分
    else:
        ext_in_stem = None  # 标记扩展名不在基名中
        json_media_name_part = json_stem_no_dup_parts[0]  # 可能的媒体文件名部分
    json_media_name_part_cut = get_file_name_cut(json_media_name_part)  # 获取可能的媒体文件名部分的前45个字符  
    return json_media_name_part_cut, ext_in_stem, json_dup_suffix


# 阶段 2: 查找匹配的 JSON 文件
def find_matching_json(media_file, all_json_files):
    '''
    find_matching_json 的 Docstring
    给定一个media_file, 从all_json_files中寻找匹配的JSON文件
    依据文件名前45个字符进行匹配, 考虑去重编号的情况
    '''
    media_fullname_cut, media_stem_cut, media_dup_suffix, media_fullname_no_dup_cut, media_stem_no_dup_cut = get_media_name_part_cut(media_file)
    # 1. 当json文件名***含***media_ext
    for json_file in all_json_files:
        json_media_name_part_cut, ext_in_stem, json_dup_suffix = get_json_media_name_part_cut(json_file)  # 获取可能的媒体文件名部分的前45个字符
        if media_file.parent == json_file.parent and ext_in_stem:
            # ***无***去重编号
            if not json_dup_suffix and (media_fullname_cut == json_media_name_part_cut):
                print(f"E1D0.匹配成功: {media_file} <--> {json_file}")
                return json_file
            # ***有***去重编号
            elif media_dup_suffix and json_dup_suffix and (media_dup_suffix == json_dup_suffix) and (media_fullname_no_dup_cut == json_media_name_part_cut):
                print(f"E1D1.匹配成功: {media_file} <--> {json_file}")
                return json_file 
    # 2. 当json文件名***不含***media_ext
    for json_file in all_json_files:
        json_media_name_part_cut, ext_in_stem, json_dup_suffix = get_json_media_name_part_cut(json_file)  # 获取可能的媒体文件名部分的前45个字符
        if (media_file.parent == json_file.parent) and not ext_in_stem:
            # ***无***去重编号
            if not json_dup_suffix and (media_stem_cut == json_media_name_part_cut):
                print(f"E0D0.匹配成功: {media_file} <--> {json_file}")
                return json_file
            # ***有***去重编号
            elif media_dup_suffix and json_dup_suffix and (media_dup_suffix == json_dup_suffix) and (media_stem_no_dup_cut == json_media_name_part_cut):
                print(f"E0D1.匹配成功: {media_file} <--> {json_file}")
                return json_file
    print(f"通过find_matching_json未找到匹配的JSON文件 for {media_file}")
    return None  # 未找到匹配的 JSON 文件


def live_photo_treat(media_file, matched_pairs):
    '''
    live_photo_treat 的 Docstring
    对于可能是 live photo 类型的媒体文件，从已匹配的同名图片文件中寻找并建立对应的 JSON 文件
    '''
    media_fullname = media_file.name  # 带扩展名的完整文件名
    media_stem = media_file.stem  # 不带扩展名的文件名
    media_ext = media_file.suffix  # 文件扩展名

    # 判断开始
    if media_ext.lower() in video_extensions:
        for ref_media_file in matched_pairs:
            if (ref_media_file.parent == media_file.parent) and (ref_media_file.suffix.lower() in image_extensions) and media_stem == ref_media_file.stem and matched_pairs[ref_media_file]:
                    json_fullname = media_fullname + ".json"
                    json_file = media_file.parent / json_fullname
                    shutil.copy2(matched_pairs[ref_media_file], json_file)
                    update_json_key_title(media_file, json_file)
                    print(f"LP.匹配成功: {media_file} <--> {json_file}")
                    return json_file

    print(f"通过live_photo_treat未找到匹配的JSON文件 for {media_file}")
    return None  # 未找到匹配的 JSON 文件
    

def find_matching_pairs(all_media_files, all_json_files):
    '''
    find_matching_pairs 的 Docstring
    匹配媒体文件与 JSON 文件，返回匹配对字典
    '''
    # 0. 分离图片和视频文件列表
    all_image_files = [f for f in all_media_files if f.suffix.lower() in image_extensions]
    all_video_files = [f for f in all_media_files if f.suffix.lower() in video_extensions]
    # 1. 先处理图片文件的匹配, 保证图片优先匹配, 找不到的同名视频可以通过 live photo 处理
    print(f"--- 阶段 2.1: 寻找image文件的匹配 ---")
    matched_pairs = dict.fromkeys(all_image_files, None)
    for media_file in list(matched_pairs.keys()):
        if matched_pairs[media_file] is None:
            json_file = find_matching_json(media_file, all_json_files)
            if json_file:
                matched_pairs[media_file] = json_file
                all_json_files.remove(json_file)  # 移除已匹配的 JSON 文件，防止重复使用
    # 2. 再处理视频文件的匹配
    print(f"--- 阶段 2.2: 寻找video文件的匹配 ---")
    matched_pairs.update(dict.fromkeys(all_video_files, None))
    for media_file in list(matched_pairs.keys()):
        if matched_pairs[media_file] is None and media_file.suffix.lower() in video_extensions:
            json_file = find_matching_json(media_file, all_json_files)
            if json_file:
                matched_pairs[media_file] = json_file
                all_json_files.remove(json_file)  # 移除已匹配的 JSON 文件，防止重复使用
    # 3. 再处理live photo可疑视频文件的匹配
    print(f"--- 阶段 2.3: 处理live photo可疑video文件的匹配 ---")
    for media_file in list(matched_pairs.keys()):
        if matched_pairs[media_file] is None and media_file.suffix.lower() in video_extensions:
            json_file = live_photo_treat(media_file, matched_pairs)
            if json_file:
                matched_pairs[media_file] = json_file

    # 4. 善后清理
    print(f"--- 阶段 2.4: 善后清理 ---")
    matched_pairs = cleanup_matched_pairs(matched_pairs)
    cleanup_unmatched_json(all_json_files)

    return matched_pairs


def cleanup_matched_pairs(matched_pairs):
    '''
    cleanup_matched_pairs 的 Docstring
    清理匹配对字典，移除未匹配的项
    '''
    # 1. 创建待删除键的列表
    keys_to_delete = []
    for media_file in matched_pairs:
        if matched_pairs[media_file] is None:
            try:
                if media_file.anchor == '':
                    media_relative_path = media_file
                else:
                    media_relative_path = media_file.relative_to(media_file.anchor)
                target_dir = Path("unmatched") / media_relative_path.parent
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / media_file.name
                print(f"[清理] 正在移动未匹配 MEDIA 文件: {media_file} -> {target_path}")
                logging.info(f"[清理] 未匹配 MEDIA 文件: {media_file} -> {target_path}")
                shutil.move(str(media_file), str(target_path))
            except Exception as e:
                logging.error(f"[清理失败] 移动未匹配文件: {media_file} -> {target_path}, 错误: {e}")
            keys_to_delete.append(media_file)
    # 2. 删除未匹配的键
    for key in keys_to_delete:
        del matched_pairs[key]

    return matched_pairs


def cleanup_unmatched_json(all_json_files):
    '''
    cleanup_unmatched_json 的 Docstring
    清理未匹配的 JSON 文件，移动到 unmatched 目录
    '''
    for json_file in all_json_files:
        if json_file and json_file.exists():
            try:
                if json_file.anchor == '':
                    json_relative_path = json_file
                else:
                    json_relative_path = json_file.relative_to(json_file.anchor)
                target_dir = Path("unmatched") / json_relative_path.parent
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / json_file.name
                print(f"[清理] 正在移动未匹配 JSON 文件: {json_file} -> {target_path}")
                logging.info(f"[清理] 未匹配 JSON 文件: {json_file} -> {target_path}")
                shutil.move(str(json_file), str(target_path))
            except Exception as e:
                logging.error(f"[清理失败] 移动未匹配 JSON 文件: {json_file} -> {target_path}, 错误: {e}")


def let_ext_correct(media_file, json_file):
    # 检测文件类型
    kind = filetype.guess(media_file)
    if kind is None:
        print(f"! 无法识别文件类型: {media_file}")
        return media_file, json_file
    detected_extension = f".{kind.extension}"
    current_extension = Path(media_file).suffix.lower()
    if detected_extension == ".jpeg":  # jpg有两种扩展名
        detected_extension = ".jpg"
    if current_extension == ".jpeg":
        current_extension = ".jpg"
    if detected_extension != current_extension:
        # 构建新文件名
        new_media_fullname = Path(media_file).stem + detected_extension
        new_media_file = Path(media_file).with_name(new_media_fullname)
        count = 1
        while new_media_file.exists():  # 如果新文件名已存在，添加数字后缀
            if re.search(r"_\d{1,2}$", Path(new_media_file).stem):
                new_media_fullname = re.sub(r"_\d{1,2}$", f"_{count}", Path(new_media_file).stem) + detected_extension
            else:
                new_media_fullname = f"{Path(new_media_file).stem}_{count}{detected_extension}"
            new_media_file = Path(media_file).with_name(new_media_fullname)
            count += 1
        # 重命名媒体文件
        try: 
            print(f"- 更正扩展名: {Path(media_file).name} --> {Path(new_media_file).name}")
            Path(media_file).rename(new_media_file)
            media_file = new_media_file  # 更新media_file为新文件名
        except Exception as e:
            logging.error(f"! 重命名文件 {Path(media_file).name} 时出错: {e}")
        # 重命名对应的json文件
        if json_file:
            json_fullname = Path(json_file).name
            try:
                new_json_fullname = Path(media_file).name + ".json"
                new_json_file = Path(json_file).with_name(new_json_fullname)
                print(f"- 更正对应json文件名: {Path(json_file).name} --> {Path(new_json_file).name}")
                Path(json_file).rename(new_json_file)
                json_file = new_json_file  # 更新json_file为新文件名
            except Exception as e:
                logging.error(f"! 重命名文件 {Path(json_file).name} 时出错: {e}")
        # 更新json中的title值
        if json_file:
            update_json_key_title(media_file, json_file)

    return media_file, json_file  # 返回更新后的文件路径


def correct_ext_of_matched_pairs(matched_pairs):
    '''
    correct_ext_of_matched_pairs 的 Docstring
    对匹配对中的媒体文件进行扩展名更正
    '''
    for media_file in list(matched_pairs.keys()):
        json_file = matched_pairs[media_file]
        new_media_file, new_json_file = let_ext_correct(media_file, json_file)
        # 如果文件名有变更，更新匹配对字典的键和值
        if new_media_file != media_file:
            matched_pairs[new_media_file] = matched_pairs.pop(media_file)
        if new_json_file != json_file:
            matched_pairs[new_media_file] = new_json_file
    return matched_pairs


def update_media_metadata(media_file, json_file):
    """
    使用 ExifTool 将 JSON 信息写入媒体文件 (支持 JPG, HEIC, MP4, MOV)
    """
    try:
        # 1. 读取 JSON 数据
        data = json.loads(json_file.read_text(encoding="utf-8"))
        # 2. 获取并处理时间戳
        timestamp = None
        if "photoTakenTime" in data and "timestamp" in data["photoTakenTime"]:
            timestamp = float(data["photoTakenTime"]["timestamp"])
        elif "creationTime" in data and "timestamp" in data["creationTime"]:
            timestamp = float(data["creationTime"]["timestamp"])
        if not timestamp:
            print(f"! JSON中未找到时间戳, 跳过")
            return
        # 将时间戳转换为 ExifTool 需要的字符串格式 "YYYY:MM:DD HH:MM:SS"
        # 注意：这里使用 local_timezone (在脚本开头定义的)
        timestamp_localized = datetime.fromtimestamp(timestamp, local_timezone)
        date_str = timestamp_localized.strftime("%Y:%m:%d %H:%M:%S")
        # 3. 准备 ExifTool 命令参数
        cmd = [
            "exiftool", 
            "-charset filename=utf8",  # 处理文件名中的非ASCII字符
            "-overwrite_original",   # -overwrite_original: 直接覆盖原文件，不生成 _original 备份
            "-P",   # -P: 保留文件系统修改时间 (虽然我们后面会手动改，但加个保险)
            "-u",  # -u: 允许写入未知标签 (增加兼容性)
            f"-AllDates={date_str}",    # 写入所有常见日期标签 (DateTimeOriginal, CreateDate, ModifyDate)
        ]
        # 4. 处理 GPS 信息
        geo = data.get('geoDataExif') or data.get('geoData')
        if geo and geo.get('latitude', 0.0) != 0.0:
            lat = geo['latitude']
            lng = geo['longitude']
            alt = geo.get('altitude', 0)
            # ExifTool 非常智能，直接传带符号的浮点数，它会自动计算 Ref (N/S, E/W)
            cmd.append(f"-GPSLatitude={lat}")
            cmd.append(f"-GPSLatitudeRef={lat}")
            cmd.append(f"-GPSLongitude={lng}")
            cmd.append(f"-GPSLongitudeRef={lng}")
            cmd.append(f"-GPSAltitude={alt}")
            # 针对视频文件的特殊 GPS 标签 (QuickTime)
            # 格式通常为 "+23.1250+113.3393/"
            if media_file.suffix.lower() in video_extensions:
                 # 简单的视频 GPS 格式化，ExifTool 对视频 GPS 支持稍微复杂一点，这行尝试写入通用的 Keys
                cmd.append(f"-Keys:GPSCoordinates={lat}, {lng}, {alt}")
        # 5. 添加目标文件路径
        # 必须把路径转为字符串
        cmd.append(str(media_file))
        # 6. 执行命令
        # Windows下如果不把 exiftool.exe 放 PATH，可能需要指定完整路径，如 ".\exiftool.exe"
        # 这里假设你把它放在了同目录或 PATH 里
        exiftool_cmd = "exiftool" 
        if os.path.exists("exiftool.exe"): # 如果当前目录下有
            exiftool_cmd = os.path.abspath("exiftool.exe")
        cmd[0] = exiftool_cmd
        print(f"  - 正在调用 ExifTool 写入元数据...")
        # capture_output=True 可以隐藏控制台的大量输出，只看报错
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"√ ExifTool 写入成功")
        else:
            logging.error(f"ExifTool 报错 {media_file.name}: {result.stderr}")
            print(f"! ExifTool 报错: {result.stderr.strip()}")
        # 7. (可选) 再次强制刷新文件系统时间
        # 虽然 ExifTool 加了 -FileModifyDate，但有时候 Python 的 os.utime 更准
        set_file_times(media_file, timestamp)
        set_file_times(json_file, timestamp)
    except Exception as e:
        logging.error(f"元数据更新流程出错 {media_file.name}: {e}")
        print(f"! 错误: {e}")


def update_media_metadata_mp(matched_pairs):
    '''
    update_media_metadata_with_matched_pairs 的 Docstring
    对匹配对中的媒体文件进行元数据更新
    '''
    for media_file in list(matched_pairs.keys()):
        json_file = matched_pairs[media_file]
        if json_file:
            print(f"--- 正在使用 {json_file} 更新元数据: {media_file} ---")
            update_media_metadata(media_file, json_file)
    return matched_pairs

def update_media_metadata_mp_mt(matched_pairs):
    '''
    update_media_metadata_with_matched_pairs_with_multi_threading 的 Docstring
    用多线程对匹配对中的媒体文件进行元数据更新
    '''
    tasks = list(matched_pairs.items())
    workers = os.cpu_count() or 8
    with ThreadPoolExecutor(max_workers=workers) as executor: # 例如使用8个线程
        # 提交阶段 4 的所有元数据更新任务
        futures = {executor.submit(update_media_metadata, media_path, json_path): (media_path, json_path) for media_path, json_path in tasks}
        # 等待所有任务完成
        for future in as_completed(futures):
            # 处理结果或异常
            # 🚨 查找原始文件路径
            media_path, json_path = futures[future]  
            try:
                # 尝试获取任务结果（这也会触发异常，如果任务失败）
                future.result()     
            except Exception as e:
                # 报告错误时，可以明确指出是哪个文件出了问题
                logging.error(f"--- 阶段 4:处理文件 {media_path.name} 时发生错误: {e}")
            pass


# ⭐ 主函数 (修改为两阶段处理) ⭐
def repair_media_files(directory):
    # 2.1 构造基于目录的日志文件名
    # 规范化目录名，防止特殊字符
    sanitized_dir = Path(directory).name.replace(os.sep, '_').replace(':', '_').replace(' ', '_')
    log_filename = f"media_file_repair_{sanitized_dir}.log"

    # 2.2 配置日志（只在这个实例中生效）
    # 注意：要用 filemode='w' 清空旧日志，或用 'a' 追加
    logging.basicConfig(filename=log_filename, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8", filemode='a')
    print(f"日志文件: {log_filename}")

    # --- 阶段 1: 寻找媒体文件与配置文件 --- 遍历：扫描所有文件，建立媒体文件和 JSON 文件的初始列表
    print(f"--- 阶段 1: 寻找媒体文件与配置文件 ---")
    all_media_files = collect_all_files(directory, media_extensions)
    all_json_files = collect_all_files(directory, json_extensions)      
    all_json_files = set(all_json_files)  # 转为集合以便后续移除已匹配的 JSON 文件      
    print(f"扫描完成。发现 {len(all_media_files)} 个媒体文件，{len(all_json_files)} 个 JSON 文件。")

    # --- 阶段 2: 匹配媒体文件与配置文件 --- 建立配对列表
    print(f"--- 阶段 2: 匹配媒体文件与配置文件 ---")
    matched_pairs = find_matching_pairs(all_media_files, all_json_files)
    print(f"匹配完成。共匹配到 {len(matched_pairs) - list(matched_pairs.values()).count(None)} 对媒体文件与 JSON 文件。")
    
    # --- 阶段 3: 更正错误扩展名 ---
    print(f"--- 阶段 3: 更正错误扩展名 ---")
    matched_pairs = correct_ext_of_matched_pairs(matched_pairs)
    print(f"扩展名更正完成。")
    
    # --- 阶段 4: 更新元数据 ---
    print(f"--- 阶段 4: 更新元数据 ---")
    update_media_metadata_mp_mt(matched_pairs)
    
    
    print(f"元数据更新完成。")

    



if __name__ == "__main__":
    # 使用argparse解析命令行参数
    parser = argparse.ArgumentParser(description="修复媒体文件元数据")
    parser.add_argument("directory", help="需要处理的目录路径")
    args = parser.parse_args()

    repair_media_files(args.directory)