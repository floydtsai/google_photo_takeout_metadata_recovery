# google_photo_takeout_metadata_recovery

# 📷 Google 相册 Takeout 元数据恢复工具 (google_takeout_metafix)

这个 Python 脚本旨在解决从 Google 相册 (Google Photos) 取回相片（通过 Google Takeout 服务）后，**照片元数据（如拍摄时间、GPS 信息等）被剥离到单独 JSON 文件中**的问题。

本工具通过操作著名的 **ExifTool** 程序，将 JSON 文件中的关键元数据读取出来，并准确地恢复（写入）到对应的媒体文件（照片/视频）中。

---

单线程: goometa_recovery.py
多线程: goometa_recovery_mt.py

---

## 🚀 快速开始

### 🛠️ 依赖环境安装

要成功运行此脚本，您需要确保系统安装了 **Python 3**、**ExifTool**，以及所需的 Python 库。

#### 1. Python 及外部工具 (Windows 推荐)

如果您使用的是 Windows 系统，可以使用 `winget` 快速安装：

```bash
# 安装 Python 3
winget install Python.Python.3.12

# 安装 ExifTool (核心元数据处理工具)
winget install ExifTool
```

#### 2\. Python 扩展库

通过 `pip` 安装脚本依赖的 Python 库：

```bash
# filetype 用于准确判断文件类型，pytz 用于时区处理
pip install filetype pytz
```

### 💡 如何运行

请在命令行中导航到脚本所在目录，并使用以下命令启动：

```bash
# 格式：python 脚本名 <要处理的根目录>

# 示例: 
python goometa_recovery.py /path/to/your/takeout/root/folder

```

-----

## 💖 贡献与致谢

本项目是我学习 Python 过程中的第一个项目，可能仍存在一些问题或改进空间。欢迎任何形式的反馈、Bug 报告或代码贡献！


