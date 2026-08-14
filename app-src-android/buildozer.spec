[app]

# 应用标题
title = MC自动中文化_普通版

# 包名
package.name = mcchinesefeature

# 域名
package.domain = org.example.mcchinesefeature

# 源码目录
source.dir = .

# 包含的扩展名
source.include_exts = py,png,jpg,kv,atlas,yml,json,txt,ttf,ttc,otf

# 版本号
version = 1.0.0

# 依赖列表（确保打包进 APK）
# 使用 kivy==2.2.1 让 python-for-android 内置 recipe 从源码编译，确保 config.pxi 等头文件完整
# python3==3.10.15 强制 Android 目标解释器为 3.10，避免 p4a 默认拉取 3.14 导致 cgi 缺失
requirements = python3==3.10.15,hostpython3==3.10.15,kivy==2.2.1,pyjnius,deep-translator,openai,pyyaml,requests,urllib3,charset_normalizer,certifi,idna,httpx,httpcore,h11,sniffio,anyio,typing_extensions,tqdm,distro

# 安卓权限
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

# 屏幕方向
orientation = portrait

# 不全屏，保留状态栏
fullscreen = 0

# Android API 级别
android.api = 33

# 最低 SDK（Android 5.0 起可安装）
android.minapi = 21

# 目标 SDK
android.sdk = 33

# NDK API
android.ndk_api = 21

# 构建架构（先构建 arm64，构建成功后可再切到 armeabi-v7a）
android.archs = arm64-v8a

# 自动接受 Android SDK 许可协议（非交互环境必需）
android.accept_sdk_license = True

# 图标（可选）
# icon.filename = icon.png

[buildozer]

# 不提示 root 警告
warn_on_root = 0

# 日志级别（0=最详细，方便 CI 排障）
log_level = 0

# 构建目录
build_dir = ./.buildozer

# bin 目录
bin_dir = ./bin
