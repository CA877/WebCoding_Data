import argparse
import json
import os
import time

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        required=True,
        help="例如 https://api.example.com/v1",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="要测试的模型名，例如 gpt-6-astra",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY"),
        help="API Key；也可以通过 OPENAI_API_KEY 环境变量提供",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="high",
        choices=["low", "medium", "high"],
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="打印完整原始响应",
    )

    args = parser.parse_args()

    if not args.api_key:
        raise RuntimeError(
            "没有找到 API Key。请使用 --api-key 或设置 OPENAI_API_KEY"
        )

    # 自动拼接 Responses API 地址
    base_url = args.base_url.rstrip("/")

    if base_url.endswith("/responses"):
        url = base_url
    else:
        url = f"{base_url}/responses"

    payload = {
        "model": args.model,
        "input": "只回复：连接成功",
        "reasoning": {
            "effort": args.reasoning_effort
        },
        "max_output_tokens": 50,
    }

    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json",
    }

    print("=" * 60)
    print("Request")
    print("=" * 60)
    print(f"URL:               {url}")
    print(f"Requested model:   {args.model}")
    print(f"Reasoning effort:  {args.reasoning_effort}")
    print()

    # 不打印 API Key
    print("Payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print()

    start = time.time()

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=300,
        )
    except Exception as e:
        print("请求失败：")
        print(repr(e))
        return

    elapsed = time.time() - start

    print("=" * 60)
    print("Response")
    print("=" * 60)

    print(f"HTTP status:       {response.status_code}")
    print(f"Elapsed:           {elapsed:.2f}s")

    try:
        data = response.json()
    except Exception:
        print("\n响应不是 JSON：")
        print(response.text)
        return

    returned_model = data.get("model")

    print(f"Requested model:   {args.model}")
    print(f"Returned model:    {returned_model}")
    print(
        f"Model matches:     "
        f"{returned_model == args.model}"
    )

    print()

    # 提取输出文本
    output_text = None

    if "output_text" in data:
        output_text = data["output_text"]

    elif "output" in data:
        texts = []

        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(content.get("text", ""))

        if texts:
            output_text = "\n".join(texts)

    print(f"Reply:             {output_text}")

    usage = data.get("usage")

    if usage:
        print()
        print("Usage:")
        print(json.dumps(usage, indent=2, ensure_ascii=False))

    # 一些有助于定位代理 / 网关的信息
    print()
    print("Interesting response headers:")

    interesting_headers = [
        "x-request-id",
        "request-id",
        "x-model",
        "x-served-model",
        "server",
        "via",
    ]

    for key in interesting_headers:
        if key in response.headers:
            print(f"  {key}: {response.headers[key]}")

    if args.show_raw:
        print()
        print("=" * 60)
        print("RAW RESPONSE")
        print("=" * 60)
        print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()