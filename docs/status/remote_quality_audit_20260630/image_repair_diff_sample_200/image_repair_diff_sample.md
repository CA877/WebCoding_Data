# Image Repair Diff Sample

- release root: `/data1/xieqianqian/webcoding/release_sft_6tasks_v1`
- total records: 4845
- eligible with src/dst: 4567
- sampled: 200
- seed: 20260630

## Status

| status | count | ratio in sample |
|---|---:|---:|
| `ok` | 200 | 100.00% |

## RMS Diff Buckets

| bucket | count | ratio among ok |
|---|---:|---:|
| `clear_0.05_0.10` | 20 | 10.00% |
| `large_ge_0.10` | 49 | 24.50% |
| `low_0.01_0.02` | 15 | 7.50% |
| `moderate_0.02_0.05` | 22 | 11.00% |
| `near_identical_lt_0.005` | 89 | 44.50% |
| `very_low_0.005_0.01` | 5 | 2.50% |

## Numeric Summary

### rms_diff

| min | p10 | p25 | median | mean | p75 | p90 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.000000 | 0.000000 | 0.000000 | 0.013287 | 0.059952 | 0.098313 | 0.172058 | 0.594047 |

### mean_abs_diff

| min | p10 | p25 | median | mean | p75 | p90 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.000000 | 0.000000 | 0.000000 | 0.000712 | 0.025144 | 0.027626 | 0.072147 | 0.487001 |

### changed_pixel_ratio

| min | p10 | p25 | median | mean | p75 | p90 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.000000 | 0.000000 | 0.000000 | 0.004517 | 0.105532 | 0.186340 | 0.375183 | 0.974731 |

## Lowest RMS Examples

| instance_id | rms | mean_abs | changed_pixels | bucket |
|---|---:|---:|---:|---|
| `bryonycrane.co.uk__shop` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `greenwaynetwork.org__become-a-member` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `babywinkz.com__elitza` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `fitnessbuzz.net__superfood-reviews` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `fleahopper.com__happy-healthy-and-on-the-road-again` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `bbcwahpeton.org__events` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `bridgechurch.org.za__plan-your-visit-port-alfred` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `camptechii.com__services` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `caddyserver.com__json` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `edurobots.eu__about-us` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `highschoolsports.co__sign_up` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `holybasil.com.au__privacy` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `advancingsynergy.com__about-us` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `floridamotorcycletraining.com__keo-doi-ghi-ban-dau` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `bridesworldsite.com` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `evesland.com__rehabilitation-of-agbo-road-and-construction-triple-cell-box-culvert-of-3m-x-3m-in-ijebu-igboogun-state` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `diyindex.com__tools-skills` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `gezginkamera.net__360-derece-ajans-hizmetleri` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `accountingtaxespayroll.com` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
| `brazdepina.com__about` | 0.000000 | 0.000000 | 0.00% | `near_identical_lt_0.005` |
