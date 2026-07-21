# 小u桌面角色 | XiaoU Desktop Character

[![Tests](https://github.com/1766054554-pixel/XiaoU-Desktop-Character/actions/workflows/tests.yml/badge.svg)](https://github.com/1766054554-pixel/XiaoU-Desktop-Character/actions/workflows/tests.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB)](https://www.python.org/)
[![Code License: MIT](https://img.shields.io/badge/code-MIT-1f2937)](LICENSE)
[![Pixel Art: CC BY 4.0](https://img.shields.io/badge/pixel_art-CC_BY_4.0-d9485f)](ASSETS_LICENSE.md)

把一张人物图片，变成一个会在桌面散步、困了就睡、摸鱼会回话、偶尔还要换新衣服的小u。

她不是贴在屏幕上的静态图片：她有完整动作、状态和对白，会在 **Windows 与 macOS** 上持续显示；这个仓库也保留了“从一张图片到可运行原创角色”的完整 Agent 制作流程。

![小u说话与星星眼](docs/media/xiaou-speech.png)

> 你忙你的，小u负责可爱。

想给男朋友或女朋友做一份真的会动的礼物，可以从这里开始；想研究跨平台透明窗口、像素动作系统和 Agent 工作流，也可以直接二次开发。

## 直接体验

从 [Releases](https://github.com/1766054554-pixel/XiaoU-Desktop-Character/releases/latest) 下载对应系统的压缩包：

| 系统 | 文件 | 打开方式 |
|---|---|---|
| Windows 10/11 x64 | `XiaoU-Windows-x64.zip` | 完整解压后双击 `XiaoU/XiaoU.exe` |
| macOS Apple Silicon | `XiaoU-macOS-arm64.zip` | 解压后首次右键点击 `XiaoU.app`，选择“打开” |

小u默认保持在其他窗口上方。右键角色可打开动作面板、查看状态、调整大小、暂停移动、控制说话或退出。

## 现在能做什么

- 在 Windows 与 macOS 桌面到处散步，切换软件也不会突然消失；
- 会嘟嘴、大笑、Wink、星星眼、认真思考，也会无聊、饥饿、犯困和生气；
- 会吃蛋糕、啃汉堡、玩手机、坐椅子摸鱼、拍照，还能陪柯基玩；
- 有 18 套真正换款式的造型，不是简单换个颜色；
- 会根据当前动作随机说话，也能一键关闭说话；
- 有默契、精力、无聊和饥饿状态，变化节奏不会催着你一直点击；
- 支持动作面板、尺寸调整、暂停移动、隐藏与退出；
- 原始照片、参考图和制作草稿只保存在本地 `user_assets/`；
- 角色形象与走路动画必须经过两次人工确认后才能打包；
- 可用本地互动包增加“发送啵啵”“要抱抱”等动作入口和专属对白，不改变公开默认内容；

### 动作多到可以慢慢翻

从走路、睡觉、吃东西到相机、手机、柯基和各种表情，全部动作都来自同一个小u原型，不用通用模板脸冒充一致性。

![小u完整动作与表情合集](docs/media/xiaou-action-catalog.png)

### 今天穿哪套？

海军服是主造型，换装则保留了丝绸礼裙、甜酷街头、软萌兔子装、日常裙装和休闲套装等不同轮廓。

![小u服装造型合集](docs/media/xiaou-outfits.png)

### 面板不是藏起来的彩蛋

打开菜单就能看到状态、说话开关、表情与互动、吃东西、日常动作、随机换装和尺寸控制。

![小u状态与动作菜单](docs/media/xiaou-menu.png)

![小u走路预览](docs/media/xiaou-walk.gif)

## 用一张图制作原创角色

仓库内提供可安装的 Codex Skill：

```text
skills/make-cross-platform-desktop-character/
```

在 Codex 中使用：

```text
Use $make-cross-platform-desktop-character to turn my character image into a tested Windows and macOS desktop character.
```

Skill 会依次完成环境检查、原图特征分析、标准角色候选、动作素材、走路预览、两次人工确认、素材一致性检查、程序接入、测试与双平台打包。未经确认不会批量生成动作，也不会把原图上传到 GitHub。

完整入口见 [Skill 说明](skills/make-cross-platform-desktop-character/SKILL.md) 与 [Agent 执行指南](agent-guide/AGENT_GUIDE.md)。

## 本地开发

需要 Python 3.12。

### macOS

```bash
./scripts/check_environment.sh
./scripts/setup_environment.sh
./scripts/run_macos.sh
./scripts/test_macos.sh
./scripts/build_macos.sh
```

构建结果：`dist/XiaoU.app`

### Windows

```powershell
.\scripts\check_environment.ps1
.\scripts\setup_environment.ps1
.\scripts\run.ps1
.\scripts\test.ps1
.\scripts\build.ps1
```

构建结果：`dist\XiaoU\XiaoU.exe`

## 付费定制

如果不想自己整理动作素材，可以通过 [Custom Character Issue](https://github.com/1766054554-pixel/XiaoU-Desktop-Character/issues/new?template=custom-character.yml) 联系作者讨论付费定制。

定制内容可以包括原创像素角色、指定动作、服装、道具和专属对白包。情侣礼物场景可按需加入“发送啵啵”“要抱抱”等互动，但这些内容只进入客户本地交付包，不是另一个公开版本。

请勿在公开 Issue 上传真人照片、联系方式或其他私人素材。Issue 只用于确认系统、画风与动作范围，正式素材通过双方确认的私密渠道处理。

## 项目来源与贡献边界

本项目基于 [Taylor154/OnePic-Desktop-Pet](https://github.com/Taylor154/OnePic-Desktop-Pet) 的 MIT 代码进行二次开发。原项目并非本仓库作者从零创建；本项目新增和完善了 macOS 支持、跨桌面空间显示、公开像素角色、动作与对白系统、素材确认门禁、隐私检查、双平台打包、自动测试和可复用制作 Skill。

详细致谢与修改范围见 [NOTICE.md](NOTICE.md)。

## 授权

- 程序代码与文档：MIT License；
- 海军服小u像素动作、造型与图标：CC BY 4.0，署名“七月在野-yrrr (@1766054554-pixel)”；
- 用户放入 `user_assets/` 的照片与私人素材：不属于公开仓库内容。

详见 [ASSETS_LICENSE.md](ASSETS_LICENSE.md)。

## 路线图

下一阶段计划支持情侣双方各自拥有一个定制角色，并在同一桌面上靠近、碰面或由用户选择后触发同步动作与双方对白。当前版本仍是经过完整验证的单角色版本，设计草案见 [ROADMAP.md](ROADMAP.md)。
