---
name: webcoding-crawl-results
description: 查找、盘点和管理 WebCoding 物理机上已抓取的网页、历史救援底稿和成功快照；按批次核对实际产物、筛选程度、重复关系及保留或删除决定。用于“已有可用爬取结果”“历史抓取记录”“整理清理旧批次”；URL 候选池和新爬取分别转用对应 skill。
---

# WebCoding 历史爬取结果

## 定位与路由

- 本地仓库：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft`。
- 物理机：`ssh -p 65022 adminweihunj@36.213.175.38`；主 run 根为 `/data1/xieqianqian/webcoding/WebCoding_Data/runs`，新 run 也可能在 `/data2/adminweihunj/webcoding/WebCoding_Data/runs`。
- 查已有产物、批次编号、数量、30 个四 HTML 项目或处置状态时，读取 [现存结果与处置清单](references/inventory.md)。只检查与用户问题相关的目录。
- 找输入 URL 用 `webcoding-url-pools`；新增抓取用 `crawl-web-pages`；后续造训练数据用 `synthesize-data`。盘点本身不启动爬虫、渲染、API 或任务构造。

## 核验和回答

1. 先区分用户要“保存过的网页”“历史技术通过”“当前可渲染”还是“可直接作为训练母本”。回答使用与证据相符的层级。
2. 清单是 2026-09-08 的现场快照，不是永久现状。问“当前”时，对目标批次核对 manifest 的状态数量和成功项目路径；文件目录数包含失败/残留，不能代替 pass 数。
3. 追加式日志可能有重试和同 URL 多条状态。若需最终成功数，按该 run 的唯一键及续跑规则聚合，分别报告尝试记录、最终成功、实际存在项目；不要随意把任一 pass 当最终状态。
4. 页面数从成功项目实际 HTML/HTM 文件统计；严格四页候选需递归确认。文件数只能证明结构，不证明首页加三子页、导航或保真。
5. 历史截图/视觉 pass 不等于当前外链仍能加载。原站 origin 回放也不等于 localhost 可用；目录名 strict/final/40k、文件名 accepted_manifest 都不能单独证明 accepted Generate Seed。
6. 历史救援可能替换缺失图片、删除代码、执行 CSS purge，并按省略 JS/bundle 的旧 60K 或外置后 40K 计数。推荐母本时必须指出“处理后网页”与“完整保真原站”的区别。
7. 清理视图与来源不是独立新样本；成功 URL 相同也不必然意味着字节相同。只按实际核验过的重复层级报告，体积不推算为可释放空间。

## 处置与维护

- 保留清单中的 A1–C1、D1-1 等批次编号和 T1–T9 试跑组编号，便于用户选择。
- 当前数据产物均待用户选择；旧盘点文档的删除授权不等于历史网页、URL 清单、manifest 或截图的删除授权。
- 查询/整理只读。用户明确决定某个目标删除后，展开精确路径，核对活跃写入、下游引用、唯一成功样本和硬链接；不因名字含 pilot/test 就自动删除，不把 manifest 指向失效误判成所有副本已丢失。
- 删除优先可恢复方式。记录所选编号、精确目标、授权内容、执行时间、结果及恢复方式；小体积 manifest/summary 的保留和项目主体的删除分别说明。
- 用户要求更新结果/记录决定时，更新 `references/inventory.md` 和项目资产登记摘要；新数量保留核验时间及证据文件，建议与已执行决定分开写。不要重新建立多份“最新盘点”文档。
- 交付简洁给出可复用类别、关键数量和限制，以及实际处置结果；无需重复完整附录。
