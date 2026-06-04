#!/usr/bin/env python3
"""
测试服务器对 HuggingFace 的连通性。

用法:
    python3 scripts/test_hf_connectivity.py
    python3 scripts/test_hf_connectivity.py --token hf_xxx
"""

import argparse
import os
import sys
import time
import urllib.request
import urllib.error
import ssl


# ============ 测试目标 ============
ENDPOINTS = [
    ("hf-mirror.com（镜像站）", "https://hf-mirror.com"),
    ("huggingface.co（官方站）", "https://huggingface.co"),
]

API_PATHS = [
    ("/api/models?limit=1", "Models API"),
    ("/api/datasets?limit=1", "Datasets API"),
]


def test_http(name: str, url: str, timeout: int = 15) -> bool:
    """测试 HTTP 连通性。"""
    print(f"\n  [{name}]")
    print(f"  URL: {url}")
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "hf-connectivity-test"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = resp.status
            size = len(resp.read())
            elapsed = time.time() - t0
            print(f"  状态: {status}  响应: {size} bytes  耗时: {elapsed:.2f}s")
            return True
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        print(f"  HTTP 错误: {e.code} {e.reason}  耗时: {elapsed:.2f}s")
        return e.code < 500  # 4xx 说明网络通了
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  失败: {type(e).__name__}: {e}  耗时: {elapsed:.2f}s")
        return False


def test_hf_api(token: str | None, endpoint: str, name: str) -> bool:
    """测试 huggingface_hub API 操作。"""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print(f"\n  [{name} - huggingface_hub API]")
        print("  跳过: pip install huggingface_hub")
        return False

    os.environ["HF_ENDPOINT"] = endpoint
    api = HfApi(token=token)
    print(f"\n  [{name} - huggingface_hub API]")
    print(f"  endpoint: {endpoint}")

    # 1) list_models
    t0 = time.time()
    try:
        models = list(api.list_models(limit=1))
        print(f"  list_models: OK ({len(models)} result, {time.time()-t0:.2f}s)")
    except Exception as e:
        print(f"  list_models: FAIL ({type(e).__name__}: {e}, {time.time()-t0:.2f}s)")
        return False

    # 2) whoami (需要 token)
    if token:
        t0 = time.time()
        try:
            info = api.whoami()
            print(f"  whoami: OK (user={info.get('name','?')}, {time.time()-t0:.2f}s)")
        except Exception as e:
            print(f"  whoami: FAIL ({type(e).__name__}: {e}, {time.time()-t0:.2f}s)")
    else:
        print("  whoami: 跳过（无 token）")

    return True


def test_upload_permission(token: str | None, endpoint: str, repo: str, name: str) -> bool:
    """测试上传权限（创建一个小文件再删除）。"""
    if not token:
        print(f"\n  [{name} - 上传权限测试]")
        print("  跳过: 无 token")
        return False

    try:
        from huggingface_hub import HfApi
    except ImportError:
        return False

    os.environ["HF_ENDPOINT"] = endpoint
    api = HfApi(token=token)
    print(f"\n  [{name} - 上传权限测试]")
    print(f"  repo: {repo}  endpoint: {endpoint}")

    # 尝试上传一个小测试文件
    import tempfile
    t0 = time.time()
    test_content = f"connectivity test at {time.time()}"
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(test_content)
            tmp_path = f.name
        api.upload_file(
            path_or_fileobj=tmp_path,
            path_in_repo="_test_connectivity.txt",
            repo_id=repo,
            repo_type="dataset",
            commit_message="connectivity test (will delete)",
        )
        elapsed = time.time() - t0
        print(f"  upload_file: OK ({elapsed:.2f}s)")
        os.unlink(tmp_path)

        # 清理：删除测试文件
        try:
            api.delete_file(
                path_in_repo="_test_connectivity.txt",
                repo_id=repo,
                repo_type="dataset",
                commit_message="cleanup connectivity test",
            )
            print(f"  cleanup: OK")
        except Exception:
            print(f"  cleanup: 跳过（手动删除 _test_connectivity.txt）")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  upload_file: FAIL ({type(e).__name__}: {e}, {elapsed:.2f}s)")
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return False


def main():
    parser = argparse.ArgumentParser(description="测试 HuggingFace 连通性")
    parser.add_argument("--token", type=str, default=None,
                        help="HF token（默认读 HF_TOKEN 环境变量）")
    parser.add_argument("--repo", type=str, default="mistletoe111/webcoding1",
                        help="测试上传的目标 repo")
    parser.add_argument("--skip-upload", action="store_true",
                        help="跳过上传测试")
    args = parser.parse_args()

    token = args.token or os.environ.get("HF_TOKEN")

    print("=" * 50)
    print("HuggingFace 连通性测试")
    print("=" * 50)

    # 打印环境
    print(f"\n代理设置:")
    for var in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "HF_ENDPOINT"):
        val = os.environ.get(var, "（未设置）")
        print(f"  {var}={val}")
    print(f"  token: {'已提供' if token else '未提供'}")

    # 1) HTTP 连通性
    print(f"\n{'='*50}")
    print("1. HTTP 连通性")
    print("=" * 50)

    results = {}
    for ep_name, ep_url in ENDPOINTS:
        # 首页
        ok = test_http(f"{ep_name} 首页", ep_url)
        results[f"{ep_name}_home"] = ok

        # API
        for path, api_name in API_PATHS:
            ok = test_http(f"{ep_name} {api_name}", ep_url + path)
            results[f"{ep_name}_{api_name}"] = ok

    # 2) huggingface_hub API
    print(f"\n{'='*50}")
    print("2. huggingface_hub API")
    print("=" * 50)

    for ep_name, ep_url in ENDPOINTS:
        test_hf_api(token, ep_url, ep_name)

    # 3) 上传测试
    if not args.skip_upload:
        print(f"\n{'='*50}")
        print("3. 上传权限测试")
        print("=" * 50)
        for ep_name, ep_url in ENDPOINTS:
            test_upload_permission(token, ep_url, args.repo, ep_name)

    # 汇总
    print(f"\n{'='*50}")
    print("汇总")
    print("=" * 50)
    for k, v in results.items():
        print(f"  {'✓' if v else '✗'} {k}")


if __name__ == "__main__":
    main()
