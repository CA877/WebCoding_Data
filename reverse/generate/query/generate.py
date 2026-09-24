#!/usr/bin/env python3
"""Generate Text Generate query plans/results under the 0921 quota.

The script never edits a release. It validates the quota matrix, selects the
matching benchmark/category few-shots, and asks an OpenAI-compatible endpoint
for one query at a time. Results are resumable JSONL records.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen

PRODUCT = {
    "Tool / Productivity": 226, "Editor / Creator": 283, "Game": 552,
    "Simulation": 628, "SVG / Diagram": 481, "Canvas / Generative Art": 8,
    "Data Visualization": 769, "Multimedia": 157,
    "Multi-page Product Website": 713, "React Full-stack Application": 660,
}
BENCH = {
 "Tool / Productivity": {"ArtifactsBench":70,"MiniAppBench":53,"Cookie-Bench":64,"WebGen":23,"WebCompass":16,"Vision2Web":0},
 "Editor / Creator": {"ArtifactsBench":74,"MiniAppBench":74,"Cookie-Bench":83,"WebGen":27,"WebCompass":25,"Vision2Web":0},
 "Game": {"ArtifactsBench":244,"MiniAppBench":185,"Cookie-Bench":123,"WebGen":0,"WebCompass":0,"Vision2Web":0},
 "Simulation": {"ArtifactsBench":148,"MiniAppBench":277,"Cookie-Bench":203,"WebGen":0,"WebCompass":0,"Vision2Web":0},
 "SVG / Diagram": {"ArtifactsBench":229,"MiniAppBench":150,"Cookie-Bench":102,"WebGen":0,"WebCompass":0,"Vision2Web":0},
 "Canvas / Generative Art": {"ArtifactsBench":0,"MiniAppBench":8,"Cookie-Bench":0,"WebGen":0,"WebCompass":0,"Vision2Web":0},
 "Data Visualization": {"ArtifactsBench":192,"MiniAppBench":172,"Cookie-Bench":268,"WebGen":77,"WebCompass":60,"Vision2Web":0},
 "Multimedia": {"ArtifactsBench":77,"MiniAppBench":10,"Cookie-Bench":70,"WebGen":0,"WebCompass":0,"Vision2Web":0},
 "Multi-page Product Website": {"ArtifactsBench":0,"MiniAppBench":0,"Cookie-Bench":0,"WebGen":520,"WebCompass":81,"Vision2Web":112},
 "React Full-stack Application": {"ArtifactsBench":0,"MiniAppBench":0,"Cookie-Bench":0,"WebGen":500,"WebCompass":40,"Vision2Web":120},
}
STACK = {"React + Vite":4738, "Vue 3 + Vite":402, "React Full-stack":443, "Angular":299}

def check_quota():
    assert sum(PRODUCT.values()) == 4477
    assert sum(STACK.values()) == 5882
    for cat, n in PRODUCT.items():
        assert sum(BENCH[cat].values()) == n, (cat, BENCH[cat])
    assert sum(sum(x.values()) for x in BENCH.values()) == 4477

def load_shots(path: Path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    cases = obj.get("cases", obj) if isinstance(obj, dict) else obj
    grouped = {}
    for x in cases:
        if not x.get("query", "").strip():
            continue
        grouped.setdefault((x["benchmark"], x["category"]), []).append(x)
    return grouped

def category_key(name):
    return {"Tool / Productivity":"Tool", "Editor / Creator":"Editor", "SVG / Diagram":"SVG / Diagram",
            "Canvas / Generative Art":"Canvas", "Data Visualization":"Data Visualization",
            "Multi-page Product Website":"Multi-page", "React Full-stack Application":"Full-stack"}.get(name, name)

def page_scope(category):
    return "multi_page" if category == "Multi-page Product Website" else "single_page"

def call_llm(base, key, model, prompt, timeout, wire_api, actor_authorization,
             max_output_tokens=1400, plain_query=False):
    headers={"Authorization":"Bearer " + key, "Content-Type":"application/json"}
    if actor_authorization:
        headers["x-openai-actor-authorization"] = actor_authorization
    if wire_api == "responses":
        body = {"model": model, "temperature": 0.7,
                "instructions": "You write concise, concrete web app build queries.",
                "input": prompt, "store": False, "stream": True}
        if max_output_tokens is not None:
            body["max_output_tokens"] = max_output_tokens
        req = Request(base.rstrip("/") + "/responses", data=json.dumps(body).encode(), headers=headers)
        parts=[]; usage={}; terminal_event=None
        with urlopen(req, timeout=timeout) as r:
            for raw in r:
                line=raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload=line[5:].strip()
                if payload == "[DONE]":
                    break
                event=json.loads(payload)
                if event.get("type") == "response.output_text.delta":
                    parts.append(event.get("delta") or "")
                elif event.get("type") == "response.completed":
                    terminal_event="response.completed"
                    response=event.get("response") or {}
                    usage=response.get("usage") or usage
                    if not parts:
                        parts.extend(part.get("text", "") for item in response.get("output", [])
                                     for part in item.get("content", []) if part.get("type") == "output_text")
                elif event.get("type") in {"response.incomplete", "response.failed", "error"}:
                    terminal_event=event.get("type")
        text="".join(parts).strip(); data={"usage": usage}
    else:
        body = {"model": model, "temperature": 0.7,
                "messages": [{"role":"system","content":"You write concise, concrete web app build queries."}, {"role":"user","content":prompt}]}
        if max_output_tokens is not None:
            body["max_tokens"] = max_output_tokens
        req = Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
        with urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        text = data["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json\n", "", 1).strip()
    if plain_query:
        marker="<<<END_QUERY>>>"
        if marker not in text:
            raise RuntimeError(f"incomplete query stream: terminal_event={terminal_event!r}")
        query=text.split(marker,1)[0].strip()
        if len(query) < 10:
            raise ValueError("model returned an empty query")
        return {"query":query}, data.get("usage", {})
    result = json.loads(text)
    if not isinstance(result, dict) or not isinstance(result.get("query"), str) or len(result["query"].strip()) < 10:
        raise ValueError("model returned invalid query object")
    return result, data.get("usage", {})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--fewshot-json", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int, default=0, help="0 means all 4477 product allocations")
    p.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.nju-link.com/v1"))
    p.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"))
    p.add_argument("--wire-api", choices=("chat-completions", "responses"), default="chat-completions")
    p.add_argument("--actor-authorization", default=None)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--benchmarks", default="", help="Comma-separated benchmark allowlist")
    p.add_argument("--api-key-file", type=Path, default=None)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--max-attempts", type=int, default=1)
    p.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    args=p.parse_args(); check_quota()
    if args.max_attempts < 1 or args.retry_backoff_seconds < 0:
        p.error("max-attempts must be positive and retry-backoff-seconds cannot be negative")
    shots=load_shots(args.fewshot_json)
    allowed={x.strip() for x in args.benchmarks.split(",") if x.strip()} or None
    missing=[]
    for cat, cells in BENCH.items():
        for bench,n in cells.items():
            if allowed is not None and bench not in allowed: continue
            if n and (bench, category_key(cat)) not in shots: missing.append((bench, category_key(cat)))
    if missing: raise SystemExit("missing few-shot cells: " + ", ".join(map(str, missing)))
    key=(args.api_key_file.read_text().strip() if args.api_key_file else os.getenv("OPENAI_API_KEY", ""))
    if not key: raise SystemExit("API key is required via --api-key-file or OPENAI_API_KEY")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing={}
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                x=json.loads(line); existing[x["allocation_id"]]=x
    allocations=[]
    for cat,cells in BENCH.items():
        for bench,n in cells.items():
            if allowed is not None and bench not in allowed: continue
            for i in range(n): allocations.append((f"{cat}|{bench}|{i+1}",cat,bench))
    if args.limit: allocations=allocations[:args.limit]
    total_usage=Counter(); done=0
    pending=[x for x in allocations if x[0] not in existing]
    def one(item):
        aid,cat,bench=item
        refs=shots[(bench,category_key(cat))][:3]
        examples="\n\n".join(f"EXAMPLE {i+1}:\n{x['query']}" for i,x in enumerate(refs))
        ref_lengths=sorted(len(x["query"]) for x in refs)
        median_len=ref_lengths[len(ref_lengths)//2]
        guidance={
            "ArtifactsBench": "Use one concrete executable coding task with the benchmark's coding-expert preamble and focused implementation requirements. Do not turn it into a full PRD.",
            "MiniAppBench": "Use a compact direct feature request for a small app or tool. Include only the core interaction and data behavior; avoid long visual design or admin requirements.",
            "Cookie-Bench": "Keep this as a short, direct app requirement like the references: usually one or two sentences and one focused capability. Do not add a dashboard, persistence, roles, analytics, or extra workflows unless the reference style clearly requires them.",
            "WebGen": "Use a multi-page website or application brief with the same breadth as one reference. Include the main pages and key user flow, but do not expand into an exhaustive product requirements document.",
        }.get(bench, "Match the reference benchmark's scope and information density.")
        output_instruction=(
            "Return only the query text, without JSON or Markdown, and end it with the exact marker "
            "<<<END_QUERY>>>."
            if bench == "Vision2Web" else
            "Return JSON only with exactly one string field: {\"query\":\"...\"}."
        )
        prompt=(f"Create exactly one new web app build query for product category {cat}, aligned to {bench}. "
                f"Study the references only to match this benchmark's wording, scope, information density, and complexity. "
                f"Reference length median is about {median_len} characters; keep the new query in a similar range and avoid exceeding about {max(120, int(median_len*1.7))} characters unless the task genuinely needs it. "
                f"{guidance} Do not merge features from multiple examples, do not copy any example, and do not invent unrelated requirements. "
                f"{output_instruction}\n\n"+examples)
        attempt_errors=[]
        for attempt in range(1,args.max_attempts+1):
            try:
                result,usage=call_llm(args.base_url,key,args.model,prompt,args.timeout,
                                      args.wire_api,args.actor_authorization,
                                      None if bench == "Vision2Web" else 1400,
                                      plain_query=bench == "Vision2Web")
                record = {"allocation_id":aid,"product_category":cat,"benchmark":bench,
                          "page_scope":page_scope(cat),"query":result["query"],"model":args.model,
                          "fewshot_case_ids":[x.get("case_id") for x in refs],"usage":usage,
                          "attempts":attempt,"attempt_errors":attempt_errors,"status":"ok"}
                if bench == "WebCompass":
                    record["benchmark_variant"] = "mp" if record["page_scope"] == "multi_page" else "sp"
                return record
            except Exception as e:
                attempt_errors.append(repr(e)[:500])
                if attempt < args.max_attempts:
                    time.sleep(min(args.retry_backoff_seconds * attempt,30.0))
        return {"allocation_id":aid,"product_category":cat,"benchmark":bench,
                "status":"failed","attempts":args.max_attempts,
                "attempt_errors":attempt_errors,"error":attempt_errors[-1]}
    with args.out.open("a", encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=max(1,args.workers)) as pool:
            futures=[pool.submit(one,item) for item in pending]
            for future in as_completed(futures):
                rec=future.result()
                out.write(json.dumps(rec,ensure_ascii=False)+"\n"); out.flush(); done+=1
                for k,v in (rec.get("usage") or {}).items():
                    if isinstance(v,int): total_usage[k]+=v
                if rec["status"] != "ok": print(json.dumps(rec,ensure_ascii=False), file=sys.stderr)
    print(json.dumps({"status":"finished","requested":len(allocations),"new":done,"workers":args.workers,"output":str(args.out),"usage":dict(total_usage)},ensure_ascii=False))

if __name__ == "__main__": main()
