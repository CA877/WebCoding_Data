# WebCoding 数据质量审计报告

## 输入

- `/data1/xieqianqian/webcoding/release_sft_6tasks_v1/jsonl/image-edit.jsonl`
- `/data1/xieqianqian/webcoding/release_sft_6tasks_v1/jsonl/image-repair.jsonl`

## 文件计数

- `/data1/xieqianqian/webcoding/release_sft_6tasks_v1/jsonl/image-repair.jsonl`: 4845
- `/data1/xieqianqian/webcoding/release_sft_6tasks_v1/jsonl/image-edit.jsonl`: 4333

## 按任务统计

### image-editing

- total: 4333

| issue | count | ratio | examples |
|---|---:|---:|---|
| `missing_output_files` | 4333 | 100.00% | `1-keyworddomainnames.com__keyword-domains-for-sale, 1-keyworddomainnames.com__keyword-domain-news, 10-twenty.ca__seo, 10-twenty.ca, 10bestbuy.com__travel` |
| `patch_0_replace_uncheckable_missing_output_code` | 4333 | 100.00% | `1-keyworddomainnames.com__keyword-domains-for-sale, 1-keyworddomainnames.com__keyword-domain-news, 10-twenty.ca__seo, 10-twenty.ca, 10bestbuy.com__travel` |
| `patch_0_search_not_found` | 3020 | 69.70% | `10-twenty.ca__seo, 10-twenty.ca, 10kcards.com__support, 10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers` |
| `remote_url_present` | 2471 | 57.03% | `10-twenty.ca__seo, 10-twenty.ca, 10kcards.com__support, 1stok.com__bonus-offers, 1teenporn.com` |
| `patch_1_replace_uncheckable_missing_output_code` | 1648 | 38.03% | `10-twenty.ca__seo, 10bestbuy.com__travel, 10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers, 1teenporn.com` |
| `placeholder_or_parked:placeholder` | 1309 | 30.21% | `1upretro.com__blog, 24-news.net__sellers, 2x2blog.com__about-us, 3-l.org__child-development, 3mdrivingschool.com.au__reviews` |
| `patch_1_search_not_found` | 1095 | 25.27% | `10-twenty.ca__seo, 10bestbuy.com__travel, 1stok.com__bonus-offers, 22fusion.com, 1upretro.com__blog` |
| `adult_or_sensitive_keyword:bet` | 978 | 22.57% | `1-keyworddomainnames.com__keyword-domains-for-sale, 10bestbuy.com__travel, 2nvr.org.au, 2x2blog.com__about-us, 3cuvw.de__hornschuch-promenade` |
| `challenge_or_captcha:captcha` | 954 | 22.02% | `3dgroup.net__custom-360-feedback-surveys, 3dgroup.net__individuals, 4thfloorcreative.com, 51deguo.com, 51deguo.com__member` |
| `patch_2_replace_uncheckable_missing_output_code` | 864 | 19.94% | `10legsinthekitchen.com__recipes-2, 1stok.com__bonus-offers, 22fusion.com, 1upretro.com__blog, 2adt.com__about` |
| `patch_2_search_not_found` | 563 | 12.99% | `1stok.com__bonus-offers, 1upretro.com__blog, 3-l.org__child-development, 3-l.org__learning-news, 4cornersfeet.com__applicant-info` |
| `patch_3_replace_uncheckable_missing_output_code` | 239 | 5.52% | `10legsinthekitchen.com__recipes-2, 1upretro.com__blog, 2adt.com__about, 3-l.org__child-development, 3-l.org__learning-news` |
| `patch_3_search_not_found` | 153 | 3.53% | `10legsinthekitchen.com__recipes-2, 1upretro.com__blog, 3-l.org__child-development, 3-l.org__learning-news, VancouverLocksmithStore.com__coupons-locksmith-service` |
| `adult_or_sensitive_keyword:cam` | 131 | 3.02% | `21ilab.com, 50skyshades.com__video, aardwerk.org__aardwerk-boot-camp-2016-registratie-registration, actionskills.co__web-design, adacrow.com` |
| `patch_4_replace_uncheckable_missing_output_code` | 128 | 2.95% | `1upretro.com__blog, 2adt.com__about, 3-l.org__child-development, DaytonLockAndKeys.com__residential-locksmith, VanNuysLocksmithService.net__coupons-locksmith-service` |
| `risky_domain_from_instance_id` | 91 | 2.10% | `1teenporn.com, adoptionformsexpress.com__terms-of-use, adultchatdatingsites.com__stripchat, adultliteracybarrow.org__literacy-ball, agencasinosbobet.net` |
| `patch_5_replace_uncheckable_missing_output_code` | 79 | 1.82% | `2adt.com__about, DaytonLockAndKeys.com__residential-locksmith, VanNuysLocksmithService.net__coupons-locksmith-service, VancouverLocksmithStore.com__coupons-locksmith-service, activetraffic.com.au__track-record` |
| `adult_or_sensitive_keyword:dating` | 74 | 1.71% | `ahsc.org.uk__how-we-work, alaynecurtiss.com__stop-the-walkouts, alteradomi.com__altera-domi-nederlands, andreworlowski.com, armandonavarro.com__myportfolio` |
| `patch_4_search_not_found` | 71 | 1.64% | `3-l.org__child-development, DaytonLockAndKeys.com__residential-locksmith, VancouverLocksmithStore.com__coupons-locksmith-service, activetraffic.com.au__track-record, agooart.com__page_6` |
| `adult_or_sensitive_keyword:bet,cam` | 62 | 1.43% | `22fusion.com, adaptistration.com__the-orchestra-website-reviews, agilemanifesto.org__authors, agooart.com__page_6, alchetron.com__privacy-policy` |
| `adult_or_sensitive_keyword:bet,dating` | 61 | 1.41% | `7gadgets.com__decor, abateva.org__officers, accentusoft.com__case-studies-and-whitepapers, alabamamga.org__local-associations, alltopdating.com` |
| `patch_6_replace_uncheckable_missing_output_code` | 52 | 1.20% | `2adt.com__about, DaytonLockAndKeys.com__residential-locksmith, VanNuysLocksmithService.net__coupons-locksmith-service, activetraffic.com.au__track-record, agooart.com__page_6` |
| `patch_5_search_not_found` | 46 | 1.06% | `DaytonLockAndKeys.com__residential-locksmith, VancouverLocksmithStore.com__coupons-locksmith-service, activetraffic.com.au__track-record, agooart.com__page_6, alteredstory.com__whatif` |
| `patch_7_replace_uncheckable_missing_output_code` | 36 | 0.83% | `DaytonLockAndKeys.com__residential-locksmith, activetraffic.com.au__track-record, agooart.com__page_6, amerusfinancial.com__blog, basilwoodsinternational.in__about-us-2` |
| `patch_6_search_not_found` | 35 | 0.81% | `activetraffic.com.au__track-record, agooart.com__page_6, amerusfinancial.com__blog, aushiphop.com.au, avalonbeachslsc.com.au__our-clubhouse` |
| `patch_7_search_not_found` | 25 | 0.58% | `activetraffic.com.au__track-record, agooart.com__page_6, amerusfinancial.com__blog, basilwoodshyd.in__shamshabad, bb-whitening.com` |
| `adult_or_sensitive_keyword:sex` | 23 | 0.53% | `adoptionformsexpress.com__terms-of-use, akbarsarkiali.com__contact-us, americana-for-sale.com__1967-chrysler-newport, balfournursery.com, bborwv.com__default_4` |
| `patch_8_replace_uncheckable_missing_output_code` | 20 | 0.46% | `amerusfinancial.com__blog, basilwoodsinternational.in__about-us-2, bb-whitening.com, berkeleytherapist.net__areas-of-expertise, budgetodorremoval.com__tobacco-smoke-odor` |
| `adult_or_sensitive_keyword:adult` | 19 | 0.44% | `adhdclinic.com.au, adultliteracybarrow.org__literacy-ball, artistpalettestudio.com, atlastmsflorida.com, babywinkz.com__judy` |
| `patch_9_replace_uncheckable_missing_output_code` | 16 | 0.37% | `amerusfinancial.com__blog, basilwoodsinternational.in__about-us-2, bb-whitening.com, berkeleytherapist.net__areas-of-expertise, busfinders.com__schools` |
| `adult_or_sensitive_keyword:xxx` | 16 | 0.37% | `birthdaycakephoto.net__happy-birthday-wishes-c8, birthdaycakephoto.net__birthday-cards-with-photos-c2, birthdaycakephoto.net__love-photo-frame-c5, birthdaycakephoto.net, brittenslogs.co.uk__pricingcontact` |
| `adult_or_sensitive_keyword:bet,sex` | 10 | 0.23% | `64gltd.com__outsourced-virtual-office-call-answering-cloud-based-support-for-uk-businesses, 96problems.com__what-is-an-onahole-the-complete-guide-to-onaholes, americana-for-sale.com__1967-cadillac-deville-3, bitcointalk.org__page_7, citylife.chelmsford.gov.uk` |
| `patch_8_search_not_found` | 10 | 0.23% | `amerusfinancial.com__blog, bb-whitening.com, busfinders.com__schools, caddyserver.com__install, dfwmuslimartists.com__artists-registration-form` |
| `adult_or_sensitive_keyword:bet,casino` | 9 | 0.21% | `agencasinosbobet.net, agencasinosbobet.net__nagad88-login-easy-access-guide-for-new-users, casinoreviews.nl__online-casino-nederland, casinoreviews.nl, dhankesariresults.in__hi` |
| `patch_10_replace_uncheckable_missing_output_code` | 9 | 0.21% | `amerusfinancial.com__blog, berkeleytherapist.net__areas-of-expertise, cannonparkdental.com__comprehensive-family-dentistry, carringtoninc.com__products, davidabramczyk.com__about-the-author` |
| `patch_9_search_not_found` | 8 | 0.18% | `amerusfinancial.com__blog, bb-whitening.com, busfinders.com__schools, frameworksuk.org__changing-the-story, galaxydentallaboratory.com__services` |
| `adult_or_sensitive_keyword:casino` | 7 | 0.16% | `1stok.com__bonus-offers, bitstarzcasinoaccess.com, casinoapp.eu__poker-apps, casinoapp.eu, heartfeltstamping.com` |
| `adult_or_sensitive_keyword:cam,dating` | 7 | 0.16% | `bcwriters.ca__About-the-FBCW, dana.ucc.nau.edu__online-degrees, datingupdates.org, datingupdates.org__print-templates, datingupdates.org__infographics` |
| `patch_11_replace_uncheckable_missing_output_code` | 7 | 0.16% | `berkeleytherapist.net__areas-of-expertise, cannonparkdental.com__comprehensive-family-dentistry, carringtoninc.com__products, davidabramczyk.com__about-the-author, givzey.com__integrations` |
| `adult_or_sensitive_keyword:adult,bet` | 5 | 0.12% | `LauraBrownAuthor.com__about, asdatoz.com__aboutus, cloudland.net__different-types-of-pipe-benders-and-learning-how-to-use-them, drstevemd.com, furaffinity.net` |
| `patch_12_replace_uncheckable_missing_output_code` | 5 | 0.12% | `berkeleytherapist.net__areas-of-expertise, cannonparkdental.com__comprehensive-family-dentistry, carringtoninc.com__products, davidabramczyk.com__about-the-author, havening.org__page_2` |
| `challenge_or_captcha:cloudflare` | 5 | 0.12% | `cherylschuermann.com__farmhouse-devotions, cherylschuermann.com__books, decoholic.org__beach-houses, decoholic.org__industrial-houses, decoholic.org__loft` |
| `adult_or_sensitive_keyword:bet,xxx` | 5 | 0.12% | `elizabethwrightart.com__about-elizabeth-wright, emblemthreads.com__blog, entitechsolutions.com__about, g2a-ltc.com__images, g2a-ltc.com__videos` |
| `patch_10_search_not_found` | 4 | 0.09% | `amerusfinancial.com__blog, givzey.com__integrations, guywh.com__naked-guy, hero173.com__1_5` |
| `patch_13_replace_uncheckable_missing_output_code` | 4 | 0.09% | `berkeleytherapist.net__areas-of-expertise, carringtoninc.com__products, davidabramczyk.com__about-the-author, havening.org__page_2` |
| `patch_14_replace_uncheckable_missing_output_code` | 4 | 0.09% | `berkeleytherapist.net__areas-of-expertise, carringtoninc.com__products, davidabramczyk.com__about-the-author, havening.org__page_2` |
| `adult_or_sensitive_keyword:bet,cam,dating` | 3 | 0.07% | `answersresearchjournal.org__early-church-fathers-genesis-debate, ashenburg.com__the-mourners-dance, freshfishfanatics.com__our-story` |
| `patch_15_replace_uncheckable_missing_output_code` | 3 | 0.07% | `berkeleytherapist.net__areas-of-expertise, carringtoninc.com__products, davidabramczyk.com__about-the-author` |
| `patch_16_replace_uncheckable_missing_output_code` | 3 | 0.07% | `berkeleytherapist.net__areas-of-expertise, carringtoninc.com__products, davidabramczyk.com__about-the-author` |
| `patch_17_replace_uncheckable_missing_output_code` | 3 | 0.07% | `berkeleytherapist.net__areas-of-expertise, carringtoninc.com__products, davidabramczyk.com__about-the-author` |
| `adult_or_sensitive_keyword:bet,cam,cams` | 3 | 0.07% | `blog.travelvictoria.com.au__accommodation-booking-scams, camstudio.org, camstudio.org__documentation` |
| `challenge_or_captcha:enable javascript` | 3 | 0.07% | `codeswithsam.com__contact, enable-javascript.com__en, exponentwptheme.com` |
| `placeholder_or_parked:this domain` | 3 | 0.07% | `deepnudeapps.com__disclaimer, digitalmarkeeter.com__privacy-policy, genecrypt.io` |
| `adult_or_sensitive_keyword:adult,bet,cam,cams,dating` | 2 | 0.05% | `adultchatdatingsites.com__stripchat, besthookupsites.org` |
| `patch_0_search_ambiguous_2` | 2 | 0.05% | `ancestralconstellations.com__writing-blog, consigmar-hellas.com` |
| `adult_or_sensitive_keyword:porn` | 2 | 0.05% | `arktan.com__best-ai-porn-generators, hentaied.com` |
| `patch_5_search_ambiguous_2` | 2 | 0.05% | `basilwoodsinternational.in__about-us-2, confluencebrewing.com__about` |
| `patch_18_replace_uncheckable_missing_output_code` | 2 | 0.05% | `berkeleytherapist.net__areas-of-expertise, davidabramczyk.com__about-the-author` |
| `patch_19_replace_uncheckable_missing_output_code` | 2 | 0.05% | `berkeleytherapist.net__areas-of-expertise, davidabramczyk.com__about-the-author` |
| `patch_20_replace_uncheckable_missing_output_code` | 2 | 0.05% | `berkeleytherapist.net__areas-of-expertise, davidabramczyk.com__about-the-author` |
| `patch_21_replace_uncheckable_missing_output_code` | 2 | 0.05% | `berkeleytherapist.net__areas-of-expertise, davidabramczyk.com__about-the-author` |
| `adult_or_sensitive_keyword:bet,betting,casino` | 2 | 0.05% | `betwinner-bd.com__login, betwinner-bd.com__promotions` |
| `adult_or_sensitive_keyword:cam,webcam` | 2 | 0.05% | `camtect.com, camtect.com__webcam-hijacking` |
| `adult_or_sensitive_keyword:dating,hookup` | 2 | 0.05% | `casualrelationships.net__near-me, datingrating.net` |
| `placeholder_or_parked:under construction` | 2 | 0.05% | `cinni.net__books, gzlandsons.com__under-construction` |
| `adult_or_sensitive_keyword:cam,cams` | 2 | 0.05% | `collegeadmissionsmadesimple.com__college-application-essays, flexitfl.com__pledge` |
| `adult_or_sensitive_keyword:dating,hookup,sex` | 2 | 0.05% | `datingreviewer.net__benaughty-review, datingreviewer.net__plentyoffish-review` |
| `adult_or_sensitive_keyword:bet,nude` | 2 | 0.05% | `deepnudeapps.com__disclaimer, deepnudeapps.com__why-deepnude-was-created` |
| `adult_or_sensitive_keyword:bet,cam,sex` | 2 | 0.05% | `durbnpoisn.com__blog, fixington.com__plumbers` |
| `patch_0_search_ambiguous_3` | 2 | 0.05% | `fracturedprunenj.com__three-locations, foragerchef.com__beef-tagliata-chive-blossom-dressing` |
| `placeholder_or_parked:placeholder,this domain` | 2 | 0.05% | `gaiageld.com, getmoredoneatwork.com` |
| `patch_11_search_not_found` | 2 | 0.05% | `givzey.com__integrations, guywh.com__naked-guy` |
| `adult_or_sensitive_keyword:porn,sex,xxx` | 1 | 0.02% | `1teenporn.com` |
| `adult_or_sensitive_keyword:erotic` | 1 | 0.02% | `albertwein.com__gallery` |
| `adult_or_sensitive_keyword:bet,cam,casino` | 1 | 0.02% | `apppearl.com__kontakt-oss` |
| `adult_or_sensitive_keyword:adult,porn` | 1 | 0.02% | `arktan.com__ai-videos` |
| `adult_or_sensitive_keyword:adult,cam` | 1 | 0.02% | `astunit.com__astunit_tutorial` |
| `adult_or_sensitive_keyword:bet,bets,betting,casino,gambling` | 1 | 0.02% | `attitudewalastatus.com__terms` |
| `patch_1_search_ambiguous_7` | 1 | 0.02% | `auroraevansville.org__find-help` |
| `adult_or_sensitive_keyword:bet,erotic,nude,nudes,porn` | 1 | 0.02% | `baddieschicks.com__isabelle-eleanore-betrays-her-husband-with-his-buddy` |
| `adult_or_sensitive_keyword:cam,casino,sex` | 1 | 0.02% | `basicincome.org.uk__coincasino-pro` |
| `patch_22_replace_uncheckable_missing_output_code` | 1 | 0.02% | `berkeleytherapist.net__areas-of-expertise` |
| `patch_23_replace_uncheckable_missing_output_code` | 1 | 0.02% | `berkeleytherapist.net__areas-of-expertise` |
| `patch_24_replace_uncheckable_missing_output_code` | 1 | 0.02% | `berkeleytherapist.net__areas-of-expertise` |
| `patch_25_replace_uncheckable_missing_output_code` | 1 | 0.02% | `berkeleytherapist.net__areas-of-expertise` |
| `adult_or_sensitive_keyword:bet,betting,casino,gambling` | 1 | 0.02% | `betmeister.net__about` |
| `adult_or_sensitive_keyword:bet,betting,gambling` | 1 | 0.02% | `betmeister.net__nba-player-props-betting-guide` |
| `adult_or_sensitive_keyword:nude` | 1 | 0.02% | `blog.dearsundays.com__best-nude-nail-polish-shades-for-every-skin-tone-a-clean-beauty-guide` |
| `adult_or_sensitive_keyword:cam,casino` | 1 | 0.02% | `blogfinger.net__feed` |
| `patch_6_search_ambiguous_2` | 1 | 0.02% | `budgetodorremoval.com__tobacco-smoke-odor` |
| `patch_7_search_ambiguous_2` | 1 | 0.02% | `budgetodorremoval.com__tobacco-smoke-odor` |
| `adult_or_sensitive_keyword:adult,bet,cam` | 1 | 0.02% | `campostonline.com__adult-game-sites` |
| `adult_or_sensitive_keyword:bet,cam,hookup` | 1 | 0.02% | `campostonline.com__hookup-sites` |
| `adult_or_sensitive_keyword:adult,bet,cam,webcam` | 1 | 0.02% | `campostonline.com__adult-webcam-sites` |
| `adult_or_sensitive_keyword:bet,hookup,sex` | 1 | 0.02% | `casualrelationships.net__hookup-near-me` |
| `adult_or_sensitive_keyword:adult,dating` | 1 | 0.02% | `community.chatchecks.com__local` |
| `patch_4_search_ambiguous_2` | 1 | 0.02% | `confluencebrewing.com__about` |
| `patch_1_search_ambiguous_2` | 1 | 0.02% | `connectabq.org__default` |
| `adult_or_sensitive_keyword:gambling` | 1 | 0.02% | `cricketmcwguide.com__for-age-18-and-above-only` |
| `adult_or_sensitive_keyword:bet,dating,hookup,sex` | 1 | 0.02% | `datingreviewer.net__coffeemeetsbagel-review` |
| `patch_20_search_not_found` | 1 | 0.02% | `davidabramczyk.com__about-the-author` |
| `patch_21_search_not_found` | 1 | 0.02% | `davidabramczyk.com__about-the-author` |
| `placeholder_or_parked:coming soon,placeholder` | 1 | 0.02% | `dbtrashers.com__cart` |
| `adult_or_sensitive_keyword:escort,escorts` | 1 | 0.02% | `delhi-escorts-x.in__blog` |
| `adult_or_sensitive_keyword:adult,bet,sex` | 1 | 0.02% | `denverjacks.com__page_4` |
| `adult_or_sensitive_keyword:adult,bet,dating` | 1 | 0.02% | `disabilitease.com__handicapped-equipment` |
| `adult_or_sensitive_keyword:escort` | 1 | 0.02% | `elitekaya.com__escort-jobs-for-girls` |
| `patch_2_search_ambiguous_2` | 1 | 0.02% | `flchampton.com__life-groups` |
| `patch_3_search_ambiguous_2` | 1 | 0.02% | `flchampton.com__life-groups` |
| `adult_or_sensitive_keyword:bet,betting` | 1 | 0.02% | `g3newswire.com__sports-betting` |
| `adult_or_sensitive_keyword:bet,betting,casino,dating,gambling` | 1 | 0.02% | `gamblingappsstore.com__compare` |
| `adult_or_sensitive_keyword:bet,cam,webcam` | 1 | 0.02% | `guywh.com__naked-guy` |
| `adult_or_sensitive_keyword:bet,cam,nude,webcam` | 1 | 0.02% | `guywh.com__nude-leaks` |

### image-repair

- total: 4845

| issue | count | ratio | examples |
|---|---:|---:|---|
| `missing_output_files` | 4845 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `patch_0_replace_uncheckable_missing_output_code` | 4845 | 100.00% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 10legsinthekitchen.com__staceybender, 01simple.com__world` |
| `remote_url_present` | 2715 | 56.04% | `1staab.com__quotes, 1staab.com__digital-art, 10-twenty.ca__seo, 01simple.com__world, 01logix.com__mspowerbi` |
| `placeholder_or_parked:placeholder` | 1080 | 22.29% | `01logix.com__mspowerbi, 2derms.com__contact, 2canoes.com__retouching-services, 2canoes.com__faq, 01logix.com__ad-linked` |
| `challenge_or_captcha:captcha` | 962 | 19.86% | `01logix.com__mspowerbi, 01logix.com__ad-linked, 01logix.com__microsoft-sharepoint-online-partner, 4master.nl__over-4master, 8dayhomesale.com` |
| `adult_or_sensitive_keyword:bet` | 792 | 16.35% | `01simple.com__world, 01simple.com__immigration, 01simple.com__realestate, 3dcomenius.com, 4thfloorjournal.co.nz__submissions-guidelines` |
| `missing_dst_screenshot` | 278 | 5.74% | `10legsinthekitchen.com__staceybender, 2fast2die.com__reviews, 4leggedflix.com__faq, AllThingsAcoustic.org__contact, NeoK12.com__games` |
| `patch_0_search_not_found` | 187 | 3.86% | `10legsinthekitchen.com__staceybender, 2fast2die.com__reviews, 4leggedflix.com__faq, AllThingsAcoustic.org__contact, NeoK12.com__games` |
| `adult_or_sensitive_keyword:cam` | 145 | 2.99% | `50skyshades.com__blogs, 50skyshades.com, actionsdg.ctb.ku.edu__cookie-policy, actionsdg.ctb.ku.edu, actionskills.co` |
| `risky_domain_from_instance_id` | 97 | 2.00% | `adoptionformsexpress.com__terms-of-use, adoptionformsexpress.com__privacy-policy, adoptionformsexpress.com, agencasinosbobet.net__admin, agencasinosbobet.net__mpo500-slot-game-review-and-winning-tips` |
| `patch_0_search_ambiguous_2` | 61 | 1.26% | `aaronlee.co, aiblifescience.com__cart, allied-eng.com__careers, alternativepac.us__join, ar2021.lovingheartjurong.org.sg__about-us` |
| `patch_1_replace_uncheckable_missing_output_code` | 58 | 1.20% | `24sevenfaith.com__workplace-wisdom, 3hundredtraining.com__39-2, aamd.org, aapatsahaaya.org__about, adkbrewery.com__story` |
| `adult_or_sensitive_keyword:bet,cam` | 32 | 0.66% | `alok-mishra.net__moving-for-moksha-my-latest-poetry-collection-is-out, alok-mishra.net__alok-mishra-creativity, alok-mishra.net__a-poem-a-day, ambientvisions.com, anchorbaptist1611.com__camp-2026` |
| `adult_or_sensitive_keyword:sex` | 29 | 0.60% | `accumulationofthings.com, activebacktohealth.com__blog, adoptionformsexpress.com__terms-of-use, adoptionformsexpress.com__privacy-policy, adoptionformsexpress.com` |
| `placeholder_or_parked:lorem ipsum` | 27 | 0.56% | `amos.im.alisoft.com, antaresproperties.ca, ben-p.de__about-me, authentictitle.com__buyers, bryonycrane.co.uk__older` |
| `adult_or_sensitive_keyword:xxx` | 18 | 0.37% | `2023.ravensbourne.ac.uk__about-ravensbourne, 2023.ravensbourne.ac.uk__concept-realisation, 8dayhomesale.com, 8dayhomesale.com__washington-dc, 8dayhomesale.com__baltimore` |
| `adult_or_sensitive_keyword:adult` | 17 | 0.35% | `LauraBrownAuthor.com__hearing-loss-resources, LauraBrownAuthor.com__my-books, LauraBrownAuthor.com__the-un-arranged-marriage, aspire.com.sg__the-guild-social-club, babywinkz.com__services` |
| `adult_or_sensitive_keyword:bet,sex` | 13 | 0.27% | `3s-selfstorage.com__faq, 96problems.com__we-vibe-instructions-and-manuals, 96problems.com__what-is-the-autoblow-history-reviews-and-critiques, 96problems.com, blog.aiesec.org__aiesec-at-unido-youth-innovation-and-partnerships-shaping-the-future` |
| `patch_2_replace_uncheckable_missing_output_code` | 10 | 0.21% | `adkbrewery.com__story, agathaschooler.com, alightcreative.com, avalon-enterprises.com__green-building, camstudio.org__faq` |
| `patch_0_search_ambiguous_3` | 9 | 0.19% | `MiamiLockAndKeys.com__locksmith-terms-and-conditions, andreworlowski.com__archive, centredevils.co.uk__transfer-news, chapelstreet.com.au__contact-us, chaseconsultants.com__about-chase` |
| `placeholder_or_parked:this domain` | 9 | 0.19% | `anvely.ca__privacy-policy, atoztopnews.com, bewellbyann.com, bsccareer.com, digitalmarkeeter.com__terms-of-service` |
| `adult_or_sensitive_keyword:bet,dating` | 8 | 0.17% | `alltopdating.com__black-dating, alltopdating.com__asian-dating, alltopdating.com__christian-dating, asianbridesonline.org__japanese-brides, bridesworldsite.com` |
| `adult_or_sensitive_keyword:dating` | 8 | 0.17% | `bc-lawyers.com.au, chainoflakesvet.com__reviews, coniferareacouncil.org__community-vision, cutcarbon.org.uk, datingproductsreview.com__ashley-madison-review` |
| `adult_or_sensitive_keyword:adult,bet` | 7 | 0.14% | `4gujarat.com__terms-of-service, aspire.com.sg__partner-with-us, bgassociates.com__business-case-boomer-marketing, debrahleecharatan.com__feed, disabilitease.com__handicapped-equipment` |
| `patch_1_search_not_found` | 7 | 0.14% | `age-of-product.com__agile-and-scrum, artechyapi.com__design-development, atsolutions.org__suggest-solution-ideas, bonsaimadesimple.com__three-late-winter-bonsai-tasks, bremerbrisbane.org.au` |
| `challenge_or_captcha:cloudflare` | 6 | 0.12% | `decoholic.org__interior-design-homes, eatwellspendsmart.com__subscribe, eatwellspendsmart.com__about, eatwellspendsmart.com, eatwellspendsmart.com__money-saving-tips` |
| `adult_or_sensitive_keyword:bet,casino` | 5 | 0.10% | `agencasinosbobet.net__admin, agencasinosbobet.net__mpo500-slot-game-review-and-winning-tips, casinoreviews.nl__fruitautomaten, daroniefoodclub.com, frische-daten.de__250-bonus` |
| `adult_or_sensitive_keyword:bet,xxx` | 5 | 0.10% | `emblemthreads.com__emtim-apparel-etsy-shop, emblemthreads.com__resources, emblemthreads.com__about, futurestepscreative.com, gatewaygazette.ca__gazette` |
| `adult_or_sensitive_keyword:bet,bets` | 5 | 0.10% | `freesuperbets.com__sport-news, freesuperbets.com__bookmakers, freesuperbets.com__et, hojopro.com__default_6, hojopro.com__default_2` |
| `adult_or_sensitive_keyword:bet,hookup` | 5 | 0.10% | `hookupinsiders.com__about, hookeepr.com__bdsm-hookup, hookupinsiders.com__nordvpn-subscription-plans, hookeepr.com__gay-hookup-sites, hookeepr.com__bbw-hookup-sites` |
| `patch_3_replace_uncheckable_missing_output_code` | 4 | 0.08% | `adkbrewery.com__story, avalon-enterprises.com__green-building, coworkbuffalo.com__agreement, hookupinsiders.com__nordvpn-subscription-plans` |
| `adult_or_sensitive_keyword:casino` | 4 | 0.08% | `1stok.com__privacy-policy, casinoapp.eu__blackjack-apps, fairgocasinoau.com, heartfeltstamping.com` |
| `placeholder_or_parked:lorem ipsum,placeholder` | 4 | 0.08% | `bikeforthecure.org__hiw, caselfreliance.org__california-cardroom-moratorium-bill-ab341-progresses-through-senate-amended-for-table-limit, caselfreliance.org__news, gildedgal.com__shop` |
| `adult_or_sensitive_keyword:cam,sex` | 3 | 0.06% | `alchetron.com__contact, brighamcason.com__feed, godmadeus.com__whichBible` |
| `adult_or_sensitive_keyword:bet,cam,cams` | 3 | 0.06% | `camstudio.org, camstudio.org__faq, camstudio.org__legacy` |
| `adult_or_sensitive_keyword:bet,betting,casino` | 3 | 0.06% | `casinoapp.eu__sports-betting, gbbet.co.uk__sportsbook-reviews, gbbet.co.uk__deposit-methods` |
| `patch_4_replace_uncheckable_missing_output_code` | 2 | 0.04% | `adkbrewery.com__story, coworkbuffalo.com__agreement` |
| `adult_or_sensitive_keyword:adult,bet,cam` | 2 | 0.04% | `ambientvisions.com__avsqanda, aspire.com.sg__aspire-infinite-experiential-camps` |
| `adult_or_sensitive_keyword:bet,cam,casino` | 2 | 0.04% | `apppearl.com__personvernerklaering, apppearl.com__om-oss` |
| `patch_0_search_ambiguous_5` | 2 | 0.04% | `beckermanlegal.com, gabrielheymans.com__contact` |
| `adult_or_sensitive_keyword:bet,casino,sex` | 2 | 0.04% | `betmentor.com__22bet-review, betmentor.com__melbet-review` |
| `challenge_or_captcha:captcha,enable javascript` | 2 | 0.04% | `caselfreliance.org__contact, drlisamarotta.com` |
| `adult_or_sensitive_keyword:adult,dating` | 2 | 0.04% | `cupidbrides.com__lithuanian-brides, datingjet.org__adult` |
| `adult_or_sensitive_keyword:escort,escorts` | 2 | 0.04% | `delhi-escorts-x.in__sadie, elitekaya.com__rates` |
| `challenge_or_captcha:enable javascript` | 2 | 0.04% | `enable-javascript.com__es, genesis-construction.com__connect` |
| `adult_or_sensitive_keyword:bet,cam,sex` | 2 | 0.04% | `fixington.com__plumbers, fixington.com__heating-engineers` |
| `adult_or_sensitive_keyword:cam,xxx` | 2 | 0.04% | `ftmanews.com__page_6, ftmanews.com__page_1` |
| `adult_or_sensitive_keyword:hookup` | 2 | 0.04% | `hookupsguru.com__size-guide-adidas-footwear, hookupsguru.com__return-policy` |
| `adult_or_sensitive_keyword:casino,gambling` | 1 | 0.02% | `1stok.com__online-slots` |
| `adult_or_sensitive_keyword:adult,bet,bets,betting,gambling` | 1 | 0.02% | `abitoarchitects.com` |
| `patch_5_replace_uncheckable_missing_output_code` | 1 | 0.02% | `adkbrewery.com__story` |
| `adult_or_sensitive_keyword:bet,casino,gambling` | 1 | 0.02% | `agencasinosbobet.net__gambling` |
| `adult_or_sensitive_keyword:cam,dating,porn,porno` | 1 | 0.02% | `alchetron.com__terms` |
| `adult_or_sensitive_keyword:porn` | 1 | 0.02% | `all-free-download.com__font` |
| `patch_0_search_ambiguous_543844` | 1 | 0.02% | `amaravillage.net__jackery-solarsaga-100w-solar-panel` |
| `patch_1_search_ambiguous_281` | 1 | 0.02% | `angel.co__overview` |
| `patch_0_search_ambiguous_331724` | 1 | 0.02% | `annabellenelson.com__books` |
| `patch_0_search_ambiguous_9656` | 1 | 0.02% | `anvely.ca__privacy-policy` |
| `patch_0_search_ambiguous_8` | 1 | 0.02% | `arhq.com__services` |
| `patch_0_search_ambiguous_896742` | 1 | 0.02% | `aspirecaregiving.com__specialized-care-programs` |
| `adult_or_sensitive_keyword:adult,cam` | 1 | 0.02% | `astunit.com` |
| `adult_or_sensitive_keyword:erotic,nude,porn,sex,xxx` | 1 | 0.02% | `baddieschicks.com__alannasworldx-takes-a-hard-fucking-post-workout` |
| `challenge_or_captcha:security check` | 1 | 0.02% | `basicincome.org.uk__betninja` |
| `adult_or_sensitive_keyword:cam,nude,nudes` | 1 | 0.02% | `bauerart.com__Mayan` |
| `adult_or_sensitive_keyword:adult,bet,dating,hookup` | 1 | 0.02% | `bestadulthookup.com__best-married-dating-sites` |
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
| `adult_or_sensitive_keyword:adult,dating,hookup` | 1 | 0.02% | `casualrelationships.net__adult` |
| `patch_0_search_ambiguous_4` | 1 | 0.02% | `chaplainsontheharbor.org__anime` |
| `patch_0_search_ambiguous_574473` | 1 | 0.02% | `clarkairservices.com__preventative-maintenance` |
| `adult_or_sensitive_keyword:cam,webcam` | 1 | 0.02% | `crossbrowdy.com__page_1` |
| `patch_0_search_ambiguous_913939` | 1 | 0.02% | `ctrlnetworks.com__contact-us` |
| `adult_or_sensitive_keyword:bet,cam,cams,dating` | 1 | 0.02% | `datingjet.com__myfreecams-review` |
| `adult_or_sensitive_keyword:dating,hookup,sex` | 1 | 0.02% | `datingreviewer.net__eharmony-review` |
| `adult_or_sensitive_keyword:dating,hookup` | 1 | 0.02% | `datingjet.org__hookup-apps` |
| `adult_or_sensitive_keyword:cam,dating` | 1 | 0.02% | `datingupdates.org__social-media` |
| `adult_or_sensitive_keyword:bet,dating,sex` | 1 | 0.02% | `datingjet.org` |
| `adult_or_sensitive_keyword:adult,bet,nude` | 1 | 0.02% | `deepnudeapps.com__bots` |
| `adult_or_sensitive_keyword:adult,bet,sex` | 1 | 0.02% | `denverjacks.com__page_4` |
| `patch_0_search_ambiguous_381248` | 1 | 0.02% | `deanclaytonwoo.com` |
| `patch_0_search_ambiguous_522021` | 1 | 0.02% | `dreameditionspress.com__my-cart` |
| `patch_0_search_ambiguous_3261` | 1 | 0.02% | `drivebywebsites.co.uk__responsive-website-development` |
| `placeholder_or_parked:under construction` | 1 | 0.02% | `dressesgalore.co.uk` |
| `patch_0_search_ambiguous_528734` | 1 | 0.02% | `eaglecapecod.com__contact-eagle-companies-inc` |
| `adult_or_sensitive_keyword:escort` | 1 | 0.02% | `elitekaya.com__escort-jobs-for-girls` |
| `adult_or_sensitive_keyword:dating,escort,escorts` | 1 | 0.02% | `elitekaya.com__contact-us` |
| `patch_0_search_ambiguous_408020` | 1 | 0.02% | `elitehc.net__sms-privacy-policy` |
| `adult_or_sensitive_keyword:adult,escort,escorts` | 1 | 0.02% | `englandescortdirectory.com__registration` |
| `adult_or_sensitive_keyword:bet,porn,porno` | 1 | 0.02% | `essentialsurvival.org__feed` |
| `patch_0_search_ambiguous_789253` | 1 | 0.02% | `eu-cnc.org__business` |
| `patch_0_search_ambiguous_314179` | 1 | 0.02% | `evesland.com__1081` |
| `patch_0_search_ambiguous_355935` | 1 | 0.02% | `familydentistryelpasotexas.com` |
| `patch_1_search_ambiguous_54` | 1 | 0.02% | `fortheloveofpeterentals.com__event-rental` |
| `adult_or_sensitive_keyword:bet,betting` | 1 | 0.02% | `g3newswire.com__sports-betting` |
| `adult_or_sensitive_keyword:bet,betting,casino,gambling` | 1 | 0.02% | `gamblingappsstore.com` |
| `patch_0_search_ambiguous_293294` | 1 | 0.02% | `getasa2.com__your-account` |
| `adult_or_sensitive_keyword:bet,bets,casino` | 1 | 0.02% | `goharpc.com__golden-panda-casino` |
| `adult_or_sensitive_keyword:adult,sex` | 1 | 0.02% | `grabbysamerica.com` |
| `adult_or_sensitive_keyword:bet,cam,webcam` | 1 | 0.02% | `guywh.com__categories` |
| `patch_0_search_ambiguous_16424` | 1 | 0.02% | `hdizhi1.com__1_5` |

## 解读

- `likely_non_zh_en` / `likely_non_english_latin` / `likely_other_script`: 语言启发式，不替代人工或 fastText/langid，但适合作为第一轮剔除候选。
- `adult_or_sensitive_keyword:*` 和 `risky_domain_from_instance_id`: 域名、路径或页面文本命中成人/博彩/约会等风险词。
- `patch_*_search_not_found` / `patch_*_search_ambiguous_*`: patch 不能在输入代码中唯一匹配，edit/repair 监督不可靠。
- `image_repair_low_visual_diff`: repair 前后截图差异过小，可能是视觉无关 bug，也可能是不适合作为 image-repair 的样本。
- `remote_url_present`: 训练样本仍含远程 URL，需进一步区分允许的图片替代 URL与应本地化的资源。
