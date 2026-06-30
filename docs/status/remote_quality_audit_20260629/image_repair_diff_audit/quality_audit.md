# WebCoding 数据质量审计报告

## 输入

- `/data1/xieqianqian/webcoding/release_sft_6tasks_v1/jsonl/image-repair.jsonl`

## 文件计数

- `/data1/xieqianqian/webcoding/release_sft_6tasks_v1/jsonl/image-repair.jsonl`: 4845

## 按任务统计

### image-repair

- total: 4845

| issue | count | ratio | examples |
|---|---:|---:|---|
| `image_repair_diff_unavailable` | 4845 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `missing_output_files` | 4845 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `patch_0_replace_uncheckable_missing_output_code` | 4845 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `remote_url_present` | 2431 | 50.18% | `10-twenty.ca__seo, 01simple.com__world, 01logix.com__mspowerbi, 24-news.net__ip, 01simple.com__immigration` |
| `challenge_or_captcha:captcha` | 907 | 18.72% | `01logix.com__mspowerbi, 01logix.com__ad-linked, 01logix.com__microsoft-sharepoint-online-partner, 4master.nl__over-4master, 8dayhomesale.com` |
| `placeholder_or_parked:placeholder` | 702 | 14.49% | `2derms.com__contact, 2fast2die.com__about, 3mdrivingschool.com.au__faq, 2fast2die.com__reviews, 3mdrivingschool.com.au__contact` |
| `adult_or_sensitive_keyword:bet` | 485 | 10.01% | `01simple.com__world, 01simple.com__immigration, 01simple.com__realestate, 8welllife.com, MonstrosityPodcast.com__about-david-race` |
| `missing_dst_screenshot` | 278 | 5.74% | `10legsinthekitchen.com__staceybender, 2fast2die.com__reviews, 4leggedflix.com__faq, AllThingsAcoustic.org__contact, NeoK12.com__games` |
| `patch_0_search_not_found` | 187 | 3.86% | `10legsinthekitchen.com__staceybender, 2fast2die.com__reviews, 4leggedflix.com__faq, AllThingsAcoustic.org__contact, NeoK12.com__games` |
| `adult_or_sensitive_keyword:cam` | 116 | 2.39% | `50skyshades.com__blogs, 50skyshades.com, actionskills.co, agilemanifesto.org__history, alchetron.com__contact` |
| `risky_domain_from_instance_id` | 97 | 2.00% | `adoptionformsexpress.com__terms-of-use, adoptionformsexpress.com__privacy-policy, adoptionformsexpress.com, agencasinosbobet.net__admin, agencasinosbobet.net__mpo500-slot-game-review-and-winning-tips` |
| `patch_0_search_ambiguous_2` | 61 | 1.26% | `aaronlee.co, aiblifescience.com__cart, allied-eng.com__careers, alternativepac.us__join, ar2021.lovingheartjurong.org.sg__about-us` |
| `patch_1_replace_uncheckable_missing_output_code` | 58 | 1.20% | `24sevenfaith.com__workplace-wisdom, 3hundredtraining.com__39-2, aamd.org, aapatsahaaya.org__about, adkbrewery.com__story` |
| `placeholder_or_parked:lorem ipsum` | 27 | 0.56% | `amos.im.alisoft.com, antaresproperties.ca, ben-p.de__about-me, authentictitle.com__buyers, bikeforthecure.org__hiw` |
| `adult_or_sensitive_keyword:sex` | 17 | 0.35% | `3s-selfstorage.com__faq, accumulationofthings.com, activebacktohealth.com__blog, adoptionformsexpress.com__terms-of-use, adoptionformsexpress.com__privacy-policy` |
| `adult_or_sensitive_keyword:adult` | 17 | 0.35% | `LauraBrownAuthor.com__hearing-loss-resources, LauraBrownAuthor.com__my-books, LauraBrownAuthor.com__the-un-arranged-marriage, babywinkz.com__services, babywinkz.com__about-us` |
| `adult_or_sensitive_keyword:xxx` | 14 | 0.29% | `2023.ravensbourne.ac.uk__about-ravensbourne, 2023.ravensbourne.ac.uk__concept-realisation, birthdaycakephoto.net__birthday-cards-with-photos-c2, ahselanne.com__hello-im-felicia, ahselanne.com__crochet-apparel-accessories` |
| `adult_or_sensitive_keyword:dating` | 12 | 0.25% | `alltopdating.com__black-dating, alltopdating.com__asian-dating, alltopdating.com__christian-dating, bc-lawyers.com.au, chainoflakesvet.com__reviews` |
| `patch_2_replace_uncheckable_missing_output_code` | 10 | 0.21% | `adkbrewery.com__story, agathaschooler.com, alightcreative.com, avalon-enterprises.com__green-building, camstudio.org__faq` |
| `patch_0_search_ambiguous_3` | 9 | 0.19% | `MiamiLockAndKeys.com__locksmith-terms-and-conditions, andreworlowski.com__archive, centredevils.co.uk__transfer-news, chapelstreet.com.au__contact-us, chaseconsultants.com__about-chase` |
| `patch_1_search_not_found` | 7 | 0.14% | `age-of-product.com__agile-and-scrum, artechyapi.com__design-development, atsolutions.org__suggest-solution-ideas, bonsaimadesimple.com__three-late-winter-bonsai-tasks, bremerbrisbane.org.au` |
| `adult_or_sensitive_keyword:casino` | 7 | 0.14% | `apppearl.com__personvernerklaering, apppearl.com__om-oss, 1stok.com__privacy-policy, casinoapp.eu__blackjack-apps, fairgocasinoau.com` |
| `adult_or_sensitive_keyword:adult,bet` | 5 | 0.10% | `4gujarat.com__terms-of-service, aspire.com.sg__partner-with-us, bgassociates.com__business-case-boomer-marketing, fencebuildersaz.com__swimming-pool-safety-fence, furaffinity.net__search` |
| `adult_or_sensitive_keyword:bet,sex` | 5 | 0.10% | `96problems.com__we-vibe-instructions-and-manuals, 96problems.com__what-is-the-autoblow-history-reviews-and-critiques, 96problems.com, blog.aiesec.org__aiesec-at-unido-youth-innovation-and-partnerships-shaping-the-future, frenchamerican.org__cyber-security` |
| `placeholder_or_parked:this domain` | 5 | 0.10% | `anvely.ca__privacy-policy, atoztopnews.com, bsccareer.com, digitalmarkeeter.com__terms-of-service, digitalmarkeeter.com__privacy-policy` |
| `patch_3_replace_uncheckable_missing_output_code` | 4 | 0.08% | `adkbrewery.com__story, avalon-enterprises.com__green-building, coworkbuffalo.com__agreement, hookupinsiders.com__nordvpn-subscription-plans` |
| `adult_or_sensitive_keyword:bet,casino` | 4 | 0.08% | `agencasinosbobet.net__admin, agencasinosbobet.net__mpo500-slot-game-review-and-winning-tips, casinoreviews.nl__fruitautomaten, daroniefoodclub.com` |
| `adult_or_sensitive_keyword:bet,cam` | 4 | 0.08% | `ambientvisions.com__avsqanda, anchorbaptist1611.com__camp-2026, boldly.com__executive-assistants, fujilove.com` |
| `adult_or_sensitive_keyword:bet,dating` | 4 | 0.08% | `asianbridesonline.org__japanese-brides, bridesworldsite.com, datingjet.com__dating-sites, datingjet.com__coomeet-review` |
| `adult_or_sensitive_keyword:hookup` | 4 | 0.08% | `hookupsguru.com__size-guide-adidas-footwear, hookupinsiders.com__about, hookupsguru.com__return-policy, hookupinsiders.com__nordvpn-subscription-plans` |
| `adult_or_sensitive_keyword:cam,sex` | 3 | 0.06% | `brighamcason.com__feed, fixington.com__plumbers, fixington.com__heating-engineers` |
| `adult_or_sensitive_keyword:bet,cam,cams` | 3 | 0.06% | `camstudio.org, camstudio.org__faq, camstudio.org__legacy` |
| `adult_or_sensitive_keyword:bet,bets` | 3 | 0.06% | `freesuperbets.com__sport-news, freesuperbets.com__bookmakers, freesuperbets.com__et` |
| `adult_or_sensitive_keyword:bet,betting` | 3 | 0.06% | `g3newswire.com__sports-betting, gbbet.co.uk__sportsbook-reviews, gbbet.co.uk__deposit-methods` |
| `adult_or_sensitive_keyword:bet,hookup` | 3 | 0.06% | `hookeepr.com__bdsm-hookup, hookeepr.com__gay-hookup-sites, hookeepr.com__bbw-hookup-sites` |
| `patch_4_replace_uncheckable_missing_output_code` | 2 | 0.04% | `adkbrewery.com__story, coworkbuffalo.com__agreement` |
| `patch_0_search_ambiguous_5` | 2 | 0.04% | `beckermanlegal.com, gabrielheymans.com__contact` |
| `adult_or_sensitive_keyword:adult,dating,hookup` | 2 | 0.04% | `bestadulthookup.com__best-married-dating-sites, casualrelationships.net__adult` |
| `adult_or_sensitive_keyword:bet,casino,sex` | 2 | 0.04% | `betmentor.com__22bet-review, betmentor.com__melbet-review` |
| `challenge_or_captcha:captcha,enable javascript` | 2 | 0.04% | `caselfreliance.org__contact, drlisamarotta.com` |
| `placeholder_or_parked:lorem ipsum,placeholder` | 2 | 0.04% | `caselfreliance.org__news, gildedgal.com__shop` |
| `adult_or_sensitive_keyword:adult,dating` | 2 | 0.04% | `cupidbrides.com__lithuanian-brides, datingjet.org__adult` |
| `adult_or_sensitive_keyword:escort,escorts` | 2 | 0.04% | `delhi-escorts-x.in__sadie, elitekaya.com__rates` |
| `challenge_or_captcha:enable javascript` | 2 | 0.04% | `enable-javascript.com__es, genesis-construction.com__connect` |
| `adult_or_sensitive_keyword:casino,gambling` | 1 | 0.02% | `1stok.com__online-slots` |
| `adult_or_sensitive_keyword:adult,bet,bets,betting,gambling` | 1 | 0.02% | `abitoarchitects.com` |
| `patch_5_replace_uncheckable_missing_output_code` | 1 | 0.02% | `adkbrewery.com__story` |
| `adult_or_sensitive_keyword:bet,casino,gambling` | 1 | 0.02% | `agencasinosbobet.net__gambling` |
| `adult_or_sensitive_keyword:dating,porn,porno` | 1 | 0.02% | `alchetron.com__terms` |
| `adult_or_sensitive_keyword:porn` | 1 | 0.02% | `all-free-download.com__font` |
| `patch_0_search_ambiguous_543844` | 1 | 0.02% | `amaravillage.net__jackery-solarsaga-100w-solar-panel` |
| `patch_1_search_ambiguous_281` | 1 | 0.02% | `angel.co__overview` |
| `patch_0_search_ambiguous_331724` | 1 | 0.02% | `annabellenelson.com__books` |
| `patch_0_search_ambiguous_9656` | 1 | 0.02% | `anvely.ca__privacy-policy` |
| `patch_0_search_ambiguous_8` | 1 | 0.02% | `arhq.com__services` |
| `adult_or_sensitive_keyword:adult,bet,cam` | 1 | 0.02% | `aspire.com.sg__aspire-infinite-experiential-camps` |
| `patch_0_search_ambiguous_896742` | 1 | 0.02% | `aspirecaregiving.com__specialized-care-programs` |
| `adult_or_sensitive_keyword:erotic,nude,porn,sex,xxx` | 1 | 0.02% | `baddieschicks.com__alannasworldx-takes-a-hard-fucking-post-workout` |
| `challenge_or_captcha:security check` | 1 | 0.02% | `basicincome.org.uk__betninja` |
| `patch_0_search_ambiguous_12` | 1 | 0.02% | `bewellbyann.com` |
| `patch_1_search_ambiguous_5` | 1 | 0.02% | `andreasmaxones.com__kontakt` |
| `patch_0_search_ambiguous_464112` | 1 | 0.02% | `aaryavartt.com` |
| `patch_0_search_ambiguous_667948` | 1 | 0.02% | `3mdrivingschool.com.au__gallery` |
| `patch_0_search_ambiguous_790468` | 1 | 0.02% | `4thfloorcreative.com__about` |
| `adult_or_sensitive_keyword:bet,bets,betting,sex` | 1 | 0.02% | `betmentor.com` |
| `patch_0_search_ambiguous_1432069` | 1 | 0.02% | `bluewater-farms.com__fresh-cranberries` |
| `placeholder_or_parked:coming soon` | 1 | 0.02% | `brewham.co.uk` |
| `patch_0_search_ambiguous_454654` | 1 | 0.02% | `campiopartners.com__contact` |
| `patch_0_search_ambiguous_213468` | 1 | 0.02% | `cannonhilldental.com__new-technology` |
| `placeholder_or_parked:placeholder,this domain,under construction` | 1 | 0.02% | `carefulapps.com` |
| `adult_or_sensitive_keyword:bet,betting,casino` | 1 | 0.02% | `casinoapp.eu__sports-betting` |
| `patch_0_search_ambiguous_4` | 1 | 0.02% | `chaplainsontheharbor.org__anime` |
| `patch_0_search_ambiguous_574473` | 1 | 0.02% | `clarkairservices.com__preventative-maintenance` |
| `patch_0_search_ambiguous_913939` | 1 | 0.02% | `ctrlnetworks.com__contact-us` |
| `adult_or_sensitive_keyword:bet,cam,cams,dating` | 1 | 0.02% | `datingjet.com__myfreecams-review` |
| `adult_or_sensitive_keyword:dating,hookup` | 1 | 0.02% | `datingjet.org__hookup-apps` |
| `adult_or_sensitive_keyword:cam,dating` | 1 | 0.02% | `datingupdates.org__social-media` |
| `adult_or_sensitive_keyword:bet,dating,sex` | 1 | 0.02% | `datingjet.org` |
| `adult_or_sensitive_keyword:bet,nude` | 1 | 0.02% | `deepnudeapps.com__bots` |
| `patch_0_search_ambiguous_381248` | 1 | 0.02% | `deanclaytonwoo.com` |
| `patch_0_search_ambiguous_522021` | 1 | 0.02% | `dreameditionspress.com__my-cart` |
| `patch_0_search_ambiguous_3261` | 1 | 0.02% | `drivebywebsites.co.uk__responsive-website-development` |
| `placeholder_or_parked:under construction` | 1 | 0.02% | `dressesgalore.co.uk` |
| `patch_0_search_ambiguous_528734` | 1 | 0.02% | `eaglecapecod.com__contact-eagle-companies-inc` |
| `adult_or_sensitive_keyword:escort` | 1 | 0.02% | `elitekaya.com__escort-jobs-for-girls` |
| `adult_or_sensitive_keyword:dating,escort,escorts` | 1 | 0.02% | `elitekaya.com__contact-us` |
| `patch_0_search_ambiguous_408020` | 1 | 0.02% | `elitehc.net__sms-privacy-policy` |
| `adult_or_sensitive_keyword:adult,escort,escorts` | 1 | 0.02% | `englandescortdirectory.com__registration` |
| `adult_or_sensitive_keyword:porn,porno` | 1 | 0.02% | `essentialsurvival.org__feed` |
| `patch_0_search_ambiguous_789253` | 1 | 0.02% | `eu-cnc.org__business` |
| `patch_0_search_ambiguous_314179` | 1 | 0.02% | `evesland.com__1081` |
| `patch_0_search_ambiguous_355935` | 1 | 0.02% | `familydentistryelpasotexas.com` |
| `patch_1_search_ambiguous_54` | 1 | 0.02% | `fortheloveofpeterentals.com__event-rental` |
| `adult_or_sensitive_keyword:bet,betting,casino,gambling` | 1 | 0.02% | `gamblingappsstore.com` |
| `patch_0_search_ambiguous_293294` | 1 | 0.02% | `getasa2.com__your-account` |
| `adult_or_sensitive_keyword:bet,bets,casino` | 1 | 0.02% | `goharpc.com__golden-panda-casino` |
| `adult_or_sensitive_keyword:cam,webcam` | 1 | 0.02% | `guywh.com__categories` |
| `patch_0_search_ambiguous_16424` | 1 | 0.02% | `hdizhi1.com__1_5` |

## 解读

- `likely_non_zh_en` / `likely_non_english_latin` / `likely_other_script`: 语言启发式，不替代人工或 fastText/langid，但适合作为第一轮剔除候选。
- `adult_or_sensitive_keyword:*` 和 `risky_domain_from_instance_id`: 域名、路径或页面文本命中成人/博彩/约会等风险词。
- `patch_*_search_not_found` / `patch_*_search_ambiguous_*`: patch 不能在输入代码中唯一匹配，edit/repair 监督不可靠。
- `image_repair_low_visual_diff`: repair 前后截图差异过小，可能是视觉无关 bug，也可能是不适合作为 image-repair 的样本。
- `remote_url_present`: 训练样本仍含远程 URL，需进一步区分允许的图片替代 URL与应本地化的资源。
