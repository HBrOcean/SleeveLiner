# 如何用 Git 把项目发布到 GitHub

> 以本项目 SleeveLiner 为例，从零到发布 + 发版本，一步步来。

---

## 0. 一次性准备（只做一次）

**① 安装 Git**

- Windows：到 https://git-scm.com/download/win 下载安装
- macOS：终端运行 `xcode-select --install`（或 `brew install git`）
- Linux：`sudo apt install git`

装好后在终端验证：

```bash
git --version
```

**② 配置身份**（提交记录里会显示）

```bash
git config --global user.name "HBrOcean"
git config --global user.email "你的GitHub邮箱"
```

---

## 1. 在 GitHub 上新建一个空仓库

1. 打开 GitHub，点右上角 **+ → New repository**
2. 仓库名填 `SleeveLiner`
3. **不要**勾选 “Add a README file” / “Add .gitignore” / “Choose a license”
   （因为本地项目里已经有这些文件了，勾了会冲突）
4. 点 **Create repository**，记下仓库地址：
   `https://github.com/HBrOcean/SleeveLiner.git`

---

## 2. 把项目文件夹变成 Git 仓库

在终端进入项目文件夹（就是放 `sleeve_liner.py` 等的那个文件夹）：

```bash
cd 你的路径/SleeveLiner

git init                              # 初始化：这个文件夹变成 Git 仓库
git add .                             # 把所有文件加入暂存区
git commit -m "feat: SleeveLiner v2.3" # 首次提交
git branch -M main                    # 主分支命名为 main
```

> `.gitignore` 已经配好，`output/`、缓存文件等不会被提交，放心 `git add .`。
>
> 可以用 `git status` 随时查看当前状态。

---

## 3. 关联远程仓库并推送

```bash
git remote add origin https://github.com/HBrOcean/SleeveLiner.git
git push -u origin main
```

首次推送会要求登录。**注意：GitHub 早已不支持用密码推送**，二选一：

### 方式 A：HTTPS + 访问令牌（Token）

1. GitHub → 右上角头像 → **Settings** → 左侧最下 **Developer settings**
   → **Personal access tokens** → **Tokens (classic)** → **Generate new token**
2. 勾选 `repo` 权限，生成后**复制保存**（只显示一次）
3. 推送时：用户名填 GitHub 用户名，密码处**粘贴这个 token**

### 方式 B：SSH（推荐，一次配置长期免密）

```bash
ssh-keygen -t ed25519 -C "你的GitHub邮箱"   # 一路回车即可
cat ~/.ssh/id_ed25519.pub                    # 复制输出的公钥
```

把公钥粘贴到 GitHub → **Settings → SSH and GPG keys → New SSH key**，然后：

```bash
git remote set-url origin git@github.com:HBrOcean/SleeveLiner.git
git push -u origin main
```

---

## 4. 日常更新流程（最常用）

以后每次改了代码，就三步：

```bash
git add .
git commit -m "说明这次改了什么"
git push
```

---

## 5. 发版本（自动构建 + 自动发 Release）

本项目配了 GitHub Actions。**只要打一个 tag 并推送**，就会自动：

- 在 3 个平台（Linux / Windows / macOS）用 PyInstaller 打包出可执行文件
- 创建带附件的 Release 页面

```bash
git tag v2.3              # 打标签（版本号）
git push origin v2.3      # 推送标签，触发 Actions
```

几十秒后，去仓库的 **Releases** 页面就能看到新版本 + 可下载的附件了 🎉

---

## 6. 常见问题

| 报错 / 情况 | 解决办法 |
|---|---|
| `remote origin already exists` | 先 `git remote rm origin` 再重新 `git remote add` |
| 推送时一直要密码 | 用 Token 或 SSH（见第 3 步），不能用账号密码 |
| 想改上次的提交信息 | `git commit --amend -m "新的说明"` |
| 误把文件加进暂存区 | `git restore --staged 文件名` |
| 想知道改了哪些文件 | `git status` |
| 想看提交历史 | `git log --oneline` |
| 想撤销未提交的改动 | `git restore 文件名` |

---

## 附：最精简的完整流程

```bash
cd 你的项目文件夹
git init
git add .
git commit -m "feat: SleeveLiner v2.3"
git branch -M main
git remote add origin https://github.com/HBrOcean/SleeveLiner.git
git push -u origin main

# 发版本
git tag v2.3
git push origin v2.3
```
