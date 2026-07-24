# 发视频前 · GitHub 发布检查清单

目标：宣传小u + 定制能力；公开仓库只有小u 的 Win/Mac 下载包；不出现鸡蛋壳；不出现真人自拍；暂时藏起「星光学习岛」。

## 1. 隐藏「星光学习岛」（仓库名 `-`）

当前公开仓库：https://github.com/1766054554-pixel/-  
（主页仓库列表里那个叫 `-` 的，就是星光学习岛。）

请你本机执行（需已登录 `gh`）：

```bash
gh auth login   # 若尚未登录
gh repo edit 1766054554-pixel/- --visibility private
```

网页操作也可以：

1. 打开 https://github.com/1766054554-pixel/-/settings
2. 滚到 Danger Zone → **Change repository visibility** → Private
3. 再打开 Settings → Pages → 若仍开着 GitHub Pages，先 Disable（避免 `https://1766054554-pixel.github.io/-/` 还能打开）

改完后个人主页应只剩 `XiaoU-Desktop-Character` 一个公开项目。

## 2. 更新仓库「简介 / About」

建议描述（About 栏，≤ 350 字）：

```text
小u：会在桌面散步、换装、对白的像素桌宠｜Win/macOS 一键下载｜可付费定制情侣双人桌宠｜开源引擎 + Codex Skill
```

建议 Topics：

```text
desktop-pet pixel-art macos windows pyside6 open-source customizable
```

Homepage 可填 Releases 页：

```text
https://github.com/1766054554-pixel/XiaoU-Desktop-Character/releases
```

命令示例：

```bash
gh repo edit 1766054554-pixel/XiaoU-Desktop-Character \
  --description "小u：会在桌面散步、换装、对白的像素桌宠｜Win/macOS 一键下载｜可付费定制情侣双人桌宠｜开源引擎 + Codex Skill" \
  --homepage "https://github.com/1766054554-pixel/XiaoU-Desktop-Character/releases" \
  --add-topic desktop-pet --add-topic pixel-art --add-topic macos --add-topic windows --add-topic pyside6 --add-topic open-source
```

## 3. 推送最新公开代码（含双人互动）

本地已有 `peer.py` 等双人能力，但 GitHub 上旧树可能还缺这些文件。请把**公开安全**的更新推上去：

- ✅ `src/`（含 `peer.py`、`branding.py`）、`tests/`、`examples/`、`skills/`、`docs/`、`assets/`（演示小u）
- ✅ README / `docs/宣传文案.md` / Skill
- ❌ 不要保留公开 `ROADMAP.md`（已移除）
- ❌ 不要推 `user_assets/`（含真人照、鸡蛋壳图标等私有文件）
- ❌ 不要推 `Eggdk.app`、`dist/Eggdk*`、`assets/icons/eggdk*`（已挪到 `user_assets/icons/`）
- ❌ 不要把定制角色的 Release 资产传上去

本地已备好干净 Mac 包（自检无鸡蛋壳、无真人 selfie）：

```text
dist/XiaoU-macOS-arm64.zip
```

Windows 包请用 GitHub Actions 打（见仓库 `.github/workflows/release.yml`），或本机 Windows 跑 `.\scripts\build.ps1`。

推送后打 tag 触发自动双平台打包：

```bash
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

Actions 会产出并发布：

- `XiaoU-Windows-x64.zip`
- `XiaoU-macOS-arm64.zip`

确认 Release 里**只有**这两份，没有 Eggdk。

## 4. 公开包自检

解压后确认：

- [ ] 只有小u，没有鸡蛋壳字样 / 素材
- [ ] 没有 `user_assets/selfie.png`（真人照）
- [ ] 菜单「自拍」最多播像素动作，不弹出真人照片
- [ ] Skill 目录 `skills/make-cross-platform-desktop-character/` 在仓库里可见

## 5. 宣传文案

见 [宣传文案.md](./宣传文案.md)。
