# Deep Release Quality Audit

Release root: `/data1/xieqianqian/webcoding/release_sft_6tasks_v1`

## Issue Counts

### image-edit.jsonl

| issue | count | ratio | examples |
|---|---:|---:|---|
| `patch_replace_uncheckable_missing_output_files` | 4333 | 100.00% | `1-keyworddomainnames.com__keyword-domains-for-sale`, `1-keyworddomainnames.com__keyword-domain-news`, `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `remote_url_present` | 4316 | 99.61% | `1-keyworddomainnames.com__keyword-domains-for-sale`, `1-keyworddomainnames.com__keyword-domain-news`, `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `loremflickr_placeholder_image` | 4293 | 99.08% | `1-keyworddomainnames.com__keyword-domains-for-sale`, `1-keyworddomainnames.com__keyword-domain-news`, `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `html_lang_attr_present` | 4149 | 95.75% | `1-keyworddomainnames.com__keyword-domains-for-sale`, `1-keyworddomainnames.com__keyword-domain-news`, `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `remote_image_src_or_srcset` | 4104 | 94.71% | `1-keyworddomainnames.com__keyword-domains-for-sale`, `1-keyworddomainnames.com__keyword-domain-news`, `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `remote_script_src` | 3934 | 90.79% | `1-keyworddomainnames.com__keyword-domains-for-sale`, `1-keyworddomainnames.com__keyword-domain-news`, `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `patch_search_not_found` | 3086 | 71.22% | `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support`, `10legsinthekitchen.com__recipes-2`, `1stok.com__bonus-offers` |
| `remote_or_web_font_reference` | 2311 | 53.33% | `10-twenty.ca__seo`, `10-twenty.ca`, `10bestbuy.com__travel`, `10kcards.com__support`, `10legsinthekitchen.com__recipes-2`, `1teenporn.com` |
| `missing_body_tag` | 1783 | 41.15% | `10-twenty.ca`, `1upretro.com__blog`, `21ilab.com`, `2daybusinessinfo.com__technology`, `2nvr.org.au`, `2adt.com__about` |
| `patch_search_too_short_lt_20` | 1094 | 25.25% | `10-twenty.ca__seo`, `1stok.com__bonus-offers`, `1teenporn.com`, `22fusion.com`, `1upretro.com__blog`, `21ilab.com` |
| `remote_iframe_src` | 866 | 19.99% | `1upretro.com__blog`, `21ilab.com`, `3cuvw.de__hornschuch-promenade`, `3mdrivingschool.com.au__reviews`, `3mdrivingschool.com.au`, `4thfloorcreative.com` |
| `bad_src_or_srcset_null_hash` | 391 | 9.02% | `1stok.com__bonus-offers`, `3-day-trial.uk__disclaimer`, `AlexandriaLocalLocksmith.com`, `Garage-Door-Mobile-Service-Repair.com__garage-door-price-list`, `Five-StarLock.com`, `HartfordLockAndKey.com` |
| `inline_event_handler_present` | 391 | 9.02% | `24sevenfaith.com__consulting`, `3-day-trial.uk__disclaimer`, `4leggedflix.com`, `51deguo.com`, `51deguo.com__member`, `51deguo.com__search` |
| `remote_stylesheet_href` | 336 | 7.75% | `10kcards.com__support`, `10legsinthekitchen.com__recipes-2`, `LauraBrownAuthor.com__about`, `aaagaragedoorservice.com__automatic-garage-door-repair`, `aaagaragedoorservice.com__overhead-garage-door-repair`, `aberdeengate.com__custom-gate-process-prices` |
| `dangerous_href_or_src_protocol` | 236 | 5.45% | `2x2blog.com__about-us`, `51deguo.com`, `51deguo.com__member`, `51deguo.com__search`, `51deguo.com__space-username-cote`, `51deguo.com__space-username-sofunie` |
| `non_zh_en_html_lang_attr` | 203 | 4.68% | `3cuvw.de__hornschuch-promenade`, `abelpardo.com__actividad-docente`, `ablakszereles.com__kapcsolat`, `ablakszereles.com__ablak-felujitas`, `agence-francaise-pour-la-creation-numerique.fr`, `agintech.eu` |
| `missing_html_lang_attr` | 184 | 4.25% | `22fusion.com`, `24-news.net__sellers`, `51deguo.com`, `51deguo.com__member`, `51deguo.com__search`, `51deguo.com__space-username-cote` |
| `input_images_image_file_missing` | 76 | 1.75% | `atozsports.com__miami-dolphins-news`, `anniedashstudios.com__gallery`, `alternativestocollege.com__technology`, `barneyslv.com__events`, `auribuzz.com__ccaurifil`, `blackdogpottery.ca__straight-sided-mugs` |
| `src_screenshot_image_file_missing` | 76 | 1.75% | `atozsports.com__miami-dolphins-news`, `anniedashstudios.com__gallery`, `alternativestocollege.com__technology`, `barneyslv.com__events`, `auribuzz.com__ccaurifil`, `blackdogpottery.ca__straight-sided-mugs` |
| `challenge_or_access_denied_text` | 44 | 1.02% | `51deguo.com__member`, `allproautobodyca.com__7-collision-assist`, `au.help.yahoo.com__search-for-desktop`, `au.help.yahoo.com__account`, `barbararaisbeck.com__india-collection`, `bangkoknoimodel.com` |
| `low_visible_text_lt_80` | 38 | 0.88% | `aimankabli.com__prof12`, `aimankabli.com__prof15`, `alabamamga.org__local-associations`, `allsoftwaredeals.com__travel`, `altfundmanagement.com__our-team`, `appareo.com__aviation` |
| `error_or_default_server_page_text` | 23 | 0.53% | `24-news.net__sellers`, `abrasives4sale.com__promotion`, `bangau188.com__privacy-policy`, `benharri.org__notes`, `biblicalcounsellingafrica.com__local-events`, `blog.haohtml.com__linux` |
| `adult_casino_dating_risky_instance_id` | 19 | 0.44% | `arktan.com__best-ai-porn-generators`, `betmeister.net__nba-player-props-betting-guide`, `blog.dearsundays.com__best-nude-nail-polish-shades-for-every-skin-tone-a-clean-beauty-guide`, `bridesworldsite.com__polish-dating`, `bridesworldsite.com__ukrainian-dating`, `campostonline.com__adult-game-sites` |
| `patch_search_ambiguous` | 10 | 0.23% | `ancestralconstellations.com__writing-blog`, `auroraevansville.org__find-help`, `basilwoodsinternational.in__about-us-2`, `budgetodorremoval.com__tobacco-smoke-odor`, `confluencebrewing.com__about`, `connectabq.org__default` |
| `remote_media_src` | 9 | 0.21% | `algamchina.com__pinfo`, `arktan.com__ai-videos`, `bulboaca.com__bulboaca-strategic-advisory`, `bulboaca.com__for-experienced-professionals`, `bulboaca.com__our-team`, `eguruji.com__calculation-mastery-course` |
| `parked_or_placeholder_page_text` | 8 | 0.18% | `airenergycorp.com`, `bb-whitening.com`, `blazers-n-hull.com__privacy-policy`, `cinni.net__books`, `grundco.com__seismic-retrofitting`, `gwxtreamtraffic.com` |
| `picsum_image_residual` | 5 | 0.12% | `art19.com__login`, `art19.com__advertisers`, `dbtrashers.com__about-us`, `dbtrashers.com__cart`, `ebolgo.com__advertise-here` |
| `very_few_html_tags` | 4 | 0.09% | `community.oerproject.com`, `frankbuck.org__about-us`, `frankbuck.org__contact`, `frankbuck.org__resources` |
| `patch_empty_replace` | 3 | 0.07% | `aparchitect.ca`, `dailythemecrosswordanswers.com`, `harmonycatering.ie__reviews` |
| `input_images_image_file_empty` | 1 | 0.02% | `china-tips.com__archive-source-from-china-tips-represents-vip-combo-ticket` |
| `src_screenshot_image_file_empty` | 1 | 0.02% | `china-tips.com__archive-source-from-china-tips-represents-vip-combo-ticket` |

### image-generate.jsonl

| issue | count | ratio | examples |
|---|---:|---:|---|
| `remote_url_present` | 9671 | 99.00% | `01simple.com__139738`, `01simple.com__immigration`, `1-box.com`, `1-keyworddomainnames.com`, `1-keyworddomainnames.com__feed`, `10-twenty.ca` |
| `loremflickr_placeholder_image` | 9618 | 98.45% | `01simple.com__139738`, `01simple.com__immigration`, `1-box.com`, `1-keyworddomainnames.com`, `10-twenty.ca`, `10kcards.com__login` |
| `remote_image_src_or_srcset` | 9221 | 94.39% | `01simple.com__139738`, `01simple.com__immigration`, `1-box.com`, `1-keyworddomainnames.com`, `10-twenty.ca`, `10kcards.com__login` |
| `html_lang_attr_present` | 9042 | 92.56% | `01simple.com__139738`, `01simple.com__immigration`, `1-box.com`, `1-keyworddomainnames.com`, `10-twenty.ca`, `10kcards.com__login` |
| `remote_script_src` | 8896 | 91.06% | `01simple.com__139738`, `01simple.com__immigration`, `1-box.com`, `1-keyworddomainnames.com`, `10-twenty.ca`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches` |
| `missing_body_tag` | 3729 | 38.17% | `10-twenty.ca`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches`, `1stteamweb.com__portfolio`, `1upretro.com__faq`, `2canoes.com__lr-smart-previews-tutorial`, `2daybusinessinfo.com__forex` |
| `remote_or_web_font_reference` | 3146 | 32.20% | `01simple.com__139738`, `01simple.com__immigration`, `10-twenty.ca`, `1staab.com__privacy-policy`, `1staab.com__quotes`, `24sevenfaith.com__north-of-60` |
| `inline_event_handler_present` | 998 | 10.22% | `01simple.com__139738`, `01simple.com__immigration`, `24sevenfaith.com__north-of-60`, `24sevenfaith.com__speaking`, `2derms.com__edward-searle`, `3-day-trial.uk` |
| `missing_html_lang_attr` | 727 | 7.44% | `1-keyworddomainnames.com__feed`, `50skyshades.com__login`, `LaserTraining.org__Aesthetic`, `abroadplanet.com__contact`, `adkbrewery.com__beer`, `adkbrewery.com__menu` |
| `dangerous_href_or_src_protocol` | 652 | 6.67% | `1staab.com__privacy-policy`, `1staab.com__quotes`, `ENHYPEN.com__ENHYPEN`, `LaserTraining.org__Aesthetic`, `ace-transportation.com__10`, `aknarayanassociates.com__whatsnew` |
| `non_zh_en_html_lang_attr` | 476 | 4.87% | `ablakszereles.com__ajanlatkeres`, `agence-francaise-pour-la-creation-numerique.fr__contactez-nous`, `alain-cousin.fr__petites-histoires-eole-et-les-vents`, `alteradomi.com__altera-domi-engels`, `alteradomi.com__altera-domi-frans`, `alteradomi.com__slide-anything-popup-preview` |
| `challenge_or_access_denied_text` | 137 | 1.40% | `accountingtaxespayroll.com__resources`, `achm.org__education`, `acmconstructionmanagement.com__general-contracting-project-management`, `advancetreeandshrub.com__tree-shrub-key-benefits-of-insect-disease-control`, `akelab.com`, `alvarezsearch.com__your-focusedfit-profile` |
| `low_visible_text_lt_80` | 88 | 0.90% | `50skyshades.com__login`, `aic1minute.com`, `aliikayaks.com`, `amgreatness.com`, `arungopidas.com__mentions`, `befriendingdragons.com__services` |
| `error_or_default_server_page_text` | 49 | 0.50% | `centminmod.com__faq`, `davidromano.com__abstract`, `eandireview.com__collection-kits-biologistics-and-clinical-supplies`, `eandireview.com__protocol-writing_-management-reporting-services`, `gunhansancar.com__pembayaran`, `hearinggp.co.za__jhouse_co` |
| `adult_casino_dating_risky_instance_id` | 29 | 0.30% | `alltopdating.com__country-dating`, `best-bitcoin-casino.eu`, `blog.photofeeler.com__online-dating`, `bridesworldsite.com__ukrainian-dating`, `datingjet.org__casual-dating`, `delhi-escorts-x.in__margo` |
| `remote_stylesheet_href` | 24 | 0.25% | `arapahoetennisclub.net`, `backspaceink.com__carpet_creatures_tales_from_the_deep_pile`, `backspaceink.com__portfolio`, `christiankrauter.com__blog`, `christiankrauter.com__releases`, `mossbuildingsystems.com__contact` |
| `remote_media_src` | 19 | 0.19% | `bulboaca.com__legal-services`, `connectivitycounselling.com`, `decryptedmatrix.com__space-et-ufo`, `oceanonedesign.com__page_1`, `panacea-nmr.eu`, `pnwomensrefuge.org.nz` |
| `parked_or_placeholder_page_text` | 18 | 0.18% | `hvaclakewoodco.com`, `jmkarchitects.com__our-firm`, `jovanapopic.com__works`, `mintleafdentalcare.com`, `morbidyne.com`, `nasaos.org__members` |
| `code_too_short_lt_500` | 12 | 0.12% | `larugayoga.com__ashtanga-yoga-retreats-2`, `pinecast.com__features`, `www.chooseporn.com__asian`, `www.cs.wm.edu__page_1`, `www.dromic.com__graph-viewer`, `www.edu-con.de__leistungen` |
| `remote_iframe_src` | 11 | 0.11% | `CranfordLocksmithService.com`, `Five-StarLock.com`, `HartfordLockAndKey.com`, `PlymouthMeetingLocksmithService.com`, `chemistrysimplified.com__beauty-insider-blog`, `drcandicesilverman.com.au__operating-times` |
| `very_few_html_tags` | 8 | 0.08% | `community.oerproject.com__teacher-s-lounge`, `www.ejmiral.com__about-us`, `www.ejmiral.com__ejmiral`, `www.followchain.org`, `www.oaf.org.au__donate`, `www.sprocketrocket.co__stack` |
| `bad_src_or_srcset_null_hash` | 3 | 0.03% | `motherson.com__business-divisions`, `www.katesmathlessons.com`, `www.katesmathlessons.com__contact` |
| `picsum_image_residual` | 1 | 0.01% | `pir-resourcing.com__employer-spotlight` |
| `missing_html_tag` | 1 | 0.01% | `www.sprocketrocket.co__stack` |

### image-repair.jsonl

| issue | count | ratio | examples |
|---|---:|---:|---|
| `patch_replace_uncheckable_missing_output_files` | 4845 | 100.00% | `1staab.com__quotes`, `1staab.com__digital-art`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `remote_url_present` | 4815 | 99.38% | `1staab.com__quotes`, `1staab.com__digital-art`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `loremflickr_placeholder_image` | 4781 | 98.68% | `1staab.com__quotes`, `1staab.com__digital-art`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `remote_image_src_or_srcset` | 4560 | 94.12% | `1staab.com__quotes`, `1staab.com__digital-art`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `html_lang_attr_present` | 4548 | 93.87% | `1staab.com__quotes`, `1staab.com__digital-art`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `remote_script_src` | 4338 | 89.54% | `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi`, `24-news.net__ip`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches` |
| `remote_or_web_font_reference` | 2566 | 52.96% | `1staab.com__quotes`, `1staab.com__digital-art`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `missing_body_tag` | 1916 | 39.55% | `10legsinthekitchen.com__staceybender`, `01logix.com__mspowerbi`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches`, `10legsinthekitchen.com__about`, `10legsinthekitchen.com__blog-journal-index`, `2canoes.com__retouching-services` |
| `remote_iframe_src` | 920 | 18.99% | `01logix.com__mspowerbi`, `2canoes.com__retouching-services`, `2canoes.com__faq`, `1st-drainage-tewkesbury.co.uk__gallery`, `01logix.com__ad-linked`, `37thcasa.net` |
| `inline_event_handler_present` | 449 | 9.27% | `01simple.com__world`, `01simple.com__immigration`, `24sevenfaith.com`, `2derms.com__contact`, `01simple.com__realestate`, `24sevenfaith.com__workplace-wisdom` |
| `remote_stylesheet_href` | 387 | 7.99% | `10legsinthekitchen.com__staceybender`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches`, `10legsinthekitchen.com__about`, `10kcards.com__pricing`, `10legsinthekitchen.com__blog-journal-index`, `2derms.com__contact` |
| `bad_src_or_srcset_null_hash` | 383 | 7.91% | `1stok.com__online-slots`, `2derms.com__contact`, `3-day-trial.uk__disclaimer`, `3-day-trial.uk__privacy-policy`, `3dcomenius.com`, `ColumbusLocalLocksmith.com` |
| `missing_html_lang_attr` | 297 | 6.13% | `24-news.net__ip`, `NeoK12.com__games`, `NeoK12.com`, `OilFans.com__schedule`, `NeoK12.com__presentations`, `OilFans.com__schedule_2` |
| `dangerous_href_or_src_protocol` | 289 | 5.96% | `1staab.com__quotes`, `1staab.com__digital-art`, `4gujarat.com__terms-of-service`, `ENHYPEN.com__page_5`, `LauraBrownAuthor.com__hearing-loss-resources`, `LauraBrownAuthor.com__my-books` |
| `image_repair_missing_dst_screenshot` | 278 | 5.74% | `10legsinthekitchen.com__staceybender`, `2fast2die.com__reviews`, `4leggedflix.com__faq`, `AllThingsAcoustic.org__contact`, `NeoK12.com__games`, `VancouverLocksmithStore.com__locksmith-terms-and-conditions` |
| `image_repair_partial_success_src_only` | 278 | 5.74% | `10legsinthekitchen.com__staceybender`, `2fast2die.com__reviews`, `4leggedflix.com__faq`, `AllThingsAcoustic.org__contact`, `NeoK12.com__games`, `VancouverLocksmithStore.com__locksmith-terms-and-conditions` |
| `non_zh_en_html_lang_attr` | 212 | 4.38% | `GoriLaw.Com__es`, `Vendata.org`, `abelpardo.com__abel-pardo`, `ablakszereles.com__kiszallasi-teruletek`, `acidicmathz.com__cost`, `acidicmathz.com__kaizoudo` |
| `patch_search_not_found` | 189 | 3.90% | `10legsinthekitchen.com__staceybender`, `2fast2die.com__reviews`, `4leggedflix.com__faq`, `AllThingsAcoustic.org__contact`, `NeoK12.com__games`, `VancouverLocksmithStore.com__locksmith-terms-and-conditions` |
| `patch_search_too_short_lt_20` | 107 | 2.21% | `aarontgrogg.com__portfolio`, `abounddesign.com__hungry-ghost-bread-northampton-ma`, `adoptionformsexpress.com__privacy-policy`, `affordablebailbonding.com__frequently-asked-questions`, `amaravillage.net__jackery-solarsaga-100w-solar-panel`, `angel.co__overview` |
| `patch_search_ambiguous` | 100 | 2.06% | `MiamiLockAndKeys.com__locksmith-terms-and-conditions`, `aaronlee.co`, `aiblifescience.com__cart`, `allied-eng.com__careers`, `alternativepac.us__join`, `amaravillage.net__jackery-solarsaga-100w-solar-panel` |
| `challenge_or_access_denied_text` | 73 | 1.51% | `accessaudio.com`, `accountingtaxespayroll.com__contact`, `accurixlabs.com`, `advancetreeandshrub.com__335`, `affordablebailbonding.com__frequently-asked-questions`, `artmoves.com` |
| `low_visible_text_lt_80` | 43 | 0.89% | `a3249sfdlasd.com`, `acdla.net__wp-login`, `albanymodernbodyart.com__after-care`, `all-freemagazines.com__2`, `allsoftwaredeals.com__e-commerce`, `allthebestradio.com__about` |
| `error_or_default_server_page_text` | 22 | 0.45% | `24-news.net__ip`, `abrasives4sale.com__rtp`, `abrasives4sale.com__promotion`, `abrasives4sale.com__game_2`, `abrasives4sale.com__register`, `brokenpencil.com` |
| `patch_empty_search` | 22 | 0.45% | `amaravillage.net__jackery-solarsaga-100w-solar-panel`, `annabellenelson.com__books`, `anvely.ca__privacy-policy`, `aspirecaregiving.com__specialized-care-programs`, `aaryavartt.com`, `3mdrivingschool.com.au__gallery` |
| `adult_casino_dating_risky_instance_id` | 19 | 0.39% | `agencasinosbobet.net__gambling`, `alltopdating.com__black-dating`, `alltopdating.com__asian-dating`, `alltopdating.com__christian-dating`, `bestadulthookup.com__best-married-dating-sites`, `casinoapp.eu__sports-betting` |
| `remote_media_src` | 12 | 0.25% | `algamchina.com__dealer`, `algamchina.com__news`, `algamchina.com__service`, `algamchina.com__pinfo`, `alightcreative.com`, `bulboaca.com__our-internship-program` |
| `parked_or_placeholder_page_text` | 7 | 0.14% | `airenergycorp.com`, `arbucklewildernesspark.com`, `blackoakcy.com`, `blazers-n-hull.com__privacy-policy`, `createadigitallife.com`, `dressesgalore.co.uk` |
| `input_images_image_file_empty` | 5 | 0.10% | `10legsinthekitchen.com__staceybender`, `arabicdetroit.com__local-news`, `china-tips.com__archive-source-from-china-tips-represents-double-ht-ft-matches`, `droidux.com__feed`, `formal-invitations.com__materials-for-diy-invitations` |
| `src_screenshot_image_file_empty` | 5 | 0.10% | `10legsinthekitchen.com__staceybender`, `arabicdetroit.com__local-news`, `china-tips.com__archive-source-from-china-tips-represents-double-ht-ft-matches`, `droidux.com__feed`, `formal-invitations.com__materials-for-diy-invitations` |
| `picsum_image_residual` | 5 | 0.10% | `dea.nbird.com.au__hamdashboard`, `ebolgo.com__playful-teaching-gaining-credibility-say-lego-researchers`, `ebolgo.com__ai-guided-competitive-docking-for-virtual-screening-and-compound-efficacy-prediction`, `ebolgo.com__stratasys-launches-multi-material-3d-printed-model-preset-for-dental-training`, `ebolgo.com` |
| `very_few_html_tags` | 3 | 0.06% | `community.oerproject.com__big-history`, `corsalis.com__actualites`, `frankbuck.org__resources` |
| `code_too_short_lt_500` | 2 | 0.04% | `ahmedshareef.com`, `cuts.diamond.mlb.com` |
| `dst_screenshot_image_file_empty` | 2 | 0.04% | `arabicdetroit.com__local-news`, `china-tips.com__archive-source-from-china-tips-represents-double-ht-ft-matches` |

### text-edit.jsonl

| issue | count | ratio | examples |
|---|---:|---:|---|
| `patch_replace_uncheckable_missing_output_files` | 4333 | 100.00% | `1-keyworddomainnames.com__keyword-domain-news`, `1-keyworddomainnames.com__keyword-domains-for-sale`, `10-twenty.ca`, `10-twenty.ca__seo`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `remote_url_present` | 4293 | 99.08% | `1-keyworddomainnames.com__keyword-domain-news`, `1-keyworddomainnames.com__keyword-domains-for-sale`, `10-twenty.ca`, `10-twenty.ca__seo`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `picsum_image_residual` | 4193 | 96.77% | `1-keyworddomainnames.com__keyword-domain-news`, `1-keyworddomainnames.com__keyword-domains-for-sale`, `10-twenty.ca`, `10-twenty.ca__seo`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `html_lang_attr_present` | 4149 | 95.75% | `1-keyworddomainnames.com__keyword-domain-news`, `1-keyworddomainnames.com__keyword-domains-for-sale`, `10-twenty.ca`, `10-twenty.ca__seo`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `remote_image_src_or_srcset` | 4102 | 94.67% | `1-keyworddomainnames.com__keyword-domain-news`, `1-keyworddomainnames.com__keyword-domains-for-sale`, `10-twenty.ca`, `10-twenty.ca__seo`, `10bestbuy.com__travel`, `10kcards.com__support` |
| `patch_search_not_found` | 3035 | 70.04% | `10-twenty.ca`, `10-twenty.ca__seo`, `1stok.com__bonus-offers`, `24-news.net__sellers`, `3-l.org__child-development`, `3-l.org__learning-news` |
| `remote_or_web_font_reference` | 2539 | 58.60% | `10-twenty.ca`, `10-twenty.ca__seo`, `10bestbuy.com__travel`, `10kcards.com__support`, `10legsinthekitchen.com__recipes-2`, `1teenporn.com` |
| `missing_body_tag` | 2095 | 48.35% | `10-twenty.ca`, `10-twenty.ca__seo`, `10legsinthekitchen.com__recipes-2`, `1upretro.com__blog`, `21ilab.com`, `2adt.com__about` |
| `patch_search_too_short_lt_20` | 1094 | 25.25% | `10-twenty.ca__seo`, `1stok.com__bonus-offers`, `1teenporn.com`, `1upretro.com__blog`, `21ilab.com`, `22fusion.com` |
| `remote_iframe_src` | 864 | 19.94% | `1upretro.com__blog`, `21ilab.com`, `3cuvw.de__hornschuch-promenade`, `3mdrivingschool.com.au`, `3mdrivingschool.com.au__reviews`, `4thfloorcreative.com` |
| `bad_src_or_srcset_null_hash` | 386 | 8.91% | `1stok.com__bonus-offers`, `3-day-trial.uk__disclaimer`, `64kb.de__audio-interface`, `64kb.de__sd2iec-micro`, `AlexandriaLocalLocksmith.com`, `Five-StarLock.com` |
| `inline_event_handler_present` | 354 | 8.17% | `24sevenfaith.com__consulting`, `3-day-trial.uk__disclaimer`, `4leggedflix.com`, `51deguo.com`, `51deguo.com__member`, `51deguo.com__search` |
| `remote_stylesheet_href` | 336 | 7.75% | `10kcards.com__support`, `10legsinthekitchen.com__recipes-2`, `LauraBrownAuthor.com__about`, `aaagaragedoorservice.com__automatic-garage-door-repair`, `aaagaragedoorservice.com__overhead-garage-door-repair`, `aberdeengate.com__custom-gate-process-prices` |
| `non_zh_en_html_lang_attr` | 203 | 4.68% | `3cuvw.de__hornschuch-promenade`, `abelpardo.com__actividad-docente`, `ablakszereles.com__ablak-felujitas`, `ablakszereles.com__kapcsolat`, `agence-francaise-pour-la-creation-numerique.fr`, `agintech.eu` |
| `dangerous_href_or_src_protocol` | 193 | 4.45% | `2x2blog.com__about-us`, `51deguo.com`, `51deguo.com__member`, `51deguo.com__search`, `51deguo.com__space-username-cote`, `51deguo.com__space-username-sofunie` |
| `missing_html_lang_attr` | 184 | 4.25% | `22fusion.com`, `24-news.net__sellers`, `51deguo.com`, `51deguo.com__member`, `51deguo.com__search`, `51deguo.com__space-username-cote` |
| `remote_script_src` | 73 | 1.68% | `GoriLaw.Com__trust-funds`, `abhomesva.com__move-in-ready-homes`, `aimankabli.com__pro`, `aimankabli.com__prof12`, `aimankabli.com__prof15`, `all-free-download.com` |
| `challenge_or_access_denied_text` | 45 | 1.04% | `51deguo.com__member`, `au.help.yahoo.com__account`, `au.help.yahoo.com__search-for-desktop`, `barneyslv.com__prix-fixe-2`, `belvidere.org.uk__contact`, `belvoirlife.com__search` |
| `low_visible_text_lt_80` | 42 | 0.97% | `altfundmanagement.com__our-team`, `amanok.co.jp__domestic`, `arungopidas.com__blog`, `arungopidas.com__search`, `asap-com.fr__clients`, `atlantismagazine.net__eat` |
| `error_or_default_server_page_text` | 23 | 0.53% | `24-news.net__sellers`, `abrasives4sale.com__promotion`, `bangau188.com__privacy-policy`, `benharri.org__notes`, `biblicalcounsellingafrica.com__local-events`, `blog.haohtml.com__linux` |
| `adult_casino_dating_risky_instance_id` | 19 | 0.44% | `arktan.com__best-ai-porn-generators`, `betmeister.net__nba-player-props-betting-guide`, `blog.dearsundays.com__best-nude-nail-polish-shades-for-every-skin-tone-a-clean-beauty-guide`, `bridesworldsite.com__polish-dating`, `bridesworldsite.com__ukrainian-dating`, `campostonline.com__adult-game-sites` |
| `patch_search_ambiguous` | 10 | 0.23% | `ancestralconstellations.com__writing-blog`, `auroraevansville.org__find-help`, `basilwoodsinternational.in__about-us-2`, `budgetodorremoval.com__tobacco-smoke-odor`, `confluencebrewing.com__about`, `connectabq.org__default` |
| `parked_or_placeholder_page_text` | 8 | 0.18% | `airenergycorp.com`, `bb-whitening.com`, `blazers-n-hull.com__privacy-policy`, `cardsetter.com__featured`, `cinni.net__books`, `grundco.com__seismic-retrofitting` |
| `very_few_html_tags` | 6 | 0.14% | `basicincome.org.uk__coincasino-pro`, `community.oerproject.com`, `coronamegh.in__play`, `frankbuck.org__about-us`, `frankbuck.org__contact`, `frankbuck.org__resources` |
| `patch_empty_replace` | 3 | 0.07% | `aparchitect.ca`, `dailythemecrosswordanswers.com`, `harmonycatering.ie__reviews` |

### text-generate.jsonl

| issue | count | ratio | examples |
|---|---:|---:|---|
| `remote_url_present` | 4892 | 98.65% | `3dgroup.net__360-degree-feedback`, `2daybusinessinfo.com__forex`, `3dgroup.net__feedback-coaching`, `2daybusinessinfo.com__business`, `24-news.net`, `01logix.com` |
| `picsum_image_residual` | 4761 | 96.01% | `3dgroup.net__360-degree-feedback`, `2daybusinessinfo.com__forex`, `3dgroup.net__feedback-coaching`, `2daybusinessinfo.com__business`, `24-news.net`, `01logix.com` |
| `html_lang_attr_present` | 4698 | 94.74% | `3dgroup.net__360-degree-feedback`, `2daybusinessinfo.com__forex`, `3dgroup.net__feedback-coaching`, `2daybusinessinfo.com__business`, `24-news.net`, `01logix.com` |
| `remote_image_src_or_srcset` | 4632 | 93.41% | `3dgroup.net__360-degree-feedback`, `2daybusinessinfo.com__forex`, `3dgroup.net__feedback-coaching`, `2daybusinessinfo.com__business`, `24-news.net`, `01logix.com` |
| `remote_or_web_font_reference` | 2911 | 58.70% | `2daybusinessinfo.com__forex`, `2daybusinessinfo.com__business`, `24-news.net`, `01logix.com`, `DaytonLockAndKeys.com__commercial-locksmith`, `ColumbusLocalLocksmith.com__locksmith-terms-and-conditions` |
| `missing_body_tag` | 2345 | 47.29% | `3dgroup.net__360-degree-feedback`, `2daybusinessinfo.com__forex`, `3dgroup.net__feedback-coaching`, `2daybusinessinfo.com__business`, `24-news.net`, `01logix.com` |
| `remote_iframe_src` | 964 | 19.44% | `01logix.com`, `3mdrivingschool.com.au__about-us`, `3mdrivingschool.com.au__learner-drivers`, `3mdrivingschool.com.au__reviews`, `66southpearl.com__amenities`, `DaytonLockAndKeys.com__commercial-locksmith` |
| `bad_src_or_srcset_null_hash` | 440 | 8.87% | `MiamiLockAndKeys.com`, `RedwoodCityLocksmithStore.com`, `VancouverLocksmithStore.com`, `VanNuysLocksmithService.net__coupons-locksmith-service`, `a2zcarremoval.co.nz__about-us`, `VanNuysLocksmithService.net__residential-locksmith` |
| `remote_stylesheet_href` | 398 | 8.03% | `LauraBrownAuthor.com__my-books`, `LauraBrownAuthor.com__a-cruise-fling`, `aaagaragedoorservice.com`, `aberdeengate.com__specialty-gates-doors-iron-works`, `accuratedegrees.in__regular-courses`, `adolab.com__support` |
| `inline_event_handler_present` | 397 | 8.01% | `aaagaragedoorservice.com`, `accessaudio.com__page_1`, `actionforprimates.org`, `adlibitumcomic.com`, `adsfreedaily.com__14-ad-exchanges`, `adsfreedaily.com__40-accommodation` |
| `dangerous_href_or_src_protocol` | 303 | 6.11% | `8minutefitness.com`, `LauraBrownAuthor.com__my-books`, `LauraBrownAuthor.com__a-cruise-fling`, `actionforprimates.org`, `agendaweb.org__reading-exercises`, `alleft.com__about` |
| `missing_html_lang_attr` | 261 | 5.26% | `abroadplanet.com__help`, `adsfreedaily.com__14-ad-exchanges`, `adsfreedaily.com__18-affiliate-programs`, `adsfreedaily.com__40-accommodation`, `adsfreedaily.com__signup`, `adkbrewery.com__beer` |
| `non_zh_en_html_lang_attr` | 241 | 4.86% | `alain-cousin.fr__petite-histoire-les-heure`, `alteradomi.com__altera-domi-nederlands`, `annekebrouwer.nl__blog`, `arabicdetroit.com__contact-us`, `artworkinaction.com__01`, `ashui.com__english` |
| `remote_script_src` | 73 | 1.47% | `GoriLaw.Com__trust-funds`, `amberinstruments.com__privacy-cookies-policy`, `arunnn.com__designing`, `axeetech.com__how-to`, `backspaceink.com__carpet_creatures_tales_from_the_deep_pile`, `berlin95diner.ca` |
| `challenge_or_access_denied_text` | 58 | 1.17% | `accessaudio.com__page_1`, `carolinecalder.com__tasty-wing-dip-sauce`, `carpetrepairlouisville.com__about`, `carpetrepairlouisville.com__commercial-carpet-repair-and-cleaning`, `chamberofcommerce-ontheweb.com__extreme-freebies`, `cnx.org` |
| `low_visible_text_lt_80` | 44 | 0.89% | `altfundmanagement.com__about`, `altfundmanagement.com__our-team`, `bermudaunlimited.com__register`, `bermudaunlimited.com__st-georges`, `blog.concertkatie.com__other-event`, `bodyofhealthandlife.com__contact-us` |
| `error_or_default_server_page_text` | 33 | 0.67% | `allbadcreditloan.com`, `bangau188.com__contact-us`, `biblicalcounsellingafrica.com__local-events`, `carasoulia.com__boston-family-photographer-2`, `carasoulia.com__boston-maternity-photographer`, `centminmod.com__faq` |
| `adult_casino_dating_risky_instance_id` | 17 | 0.34% | `arktan.com__best-ai-girlfriend-sexting-nsfw-porn-chat-bots`, `blog.photofeeler.com__take-photos-for-dating-apps`, `bridesworldsite.com__czech-dating`, `casualrelationships.net__local-hookup`, `casualrelationships.net__buddhist-dating`, `delhi-escorts-x.in__tamara` |
| `code_too_short_lt_500` | 6 | 0.12% | `alen-m.com`, `imux.net`, `keepon-project.eu`, `lancasteronline.com`, `ohsofficer.com`, `schools.cbe.ab.ca` |
| `parked_or_placeholder_page_text` | 4 | 0.08% | `cardsetter.com__how-it-works`, `grundco.com__structural-repairs`, `mintleafdentalcare.com`, `richmondvanewhomes.net__the-things-you-need-to-know-about-building-a-new-home` |
| `remote_media_src` | 2 | 0.04% | `ezviz.com__cn`, `meetville.com__ca` |
| `very_few_html_tags` | 1 | 0.02% | `mlsdizayn.com__hakkimizda` |

### text-repair.jsonl

| issue | count | ratio | examples |
|---|---:|---:|---|
| `patch_replace_uncheckable_missing_output_files` | 4926 | 100.00% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `remote_url_present` | 4879 | 99.05% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `picsum_image_residual` | 4748 | 96.39% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `html_lang_attr_present` | 4671 | 94.82% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `remote_image_src_or_srcset` | 4633 | 94.05% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `remote_or_web_font_reference` | 2853 | 57.92% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01simple.com__world`, `01logix.com__mspowerbi` |
| `missing_body_tag` | 2366 | 48.03% | `1staab.com__digital-art`, `1staab.com__quotes`, `10-twenty.ca__seo`, `10legsinthekitchen.com__staceybender`, `01logix.com__mspowerbi`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches` |
| `patch_search_not_found` | 1273 | 25.84% | `1staab.com__quotes`, `10legsinthekitchen.com__staceybender`, `24-news.net__ip`, `10kcards.com__pricing`, `01simple.com__realestate`, `01logix.com__microsoft-sharepoint-online-partner` |
| `remote_iframe_src` | 931 | 18.90% | `01logix.com__mspowerbi`, `2canoes.com__faq`, `2canoes.com__retouching-services`, `1st-drainage-tewkesbury.co.uk__gallery`, `01logix.com__ad-linked`, `37thcasa.net` |
| `bad_src_or_srcset_null_hash` | 408 | 8.28% | `1stok.com__online-slots`, `2derms.com__contact`, `3-day-trial.uk__disclaimer`, `3-day-trial.uk__privacy-policy`, `3dcomenius.com`, `64kb.de__psu64` |
| `inline_event_handler_present` | 403 | 8.18% | `01simple.com__world`, `01simple.com__immigration`, `24sevenfaith.com`, `2derms.com__contact`, `01simple.com__realestate`, `24sevenfaith.com__workplace-wisdom` |
| `remote_stylesheet_href` | 394 | 8.00% | `10legsinthekitchen.com__staceybender`, `10legsinthekitchen.com__lets-talk-turkey-sandwiches`, `10legsinthekitchen.com__about`, `10kcards.com__pricing`, `10legsinthekitchen.com__blog-journal-index`, `2derms.com__contact` |
| `missing_html_lang_attr` | 255 | 5.18% | `24-news.net__ip`, `NeoK12.com`, `NeoK12.com__games`, `OilFans.com__schedule`, `NeoK12.com__presentations`, `OilFans.com__schedule_2` |
| `dangerous_href_or_src_protocol` | 241 | 4.89% | `4gujarat.com__terms-of-service`, `ENHYPEN.com__page_5`, `LauraBrownAuthor.com__hearing-loss-resources`, `LauraBrownAuthor.com__my-books`, `OilFans.com__schedule`, `LauraBrownAuthor.com__the-un-arranged-marriage` |
| `non_zh_en_html_lang_attr` | 223 | 4.53% | `GoriLaw.Com__es`, `Vendata.org`, `abelpardo.com__abel-pardo`, `ablakszereles.com__kiszallasi-teruletek`, `acidicmathz.com__cost`, `acidicmathz.com__kaizoudo` |
| `patch_search_ambiguous` | 99 | 2.01% | `MiamiLockAndKeys.com__locksmith-terms-and-conditions`, `aaronlee.co`, `aiblifescience.com__cart`, `allied-eng.com__careers`, `alternativepac.us__join`, `amaravillage.net__jackery-solarsaga-100w-solar-panel` |
| `patch_search_too_short_lt_20` | 91 | 1.85% | `aarontgrogg.com__portfolio`, `abounddesign.com__hungry-ghost-bread-northampton-ma`, `adoptionformsexpress.com__privacy-policy`, `affordablebailbonding.com__frequently-asked-questions`, `amaravillage.net__jackery-solarsaga-100w-solar-panel`, `angel.co__overview` |
| `remote_script_src` | 73 | 1.48% | `GoriLaw.Com__wrongful-death-lawsuit`, `GoriLaw.Com__statute-of-limitations`, `GoriLaw.Com__es`, `abhomesva.com__build-your-home`, `abhomesva.com__contact`, `all-free-download.com__font` |
| `challenge_or_access_denied_text` | 63 | 1.28% | `accessaudio.com`, `accurixlabs.com`, `artmoves.com`, `atsolutions.org__suggest-solution-ideas`, `au.help.yahoo.com__homepage`, `basicincome.org.uk__betninja` |
| `low_visible_text_lt_80` | 56 | 1.14% | `4leggedflix.com__faq`, `a3249sfdlasd.com`, `acdla.net__wp-login`, `all-freemagazines.com__2`, `allcleanuv-c.com__contact-us`, `altfundmanagement.com__contact` |
| `error_or_default_server_page_text` | 22 | 0.45% | `24-news.net__ip`, `abrasives4sale.com__rtp`, `abrasives4sale.com__promotion`, `abrasives4sale.com__game_2`, `abrasives4sale.com__register`, `brokenpencil.com` |
| `patch_empty_search` | 22 | 0.45% | `amaravillage.net__jackery-solarsaga-100w-solar-panel`, `annabellenelson.com__books`, `anvely.ca__privacy-policy`, `aspirecaregiving.com__specialized-care-programs`, `aaryavartt.com`, `3mdrivingschool.com.au__gallery` |
| `adult_casino_dating_risky_instance_id` | 19 | 0.39% | `agencasinosbobet.net__gambling`, `alltopdating.com__black-dating`, `alltopdating.com__asian-dating`, `alltopdating.com__christian-dating`, `bestadulthookup.com__best-married-dating-sites`, `casinoapp.eu__sports-betting` |
| `parked_or_placeholder_page_text` | 7 | 0.14% | `airenergycorp.com`, `arbucklewildernesspark.com`, `blackoakcy.com`, `blazers-n-hull.com__privacy-policy`, `createadigitallife.com`, `dressesgalore.co.uk` |
| `very_few_html_tags` | 3 | 0.06% | `community.oerproject.com__big-history`, `corsalis.com__actualites`, `frankbuck.org__resources` |
| `code_too_short_lt_500` | 2 | 0.04% | `ahmedshareef.com`, `cuts.diamond.mlb.com` |
| `remote_media_src` | 1 | 0.02% | `ezviz.com` |

## Cross Sample Duplication

- duplicate instance_id groups: 9038
- samples in duplicate instance_id groups: 19733
- duplicate target-code hash groups: 472
- samples in duplicate target-code groups: 985
- duplicate image reference groups: 18947

## Task Field Values

- `image-edit.jsonl`: `image-editing`=4333
- `image-generate.jsonl`: `image-generation`=9769
- `image-repair.jsonl`: `image-repair`=4845
- `text-edit.jsonl`: `text-editing`=4333
- `text-generate.jsonl`: `text-generation`=4959
- `text-repair.jsonl`: `text-repair`=4926
