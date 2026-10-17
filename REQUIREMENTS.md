# 安装、运行与配置

[返回项目介绍](README.md)

本文件是部署使用指南；Python 依赖版本以 `pyproject.toml` 为准。所有命令在仓库根目录执行。

## 环境要求

- Python 3.10+，建议 Linux 服务器，macOS 也可运行。
- 兼容 OneBot V11 的 QQ 接入端，需自行安装、登录和配置。
- 可访问游戏上游接口的网络；首次绑定需要本人扫码授权。
- 图片卡片需要中文字体。Linux 可安装 Noto CJK 或 AR PL UMing，也可指定字体文件；没有可用字体时回复文字。

## 安装与首次启动

```sh
git clone https://github.com/qwqsyyl/Valorant-bot.git
cd Valorant-bot
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[auth,bot]'
mkdir -p data
chmod 700 data
cp deploy/bot.env.example data/bot.env
chmod 600 data/bot.env
```

Linux 首次安装时生成加密密钥：

```sh
.venv/bin/python -m valorant_qq_bot.setup_credentials
```

密钥写入 `data/core.env`，已有文件不会被覆盖。密钥和加密凭据必须一起备份。macOS 默认使用系统钥匙串，可跳过密钥生成。

编辑 `data/bot.env`，填写自己的机器人 QQ、群号与 OneBot 访问令牌；不要把真实配置、数据库、密钥、二维码、日志或凭据提交到 GitHub。

| 配置项 | 默认值 / 示例 | 用途 |
| --- | --- | --- |
| `VALORANT_BOT_QQ` | 自己的机器人 QQ | 接收命令的机器人身份 |
| `VALORANT_BOT_HOST` | `127.0.0.1` | 监听地址 |
| `VALORANT_GROUP_ID` | 自己的群号 | 使用机器人的目标群 |
| `ONEBOT_ACCESS_TOKEN` | 自行生成 | 与 QQ 接入端保持一致 |
| `VALORANT_CONFIRMED_RESET_HOUR` | `8` | 北京时间每日商店切换小时 |
| `VALORANT_CARD_FONT` | 自动探测系统字体 | 可指定中文 `.ttf` / `.ttc` 字体的绝对路径 |

将 QQ 接入端反向 WebSocket 地址设为 `ws://127.0.0.1:8080/onebot/v11/ws`，令牌与 `ONEBOT_ACCESS_TOKEN` 一致。接入端位于容器或另一台主机时，按实际网络设置监听地址和连接地址，并限制网络访问范围。

```sh
sh scripts/start-bot
```

在群内发送 `瓦绑定`，按提示本人扫码，再发送 `每日商店` 或 `战绩`。

## 自定义背景

背景模块只读取部署者自己的本地图片，无需背景接口、网络账号或抓图服务。配置写入 `data/bot.env`，图片建议放在 `data/backgrounds/`，不需要替换程序文件。

### 模式与优先级

| 模式 | 配置值 | 行为 |
| --- | --- | --- |
| 内置保底 | `default` | 直接使用随包提供的 VALORANT 背景，忽略自定义文件和目录 |
| 固定单图 | `fixed` | 使用指定图片；缺失或无效则回退内置图 |
| 本地随机 | `random` | 每次生成卡片重新选图，多张可用图片时尽量避免紧邻重复 |

未设置模式时自动兼容旧配置：有目录就随机、有单图就固定、都没有就用内置图。

随机模式的回退顺序：**图片池中可用图片 → 同一配置组指定的固定单图 → 内置保底图 → 纯色背景**。如果选中的图片在渲染前被删除或解码失败，会继续尝试其他候选。

商店和战绩共用公共配置；某种卡片只要设置了任意非空的专用背景项，就完整使用该专用配置组，不再逐项混用公共项。未设置专用配置时才沿用公共配置。设为 `default` 可让其中一种卡片单独恢复内置图。

### 公共配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `VALORANT_CARD_BACKGROUND_MODE` | 自动判断 | `default` / `fixed` / `random` |
| `VALORANT_CARD_BACKGROUND` | 空 | 固定图片路径；随机模式也可用作备用单图 |
| `VALORANT_CARD_BACKGROUND_DIR` | 空 | 随机图片目录，只读取当前层 |
| `VALORANT_CARD_PANEL_ALPHA` | 商店随机模式 96，其他 206 | 商店面板不透明度，整数 0–255，越小越透明 |
| `VALORANT_HISTORY_PANEL_ALPHA` | `218` | 战绩面板不透明度，整数 0–255 |
| `VALORANT_CARD_WEAPON_ALPHA` | 商店随机模式 56，其他 228 | 商店商品区不透明度，整数 0–255 |

专用项分别为 `VALORANT_SHOP_BACKGROUND_MODE`、`VALORANT_SHOP_BACKGROUND`、`VALORANT_SHOP_BACKGROUND_DIR`，以及 `VALORANT_HISTORY_BACKGROUND_MODE`、`VALORANT_HISTORY_BACKGROUND`、`VALORANT_HISTORY_BACKGROUND_DIR`；取值规则与公共项相同。

### 示例一：使用内置保底图

不设置任何背景项即可。也可明确写入：

```sh
VALORANT_CARD_BACKGROUND_MODE=default
```

内置文件是 `valorant_qq_bot/assets/card-background-fallback.png`；README 中的自定义背景只是展示素材，不会自动参与运行时选图。

### 示例二：固定一张自己的背景

将图片放入 `data/backgrounds/my-background.jpg`，写入：

```sh
VALORANT_CARD_BACKGROUND_MODE=fixed
VALORANT_CARD_BACKGROUND=data/backgrounds/my-background.jpg
```

### 示例三：随机背景池

将多张图片放入 `data/backgrounds/pool/`，写入：

```sh
VALORANT_CARD_BACKGROUND_MODE=random
VALORANT_CARD_BACKGROUND_DIR=data/backgrounds/pool
# 可选：图片池不可用时先尝试这张图片
VALORANT_CARD_BACKGROUND=data/backgrounds/my-background.jpg
```

### 示例四：商店随机，战绩固定

```sh
VALORANT_SHOP_BACKGROUND_MODE=random
VALORANT_SHOP_BACKGROUND_DIR=data/backgrounds/shop
VALORANT_HISTORY_BACKGROUND_MODE=fixed
VALORANT_HISTORY_BACKGROUND=data/backgrounds/history.jpg
```

希望战绩单独使用内置图时，改为 `VALORANT_HISTORY_BACKGROUND_MODE=default`。

### 图片要求与生效方式

- 支持内容和扩展名一致的 JPG / JPEG / PNG；扩展名不区分大小写，不读取符号链接或子目录。
- 支持横图、竖图和方图，自动等比缩放后裁剪，避免拉伸。保留图片的 EXIF 方向，但不把原图元数据写入卡片。
- 推荐商店使用 1920×1080 左右的横图，战绩使用竖图；人物和关键信息尽量避免放在边缘，文字区使用对比清楚的背景。
- 单张不超过 20 MiB、总像素不超过 800 万；随机池每次最多检查 500 个目录项，纳入最多 50 张有效图片、累计不超过 20 MiB。建议自行精选小型图片池。
- 相对路径相对于启动目录；项目启动脚本和示例服务均以仓库根目录运行。也支持绝对路径及 `~`。路径含空格时在配置中加引号。
- 修改 `data/bot.env` 后重启机器人生效；已启用目录中的图片增删替换在下次生成卡片时读取，无需重启。
- 连续不重复状态按卡片类型和目录隔离，只在当前进程内保存，重启会清空。随机池只有一张图时允许重复。
- 坏图、无权限、空目录和非法模式会记录回退日志，背景问题不会要求重新绑定游戏账号。

## 账号管理与命令行

| 命令 | 用途 |
| --- | --- |
| `瓦绑定 重新授权` | 登录失效后重新扫码 |
| `取消绑定` | 取消尚未完成的扫码任务 |
| `商店解绑` | 解除当前群绑定 |

其余常用指令见 [README](README.md#常用指令)。独立命令行首次同样需要本人扫码：

```sh
sh scripts/core login
sh scripts/core login --channel wechat
sh scripts/core shop
sh scripts/core refresh
sh scripts/core wishes
```

命令行默认使用独立绑定标识，与群内身份分开。`history_cli`、`friend_cli`、`maintenance_cli` 使用显式群号和用户标识，可通过 `.venv/bin/python -m valorant_qq_bot.模块名 --help` 查看参数。

## Linux 后台运行

示例用户级 systemd 服务默认安装目录为 `~/valorant-qq-bot`。克隆命令创建的是 `Valorant-bot`，请先修改 `deploy/valorant-shop.service` 中的工作目录、配置文件与解释器路径，使其对应自己的实际安装目录。

`data/core.env` 和 `data/bot.env` 准备好后执行：

```sh
mkdir -p ~/.config/systemd/user
cp deploy/valorant-shop.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now valorant-shop.service
systemctl --user status valorant-shop.service
```

配置变更后使用 `systemctl --user restart valorant-shop.service` 重启。若需退出登录后继续运行，可由管理员为服务用户启用 linger。

## 升级与数据保留

运行配置、数据库、背景池和缓存均放在自己的 `data/` 目录，该目录不进入 Git。升级前备份数据及配套密钥，检查自己的代码改动，再拉取公开仓库并更新依赖；服务重启由部署者自行执行。不要重新生成密钥覆盖已有密钥，不要用旧凭据覆盖仍有效的凭据。

## 常见问题

| 现象 | 排查方式 |
| --- | --- |
| 自定义背景没有出现 | 检查模式、专用配置是否覆盖公共配置、路径和读取权限；检查回退日志与图片限制 |
| 图片人物被裁切 | 卡片尺寸不同，自动裁剪范围也不同；更换构图，战绩优先竖图 |
| 只收到文字 | 先确认中文字体路径可读；字体或其他绘图失败会回退文字，背景读取失败本身会先回退图片 |
| 商店数据复用 | 商店按北京时间 08:00 切换周期，成功数据当天复用，失败由核心调度重试 |
| 提示重新扫码 | 登录维护每五分钟检查到期账号并通过 WT 更新，上游授权失效仍需本人重新扫码 |
| 好友查询受限 | 使用发起人的授权和实际好友关系；上游不可见或非国服端游数据不保证可查 |

素材说明见 [ASSETS.md](ASSETS.md)，公开版本变更见 [VERSION_HISTORY.md](VERSION_HISTORY.md)。
