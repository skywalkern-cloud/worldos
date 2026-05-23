#!/usr/bin/env python3
"""
GitHub API部署脚本 - deploy_via_api.py
使用GitHub API代替git push方式部署到main分支，触发Cloudflare Pages自动部署
"""
import os
import base64
import requests
from pathlib import Path
from datetime import datetime

# 配置
REPO_OWNER = "skywalkern-cloud"
REPO_NAME = "worldos"
BRANCH = "main"
GH_TOKEN = os.environ.get("GH_TOKEN", "")

if not GH_TOKEN:
    print("❌ 请设置 GH_TOKEN 环境变量")
    exit(1)

WORK_DIR = Path(__file__).parent.parent.resolve()
GITIGNORE_PATH = WORK_DIR / ".gitignore"

# 跳过特殊文件
SKIP_FILES = {".DS_Store", "Thumbs.db"}

def load_gitignore():
    """加载.gitignore规则"""
    patterns = []
    if GITIGNORE_PATH.exists():
        with open(GITIGNORE_PATH) as f:
            patterns = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return patterns

def should_skip(file_path: Path, gitignore_patterns: list) -> bool:
    """检查文件是否应该被跳过（基于.gitignore规则）"""
    str_path = str(file_path)
    
    # 检查文件名
    if file_path.name in SKIP_FILES:
        return True
    
    # 检查.gitignore模式
    for pattern in gitignore_patterns:
        # 目录模式
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/")
            if f"/{dir_name}/" in str_path or str_path.endswith(f"/{dir_name}"):
                return True
        # 通配符模式
        elif "*" in pattern:
            import fnmatch
            if fnmatch.fnmatch(str_path, pattern) or fnmatch.fnmatch(file_path.name, pattern):
                return True
        # 精确匹配
        else:
            if pattern in str_path:
                return True
    
    return False

def get_file_sha(repo_path):
    """获取文件的SHA用于更新"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{repo_path}"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    params = {"ref": BRANCH}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def upload_file(file_path: Path, repo_path: str, gitignore_patterns: list) -> bool:
    """上传单个文件到GitHub"""
    # 检查是否应该跳过
    if should_skip(file_path, gitignore_patterns):
        print(f"  ⏭️ 跳过: {repo_path}")
        return True
    
    # 使用二进制模式读取所有文件
    try:
        with open(file_path, "rb") as f:
            content = f.read()
    except Exception as e:
        print(f"  ❌ 读取失败: {repo_path} - {e}")
        return False
    
    b64_content = base64.b64encode(content).decode("utf-8")
    
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{repo_path}"
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "message": f"Deploy: {file_path.name}",
        "content": b64_content,
        "branch": BRANCH
    }
    
    sha = get_file_sha(repo_path)
    if sha:
        data["sha"] = sha
    
    r = requests.put(url, headers=headers, json=data)
    if r.status_code in [200, 201]:
        print(f"  ✅ {repo_path}")
        return True
    else:
        try:
            err_msg = r.json().get("message", r.text)
        except:
            err_msg = r.text
        print(f"  ❌ {repo_path}: {r.status_code} - {err_msg}")
        return False

def get_all_files(src_dir: Path, exclude_dirs: set) -> list:
    """递归获取所有文件"""
    files = []
    for item in src_dir.rglob("*"):
        if item.is_file():
            # 排除指定目录
            if any(ex in item.parts for ex in exclude_dirs):
                continue
            rel_path = item.relative_to(src_dir)
            files.append((item, str(rel_path)))
    return files

def main():
    print("=" * 60)
    print("GitHub API 部署脚本 - WorldOS")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 验证仓库存在
    headers = {"Authorization": f"token {GH_TOKEN}"}
    r = requests.get(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}", headers=headers)
    if r.status_code == 404:
        print(f"❌ 仓库不存在: {REPO_OWNER}/{REPO_NAME}")
        print("请先在GitHub上创建仓库，或检查仓库名是否正确")
        return
    elif r.status_code != 200:
        print(f"❌ GitHub API错误: {r.status_code}")
        return
    
    print(f"✅ 仓库存在: {REPO_OWNER}/{REPO_NAME}")
    
    gitignore_patterns = load_gitignore()
    # 排除对 dist 目录的限制（dist 是构建输出，需要上传）
    gitignore_patterns = [p for p in gitignore_patterns if p not in ("dist", "dist/", "dist-ssr")]
    print(f"已加载 {len(gitignore_patterns)} 条.gitignore规则（已移除dist/dist-ssr）")
    
    # 排除目录（这些目录不会上传到GitHub）
    exclude_dirs = {"node_modules", ".git", "dist-ssr", ".github", "gh-pages", ".vercel"}
    
    files = get_all_files(WORK_DIR, exclude_dirs)
    print(f"\n待上传: {len(files)} 个文件")
    
    success = 0
    failed = 0
    
    for full_path, repo_path in files:
        if upload_file(full_path, repo_path, gitignore_patterns):
            success += 1
        else:
            failed += 1
    
    print("\n" + "=" * 60)
    if failed == 0:
        print(f"✅ 部署完成! 成功: {success}")
        print("💡 Cloudflare Pages 将自动检测到main分支更新并部署")
    else:
        print(f"⚠️ 部分失败: 成功 {success}, 失败 {failed}")
    print("=" * 60)

if __name__ == "__main__":
    main()