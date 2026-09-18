# 远程环境运行手册

物理机入口：`ssh -p 65022 adminweihunj@36.213.175.38`；项目根：`/data1/xieqianqian/webcoding/WebCoding_Data`；远程执行使用 `lora` 环境。

网页 crawl 的已知代理为 `http://127.0.0.1:7890`，使用前核验监听与连通性。普通 API、SSH、评测和渲染先清除大小写代理变量。凭据只从受保护来源注入，绝不写进代码、文档、日志、manifest 或提交记录。

Pipeline C 的浏览器代理可用 `--browser-proxy-bypass` 或 `WEBCODING_BROWSER_PROXY_BYPASS` 指定直连域名；`crawl/pipeline_c/run_strict_local_debug.sh` 默认让 `ai.bayesdl.com` 与 `.bayesdl.com` 直连。
