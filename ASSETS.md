# 素材说明

## 下载版保底背景

`valorant_qq_bot/assets/card-background-fallback.png` 为项目维护者在 2026-10-17 提供的 VALORANT 图片，按原文件随包提供。用于未配置背景或自定义图片失效时的保底显示，无需联网下载。相关游戏标识与美术权利归原权利人，本项目不为其另行授予许可。

## README 展示素材

`docs/images/custom-background.png` 是项目原有自定义卡片背景，来自维护者此前提供的插画及背景编辑。`shop-custom.jpg`、`history-custom.jpg` 使用该背景和虚构演示数据生成；`shop-default.jpg` 演示内置保底图。展示图不包含真实账号、授权或真实对局数据。

这些素材只用于说明外观，程序不会扫描文档目录，也不会自动把展示素材加入背景池。用户可以按 `REQUIREMENTS.md` 配置自己有权使用的图片。

演示卡片中的四张默认武器图标来自 `https://valorant-api.com/v1/weapons?language=zh-CN` 返回的公开 `displayIcon`，用于说明卡片布局；名称及价格为演示用途，未附带商品缓存。

## 英雄头像与其他资源

`valorant_qq_bot/assets/history-agents/` 是战绩卡片的本地英雄头像，来自公开 Valorant API 的英雄图像；具体来源 URL 保存在该目录的 `index.json`。相关游戏美术属于 VALORANT / Riot Games，本仓库不改变其权利归属。

仓库不附带维护者的私有随机背景池、真实商品缓存或系统字体。中文字体使用自行安装的系统字体，遵守相应字体许可。
