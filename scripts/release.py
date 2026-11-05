#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release.py — 发版自动化（v2.7.0）。

一键完成：打包 → 双校验（selftest + _check_docs 含 --zip）→ Git Data API 推送
（blob→tree→commit→PATCH ref，绕过 git push 网络限制）→ 建/更新 GitHub Release
→ 上传 zip 附件 → 上传/更新 SHA256SUMS.txt。

用法（在技能根目录执行）：
  python scripts/release.py --version 2.7.0 \
      --commit-msg "v2.7.0: gate_verify 机防+瘦身+失败案例" \
      --release-title "v2.7.0 — 交付关卡机防化" \
      --release-body-file release-body.md

前置：本地仓库目录与远程 main 的差异即待推送内容（全量 diff，无需 git status）。
依赖：git（credential fill 取 token）、python 标准库。仓库 Owner 用 --owner 或环境变量 RFE_GH_OWNER。
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
UP = "https://uploads.github.com"
NAME = SKILL_ROOT.name


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def gh_token() -> str:
    out = sh(["git", "credential", "fill"],
             input="protocol=https\nhost=github.com\n\n").stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    sys.exit("❌ 取不到 GitHub token（git credential fill）")


def api(req: urllib.request.Request):
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def H(tok, extra=None):
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
         "User-Agent": f"release-{NAME}"}
    if extra:
        h.update(extra)
    return h


def walk_local(root: Path):
    skip_dirs = {".git", "dist", "__pycache__", "kb_local", "node_modules"}
    out = {}
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        if any(part in skip_dirs or part.startswith(".kb") for part in f.parts[:-1]):
            continue
        if f.name.endswith(".bak") or ".bak-" in f.name:
            continue
        h = sh(["git", "hash-object", "--stdin"], stdin=open(f, "rb"),
               cwd=str(root)).stdout.strip()
        out[rel] = h
    return out


def preflight():
    print("== 预检：selftest + 文档一致性 ==")
    for cmd in (["python", "scripts/selftest.py"],
                ["python", "_check_docs.py"]):
        r = sh(cmd, cwd=str(SKILL_ROOT))
        tail = (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else "?"
        print(f"  {'$' if r.returncode else '✔'} {' '.join(cmd[1:])} → {tail}")
        if r.returncode:
            sys.exit(f"❌ 预检失败：{' '.join(cmd)}（先修复再发版）")


def push(tok, owner, commit_msg):
    repo = NAME
    st, ref = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/git/ref/heads/main", headers=H(tok)))
    if st != 200:
        sys.exit(f"❌ 取远程 ref 失败 {st}: {ref}")
    head = ref["object"]["sha"]
    st, c = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/git/commits/{head}", headers=H(tok)))
    base_tree = c["tree"]["sha"]
    local = walk_local(SKILL_ROOT)
    st, tr = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/git/trees/{base_tree}?recursive=1", headers=H(tok)))
    remote = {e["path"]: e["sha"] for e in tr["tree"] if e["type"] == "blob"}
    changed = [p for p, h in local.items() if remote.get(p) != h]
    deleted = [p for p in remote if p not in local and not p.startswith("dist/")]
    print(f"== 推送：远程 HEAD={head[:8]}，改/增 {len(changed)}，删 {len(deleted)} ==")
    if not changed and not deleted:
        return head
    entries = []
    for p in changed:
        data = (SKILL_ROOT / p).read_bytes()
        st, blob = api(urllib.request.Request(
            f"{API}/repos/{owner}/{repo}/git/blobs",
            headers=H(tok, {"Content-Type": "application/json"}),
            data=json.dumps({"content": base64.b64encode(data).decode(),
                             "encoding": "base64"}).encode(), method="POST"))
        if st != 201:
            sys.exit(f"❌ blob {p}: {st} {blob}")
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    for p in deleted:
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": None})
    st, tree = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/git/trees",
        headers=H(tok, {"Content-Type": "application/json"}),
        data=json.dumps({"base_tree": base_tree, "tree": entries}).encode(), method="POST"))
    if st != 201:
        sys.exit(f"❌ tree: {st} {tree}")
    st, cmt = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/git/commits",
        headers=H(tok, {"Content-Type": "application/json"}),
        data=json.dumps({"message": commit_msg if commit_msg.endswith("\n")
                         else commit_msg + "\n",
                         "tree": tree["sha"], "parents": [head]}).encode(), method="POST"))
    if st != 201:
        sys.exit(f"❌ commit: {st} {cmt}")
    st, ref = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/git/refs/heads/main",
        headers=H(tok, {"Content-Type": "application/json"}),
        data=json.dumps({"sha": cmt["sha"]}).encode(), method="PATCH"))
    if st != 200:
        sys.exit(f"❌ ref 更新: {st} {ref}")
    print(f"✔ 推送完成 commit={cmt['sha'][:8]}")
    return cmt["sha"]


def release(tok, owner, version, title, body, sha):
    repo = NAME
    zip_path = SKILL_ROOT / "dist" / f"{NAME}-v{version}.zip"
    if not zip_path.is_file():
        sys.exit(f"❌ 缺少 {zip_path}（先跑 scripts/package.py）")
    raw = zip_path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    st, rels = api(urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/releases?per_page=100", headers=H(tok)))
    tag = f"v{version}"
    existing = next((r for r in rels if r.get("tag_name") == tag), None) if st == 200 else None
    if existing:
        rel_id, upload = existing["id"], existing["upload_url"].split("{")[0]
        for a in existing.get("assets", []):
            st, _ = api(urllib.request.Request(
                f"{API}/repos/{owner}/{repo}/releases/assets/{a['id']}",
                headers=H(tok), method="DELETE"))
            print(f"✔ 删旧附件 {a['name']} ({st})")
    else:
        st, rel = api(urllib.request.Request(
            f"{API}/repos/{owner}/{repo}/releases",
            headers=H(tok, {"Content-Type": "application/json"}),
            data=json.dumps({"tag_name": tag, "target_commitish": sha,
                             "name": title or tag, "body": body}).encode(), method="POST"))
        if st != 201:
            sys.exit(f"❌ 建 Release: {st} {rel}")
        rel_id, upload = rel["id"], rel["upload_url"].split("{")[0]
        print(f"✔ Release {tag} 已创建")
    st, _ = api(urllib.request.Request(
        f"{upload}?name={NAME}-v{version}.zip", headers=H(tok, {"Content-Type": "application/zip"}),
        data=raw, method="POST"))
    print(f"{'✔' if st == 201 else '❌'} zip 上传 ({st}) {len(raw):,} B SHA256={sha256[:12]}…")
    sums = f"{sha256}  {NAME}-v{version}.zip\n"
    st, _ = api(urllib.request.Request(
        f"{upload}?name=SHA256SUMS.txt",
        headers=H(tok, {"Content-Type": "text/plain; charset=utf-8"}),
        data=sums.encode(), method="POST"))
    print(f"{'✔' if st == 201 else '❌'} SHA256SUMS.txt 上传 ({st})")
    (SKILL_ROOT / "dist" / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="一键发版：打包校验推送 Release")
    ap.add_argument("--version", required=True)
    ap.add_argument("--commit-msg", required=True)
    ap.add_argument("--release-title")
    ap.add_argument("--release-body", default="")
    ap.add_argument("--release-body-file")
    ap.add_argument("--owner", default=os.environ.get("RFE_GH_OWNER", "zhangyongxin-1124"))
    ap.add_argument("--root", help="git 仓库根目录（默认脚本所在技能目录）")
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args()
    global SKILL_ROOT
    if args.root:
        SKILL_ROOT = Path(args.root).resolve()
    if not args.skip_preflight:
        preflight()
    tok = gh_token()
    body = args.release_body
    if args.release_body_file:
        body = Path(args.release_body_file).read_text(encoding="utf-8")
    sha = push(tok, args.owner, args.commit_msg)
    release(tok, args.owner, args.version, args.release_title, body, sha)
    print("✅ 发版完成。")


if __name__ == "__main__":
    main()
