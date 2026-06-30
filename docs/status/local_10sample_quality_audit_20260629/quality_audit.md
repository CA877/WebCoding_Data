# WebCoding 数据质量审计报告

## 输入

- `data/local_samples/current/local_10samples_six_tasks_20260625/image-edit/samples_10.jsonl`
- `data/local_samples/current/local_10samples_six_tasks_20260625/image-generate/samples_10.jsonl`
- `data/local_samples/current/local_10samples_six_tasks_20260625/image-repair/samples_10.jsonl`
- `data/local_samples/current/local_10samples_six_tasks_20260625/text-edit/samples_10.jsonl`
- `data/local_samples/current/local_10samples_six_tasks_20260625/text-generate/samples_10.jsonl`
- `data/local_samples/current/local_10samples_six_tasks_20260625/text-repair/samples_10.jsonl`

## 文件计数

- `data/local_samples/current/local_10samples_six_tasks_20260625/image-edit/samples_10.jsonl`: 10
- `data/local_samples/current/local_10samples_six_tasks_20260625/image-generate/samples_10.jsonl`: 10
- `data/local_samples/current/local_10samples_six_tasks_20260625/image-repair/samples_10.jsonl`: 10
- `data/local_samples/current/local_10samples_six_tasks_20260625/text-edit/samples_10.jsonl`: 10
- `data/local_samples/current/local_10samples_six_tasks_20260625/text-generate/samples_10.jsonl`: 10
- `data/local_samples/current/local_10samples_six_tasks_20260625/text-repair/samples_10.jsonl`: 10

## 按任务统计

### image-editing

- total: 10

| issue | count | ratio | examples |
|---|---:|---:|---|
| `missing_output_files` | 10 | 100.00% | `1-keyworddomainnames.com__keyword-domains-for-sale, 1-keyworddomainnames.com__keyword-domain-news, 10-twenty.ca__seo, 10-twenty.ca, 10bestbuy.com__travel` |
| `patch_0_replace_uncheckable_missing_output_code` | 10 | 100.00% | `1-keyworddomainnames.com__keyword-domains-for-sale, 1-keyworddomainnames.com__keyword-domain-news, 10-twenty.ca__seo, 10-twenty.ca, 10bestbuy.com__travel` |
| `remote_url_present` | 7 | 70.00% | `10-twenty.ca__seo, 10-twenty.ca, 10bestbuy.com__travel, 10kcards.com__support, 1stok.com__bonus-offers` |
| `patch_1_replace_uncheckable_missing_output_code` | 6 | 60.00% | `10-twenty.ca__seo, 10bestbuy.com__travel, 10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers, 1teenporn.com` |
| `patch_0_search_not_found` | 5 | 50.00% | `10-twenty.ca__seo, 10-twenty.ca, 10kcards.com__support, 10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers` |
| `patch_1_search_not_found` | 4 | 40.00% | `10-twenty.ca__seo, 10bestbuy.com__travel, 1stok.com__bonus-offers, 22fusion.com` |
| `patch_2_replace_uncheckable_missing_output_code` | 3 | 30.00% | `10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers, 22fusion.com` |
| `adult_or_sensitive_keyword:bet` | 2 | 20.00% | `1-keyworddomainnames.com__keyword-domains-for-sale, 10bestbuy.com__travel` |
| `placeholder_or_parked:placeholder` | 2 | 20.00% | `10kcards.com__support, 1stok.com__bonus-offers` |
| `patch_3_replace_uncheckable_missing_output_code` | 1 | 10.00% | `10legsinthekitchen.com__recipes-2` |
| `patch_3_search_not_found` | 1 | 10.00% | `10legsinthekitchen.com__recipes-2` |
| `adult_or_sensitive_keyword:casino` | 1 | 10.00% | `1stok.com__bonus-offers` |
| `patch_2_search_not_found` | 1 | 10.00% | `1stok.com__bonus-offers` |
| `adult_or_sensitive_keyword:porn,sex,xxx` | 1 | 10.00% | `1teenporn.com` |
| `risky_domain_from_instance_id` | 1 | 10.00% | `1teenporn.com` |
| `adult_or_sensitive_keyword:bet,cam` | 1 | 10.00% | `22fusion.com` |

### image-generation

- total: 10

| issue | count | ratio | examples |
|---|---:|---:|---|
| `remote_url_present` | 9 | 90.00% | `01simple.com__139738, 01simple.com__immigration, 1-box.com, 1-keyworddomainnames.com, 1-keyworddomainnames.com__feed` |
| `adult_or_sensitive_keyword:bet` | 2 | 20.00% | `01simple.com__139738, 01simple.com__immigration` |
| `placeholder_or_parked:placeholder` | 2 | 20.00% | `10kcards.com__login, 1st-drainage-tewkesbury.co.uk__contact` |
| `challenge_or_captcha:captcha` | 1 | 10.00% | `1st-drainage-tewkesbury.co.uk__contact` |

### image-repair

- total: 10

| issue | count | ratio | examples |
|---|---:|---:|---|
| `image_repair_diff_unavailable` | 10 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `missing_output_files` | 10 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `patch_0_replace_uncheckable_missing_output_code` | 10 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `remote_url_present` | 8 | 80.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 01simple.com__world, 01logix.com__mspowerbi` |
| `adult_or_sensitive_keyword:bet` | 2 | 20.00% | `01simple.com__world, 01simple.com__immigration` |
| `placeholder_or_parked:placeholder` | 2 | 20.00% | `01logix.com__mspowerbi, 2023.ravensbourne.ac.uk__about-ravensbourne` |
| `missing_dst_screenshot` | 1 | 10.00% | `10legsinthekitchen.com__staceybender` |
| `patch_0_search_not_found` | 1 | 10.00% | `10legsinthekitchen.com__staceybender` |
| `challenge_or_captcha:captcha` | 1 | 10.00% | `01logix.com__mspowerbi` |
| `adult_or_sensitive_keyword:xxx` | 1 | 10.00% | `2023.ravensbourne.ac.uk__about-ravensbourne` |

### text-editing

- total: 10

| issue | count | ratio | examples |
|---|---:|---:|---|
| `missing_input_files` | 10 | 100.00% | `1-keyworddomainnames.com__keyword-domain-news, 1-keyworddomainnames.com__keyword-domains-for-sale, 10-twenty.ca, 10-twenty.ca__seo, 10bestbuy.com__travel` |
| `missing_output_files` | 10 | 100.00% | `1-keyworddomainnames.com__keyword-domain-news, 1-keyworddomainnames.com__keyword-domains-for-sale, 10-twenty.ca, 10-twenty.ca__seo, 10bestbuy.com__travel` |
| `patch_uncheckable_missing_input_code` | 10 | 100.00% | `1-keyworddomainnames.com__keyword-domain-news, 1-keyworddomainnames.com__keyword-domains-for-sale, 10-twenty.ca, 10-twenty.ca__seo, 10bestbuy.com__travel` |
| `remote_url_present` | 5 | 50.00% | `1-keyworddomainnames.com__keyword-domains-for-sale, 10-twenty.ca, 10kcards.com__support, 10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers` |
| `placeholder_or_parked:placeholder` | 3 | 30.00% | `10kcards.com__support, 1stok.com__bonus-offers, 1upretro.com__blog` |
| `adult_or_sensitive_keyword:casino` | 1 | 10.00% | `1stok.com__bonus-offers` |
| `adult_or_sensitive_keyword:porn,sex,xxx` | 1 | 10.00% | `1teenporn.com` |
| `risky_domain_from_instance_id` | 1 | 10.00% | `1teenporn.com` |

### text-generation

- total: 10

| issue | count | ratio | examples |
|---|---:|---:|---|
| `placeholder_or_parked:placeholder` | 6 | 60.00% | `2daybusinessinfo.com__forex, 24-news.net, 01logix.com, 3mdrivingschool.com.au__about-us, 1-keyworddomainnames.com__keyword-domain-news` |
| `challenge_or_captcha:captcha` | 4 | 40.00% | `3dgroup.net__360-degree-feedback, 3dgroup.net__feedback-coaching, 01logix.com, 3dgroup.net__leadership-navigator-360-degree-feedback` |
| `adult_or_sensitive_keyword:bet` | 3 | 30.00% | `2daybusinessinfo.com__forex, 3dgroup.net__feedback-coaching, 3mdrivingschool.com.au__learner-drivers` |
| `remote_url_present` | 2 | 20.00% | `3mdrivingschool.com.au__about-us, 3mdrivingschool.com.au__learner-drivers` |
| `placeholder_or_parked:lorem ipsum` | 1 | 10.00% | `3dgroup.net__feedback-coaching` |
| `adult_or_sensitive_keyword:cam` | 1 | 10.00% | `24-news.net` |
| `adult_or_sensitive_keyword:dating` | 1 | 10.00% | `01logix.com` |

### text-repair

- total: 10

| issue | count | ratio | examples |
|---|---:|---:|---|
| `missing_input_files` | 10 | 100.00% | `1staab.com__digital-art, 1staab.com__quotes, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `missing_output_files` | 10 | 100.00% | `1staab.com__digital-art, 1staab.com__quotes, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `patch_uncheckable_missing_input_code` | 10 | 100.00% | `1staab.com__digital-art, 1staab.com__quotes, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `remote_url_present` | 7 | 70.00% | `1staab.com__digital-art, 1staab.com__quotes, 10legsinthekitchen.com__staceybender, 01simple.com__world, 10legsinthekitchen.com__lets-talk-turkey-sandwiches` |
| `adult_or_sensitive_keyword:bet,sex,xxx` | 2 | 20.00% | `1staab.com__digital-art, 1staab.com__quotes` |
| `adult_or_sensitive_keyword:bet` | 2 | 20.00% | `01simple.com__world, 01simple.com__immigration` |
| `challenge_or_captcha:captcha` | 1 | 10.00% | `01logix.com__mspowerbi` |
| `adult_or_sensitive_keyword:xxx` | 1 | 10.00% | `2023.ravensbourne.ac.uk__about-ravensbourne` |
| `placeholder_or_parked:placeholder` | 1 | 10.00% | `2023.ravensbourne.ac.uk__about-ravensbourne` |

## 解读

- `likely_non_zh_en` / `likely_non_english_latin` / `likely_other_script`: 语言启发式，不替代人工或 fastText/langid，但适合作为第一轮剔除候选。
- `adult_or_sensitive_keyword:*` 和 `risky_domain_from_instance_id`: 域名、路径或页面文本命中成人/博彩/约会等风险词。
- `patch_*_search_not_found` / `patch_*_search_ambiguous_*`: patch 不能在输入代码中唯一匹配，edit/repair 监督不可靠。
- `image_repair_low_visual_diff`: repair 前后截图差异过小，可能是视觉无关 bug，也可能是不适合作为 image-repair 的样本。
- `remote_url_present`: 训练样本仍含远程 URL，需进一步区分允许的图片替代 URL与应本地化的资源。
