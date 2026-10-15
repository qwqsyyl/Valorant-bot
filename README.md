# Valorant-bot

国服无畏契约每日商店、皮肤愿望提醒及最近战绩 QQ 机器人。

这是精简运行版：保留真实 QQ／微信游戏账号授权、加密凭据保存、WT 登录维护、每日商店采集、群友与游戏好友战绩、图片卡片和文字回退。版本及源提交见 `VERSION.json`。

## 环境

- Python 3.10+；建议 Linux 服务器，macOS 也可运行。
- 兼容 OneBot V11 的 QQ 接入端，需自行安装、登录并配置。
- 可访问游戏上游接口的网络。首次绑定需本人扫码授权。
- 图片卡片需要中文字体；未配置时回退文字。Linux 可安装 Noto CJK 或 AR PL UMing，或设置 `VALORANT_CARD_FONT`。

## 安装

在仓库根目录执行：

```sh
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

密钥写入 `data/core.env`；已有文件不会被覆盖。密钥和加密凭据必须一起备份。macOS 默认使用系统钥匙串，可跳过密钥生成。

编辑 `data/bot.env`，填写机器人 QQ、配置群号和 OneBot 访问令牌。不得将真实配置、数据库、密钥、二维码、日志或凭据提交到 GitHub。

将 QQ 接入端的反向 WebSocket 地址设为 `ws://127.0.0.1:8080/onebot/v11/ws`，令牌与 `ONEBOT_ACCESS_TOKEN` 一致。接入端位于容器或另一台主机时，需按实际网络设置 `VALORANT_BOT_HOST` 和连接地址，限制网络访问范围。

启动：

```sh
sh scripts/start-bot
```

## 群内命令

| 命令 | 功能 |
| --- | --- |
| `瓦绑定` / `瓦绑定 QQ` / `瓦绑定 微信` | 扫码绑定游戏账号 |
| `瓦绑定 重新授权` | 登录失效后重新扫码 |
| `取消绑定` | 取消尚未完成的扫码任务 |
| `商店解绑` | 解除当前群绑定 |
| `每日商店` / `每日商店 @群友` | 查询本人或本群已绑定成员的商店 |
| `战绩` / `战绩 @群友` | 查询最近 5 场已结束的国服端游对局 |
| `游戏好友 [关键词]` | 查询游戏好友列表及选择码 |
| `好友战绩 选择码` | 查询对应好友最近战绩 |
| `皮肤提醒 完整商品名称` | 添加皮肤愿望 |
| `愿望单` / `取消提醒 编号` | 管理订阅 |
| `商店帮助` / `战绩帮助` / `游戏好友帮助` | 查看帮助 |

同群已绑定成员可互查商店和战绩，回复发在群内；游戏好友查询使用发起人的授权和好友关系，目标无需在群或绑定。请在绑定前了解这一行为。

## 独立命令行

无需连接 QQ 即可使用核心入口，首次需要扫码：

```sh
sh scripts/core login
sh scripts/core login --channel wechat
sh scripts/core shop
sh scripts/core refresh
sh scripts/core wishes
```

命令行默认使用独立绑定标识，与群内身份分开。`history_cli`、`friend_cli`、`maintenance_cli` 使用显式群号和用户标识；参数见各模块的 `--help`。

## Linux 后台运行

`deploy/valorant-shop.service` 使用用户级 systemd，默认安装目录为 `~/valorant-qq-bot`。若目录不同，请修改该文件中的路径。准备 `data/core.env` 和 `data/bot.env` 后安装：

```sh
mkdir -p ~/.config/systemd/user
cp deploy/valorant-shop.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now valorant-shop.service
systemctl --user status valorant-shop.service
```

若需退出登录后继续运行，可由管理员为服务用户启用 linger。运行数据保存在 `data/`；升级保留该目录，禁止重新生成密钥覆盖已有密钥。

## 运行边界

商店按北京时间 08:00 切换周期，成功数据全天复用，失败后按核心调度重试。登录维护每五分钟检查到期账号，使用 WT 更新；不承诺永久免扫码，上游失效时仍可能需要重新授权。非国服端游战绩不在范围内。

精简版使用常规登录维护，不包含研究观察、实验授权入口、自动化测试、开发计划及现场测试资料。完整开发和测试在独立开发仓库维护。外部 QQ 接入端、字体及运行时背景池需自行配置；内置素材说明见 `ASSETS.md`。
