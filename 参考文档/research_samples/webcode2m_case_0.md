# WebCode2M 样本 Case 0 阅读版
这个文件把 `webcode2m_first_rows.json` 里的第 0 条样本拆成更容易读的形式，并记录一次本地渲染检查。
## 1. 样本元信息
- dataset: `xcodemind/webcode2m`
- split/config: `train` / `default`
- row_idx: `0`
- title: `zip-stream :: Stackage Server`
- lang: `en`
- score: `3`
- scale: `[1280, 1246]`
- tokens: `[925, 1323]`，含义大致是 `[CSS token 数, HTML token 数]`
- text length: `6696` chars
- bbox length: `14279` chars
- hash: `8a03192e3b8d385b2f1f297f37df7a2688523844977cc6182867a9077d638db0`
- screenshot URL: `https://datasets-server.huggingface.co/assets/xcodemind/webcode2m/--/f53cd4a9317364e32a6fc7d99dc50761fe54715f/--/default/train/0/image/image.png?Expires=1779202780&Signature=bvjSGX...`

## 2. 代码结构概览
- HTML tag 数量约：`137`
- `<style>` 数量：`1`
- `<script>` 数量：`0`
- `http(s)` 远程引用数量：`0`
- `data:` URI 数量：`0`
- 站内绝对路径引用数量：`1`

站内绝对路径例子：

- `/static/img/stackage.png`

这说明 WebCode2M 的样本不是原始网页工程。它更像是“清洗后的单文件 HTML/CSS 表示”：CSS 直接写在 HTML 里，没有远程 CDN，也没有第三方 JS。但它仍可能保留 `/static/...` 这类站内路径，因此不一定 100% 自包含。

重要判断：按我们自己的训练数据标准，这条 preview 样本不能直接作为最终训练样本使用。原因不是它完全没有 HTML，而是它缺少随 HTML 一起提供的静态资源目录。`/static/img/stackage.png` 是原站根目录下的站内绝对路径，不是这个 JSON 里的文件，也不是 Hugging Face preview 里随样本一起给出的资源文件。如果直接把这条 `text` 当成训练目标，模型会学到一种不完整的资源引用方式。

## 3. 页面内容摘要
- zip-stream :: Stackage Server
- About
- Snapshots
- LTS
- Nightly
- FAQ
- Blog
- zip-stream
- ZIP archive streaming using conduits
- Version on this page:
- 0.2.1.0
- LTS Haskell 21.22
- 0.2.2.0
- Stackage Nightly 2023-11-30
- 0.2.2.0
- Latest on Hackage:
- 0.2.2.0
- See all snapshots
- zip-stream
- appears in
- BSD-3-Clause licensed
- by
- Dylan Simon
- Maintained by
- dylan@dylex.net
- This version can be pinned in stack with:
- zip-stream-0.2.1.0@sha256:9601c2a5addd3edd8ab1f7ac8c3753e92326e1971c6d15d123e621ff8c92e002,1749
- Module documentation for 0.2.1.0
- Exact lookup
- Codec

## 4. Layout Tree / bbox 摘要
元素类型计数：

- `a`: 39
- `div`: 30
- `li`: 13
- `td`: 8
- `ul`: 6
- `span`: 5
- `tr`: 4
- `input`: 4
- `p`: 3
- `code`: 2
- `strong`: 2
- `em`: 2
- `body`: 1
- `button`: 1
- `h1`: 1
- `table`: 1
- `tbody`: 1
- `h4`: 1
- `form`: 1
- `label`: 1

前几个布局节点：

-   `div` bbox=[8, 8, 1264, 1144] content='(empty)'
-     `div` bbox=[8, 8, 1264, 148] content='(empty)'
-       `div` bbox=[8, 8, 1264, 148] content='(empty)'
-         `div` bbox=[8, 8, 1264, 148] content='(empty)'
-         `div` bbox=[8, 48, 1264, 108] content='(empty)'
-         `a` bbox=[48, 48, 41, 17] content='About'
-         `a` bbox=[48, 66, 75, 17] content='Snapshots'
-         `a` bbox=[48, 84, 28, 17] content='LTS'
-         `a` bbox=[48, 102, 48, 17] content='Nightly'
-         `a` bbox=[48, 120, 32, 17] content='FAQ'
-         `a` bbox=[48, 138, 32, 17] content='Blog'
-     `div` bbox=[8, 177, 1264, 974] content='(empty)'

## 5. HTML/CSS 片段
```html
<!DOCTYPE html>

<!DOCTYPE html>

<html class="no-js"> <head><title>zip-stream :: Stackage Server</title></head><body><div id="main"><div class="navbar navbar-inverse navbar-static-top"><div class="navbar-inner"><div class="container"><button class="btn btn-navbar"><span class="icon-bar"></span><span class="icon-bar"></span><span class="icon-bar"></span></button><a class="brand"><img src="/static/img/stackage.png"/></a><div class="nav-collapse collapse"><ul class="nav"><li> <a>About</a></li><li> <a>Snapshots</a></li><li> <a>LTS</a></li><li> <a>Nightly</a></li><li> <a>FAQ</a></li><li> <a>Blog</a></li></ul></div></div></div></div><div class="container"><div class="container content" id="snapshot-home"><div class="row"><div class="span12"><h1>zip-stream</h1><p class="synopsis">ZIP archive streaming using conduits</p><table><tr><td>Version on this page:</td><td><span class="version">0.2.1.0</span></td></tr><tr><td><a>LTS Haskell 21.22</a>:</td><td><span class="version"><a>0.2.2.0</a></span></td></tr><tr><td><a>Stackage Nightly 2023-11-30</a>:</td><td><span class="version"><a>0.2.2.0</a></span></td></tr><tr><td>Latest on Hackage:</td><td><a><span class="version">0.2.2.0</span></a></td></tr></table><p><a>See all snapshots <code>zip-stream</code> appears in</a></p></div></div><div class="row"><div class="span12"><div class="authorship"><span class="license">BSD-3-Clause licensed </span>by <strong class="author">Dylan Simon</strong></div><div class="maintainer">Maintained by <strong class="author"><a>dylan@dylex.net</a></strong></div><div class="pantry-version">This version can be pinned in stack with:<code>zip-stream-0.2.1.0@sha256:9601c2a5addd3edd8ab1f7ac8c3753e92326e1971c6d15d123e621ff8c92e002,1749</code></div><div class="docs"><h4>Module documentation for 0.2.1.0</h4><form class="hoogle"><input class="search"/><input class="btn"/><input/><label class="checkbox exact-lookup"><input id="exact"/>
Exact lookup</label></form><ul class="docs-list"><li>Codec<ul class="docs-list"><li>Codec.Archive<ul class="docs-list"><li>Codec.Archive.Zip<ul class="docs-list"><li>Codec.Archive.Zip.Conduit<ul class="docs-list"><li><a>Codec.Archive.Zip.Conduit.Types</a></li><li><a>Codec.Archive.Zip.Conduit.UnZip</a></li><li><a>Codec.Archive.Zip.Conduit.Zip</a></li></ul></li></ul></li></ul></li></ul></li></ul></div></div></div></div><div class="container content" id="snapshot-home"><div class="row"><div class="span12"><div class="dependencies" id="dependencies">Depends on 19 packages<em
...
```

## 6. 初步质量判断
### 6.1 质量优点

1. 代码明显经过清洗，长度比真实原站工程短很多。
2. CSS 内嵌在 HTML 中，训练时模型能直接看到页面样式。
3. 没有远程 CDN、analytics、tracking、第三方 JS，噪声很少。
4. 提供了 bbox/layout tree，这对训练模型理解页面层级很有价值。
5. 有 `score`、`lang`、`tokens`、`scale`、`hash` 等 metadata，方便做质量过滤、语言过滤和长度控制。
6. 页面内容、布局树和截图在同一条样本里，适合做 screenshot-to-code 或 layout-to-code 这类监督训练。

### 6.2 质量缺点

1. 不是完整项目目录，只有单条 HTML/CSS 文本和截图。
2. 保留了 `/static/img/stackage.png` 这种站内绝对路径，本地渲染时会 404，说明它不一定完全自包含。
3. 没有 JS 交互，对我们想做的多页/交互式 web coding 数据只能作为“清洗表示”的参考。
4. 样本的 HTML 有重复 `<!DOCTYPE html>`，说明自动清洗仍可能留下小瑕疵。
5. 如果没有原始截图对照，单看渲染结果很难判断视觉是否真的和目标一致。
6. Hugging Face dataset viewer 给出的 preview 不是完整可运行工程，不能证明完整数据集每条样本都能离线渲染。
7. 对我们的目标来说，它缺少多文件结构、页面间导航、本地 assets 管理、真实 JS 交互等能力。

### 6.3 是否能直接作为我们的训练数据

不能直接作为我们最终的 web coding 训练数据。

它最多可以作为“参考数据形态”或“辅助研究样本”：

```text
可以借鉴：清洗后的 HTML/CSS 表示、bbox/layout tree、metadata、质量评分。
不能照搬：不完整资源路径、单文件静态 HTML、缺失 JS 交互、缺失多页项目结构。
```

如果要把 WebCode2M 类似数据并入我们的训练集，至少要先做三件事：

1. 检查每条样本是否有未解析的 `/static/...`、`/assets/...`、`http(s)://...` 资源引用。
2. 对缺失图片/字体/CSS 做本地化或 placeholder 替换。
3. 渲染后和原始 screenshot 对齐验证，不能只看 HTML 能不能打开。

## 7. 渲染检查
我已把该样本保存成：

```text
paper/research_samples/webcode2m_case_0_render.html
```

本地渲染结论：见同目录下截图 `webcode2m_case_0_render.png`。Chrome headless 可以打开 HTML 并生成截图，截图尺寸为 `1280 x 1246`，文件大小约 `124KB`，不是完全空白页。但这不等于“训练可用”。

静态服务器日志显示：

```text
GET /webcode2m_case_0_render.html 200
GET /static/img/stackage.png 404
GET /favicon.ico 404
```

其中 `/static/img/stackage.png` 是真正的问题。它说明这条样本的 HTML 仍然引用了没有随样本提供的站内静态资源。如果用户直接打开这个缺失图片地址，或者本地 server 已经关闭，就会看到 Safari 的“无法连接服务器”页面。这不是网页主体，而是浏览器在访问缺失资源 URL。

所以这条 case 的结论应改成：

```text
技术上：HTML 主体可以被浏览器解析并截图。
数据质量上：资源不完整，不能直接作为我们的最终训练样本。
```

## 8. 对我们数据处理的启发
WebCode2M 的重点不是保存真实网页的所有资源，而是把真实网页压缩成适合训练的、短而干净的页面表示。我们可以借鉴：

1. 把外部 CSS 转成本地或内嵌 CSS。
2. 删除 analytics/tracking/ads/social embed 等低价值代码。
3. 记录 layout tree 或至少记录 DOM 层级摘要，辅助训练和质量筛选。
4. 为每个样本保留质量分数、语言、token 数、截图尺寸等 metadata。
5. 但我们自己的数据如果要支持多页和 JS 交互，不能完全照搬 WebCode2M 的单文件静态形态。

更具体地说，我们应该借鉴它的“数据组织方式”，而不是直接借鉴它的“可运行工程形态”：

### 8.1 值得借鉴

1. 每条样本记录 `image/screenshot`，后续可以做渲染对齐检查。
2. 每条样本记录 `bbox/layout tree`，后续可以做页面结构监督或质量筛选。
3. 每条样本记录 `tokens`，便于过滤过长 HTML/CSS。
4. 每条样本记录 `lang`，便于控制语言分布。
5. 每条样本记录 `score`，便于优先选择高质量样本。
6. 把真实网页里的 CMS、analytics、tracking、广告等噪声清掉。
7. 尽量让 CSS 进入样本文本或本地文件，而不是依赖远程 CDN。

### 8.2 不能照搬

1. 不能接受缺失资源的 `/static/...` 路径。
2. 不能只保存单文件 HTML，因为我们的目标包含多页项目结构。
3. 不能完全去掉 JS，因为我们的 web coding 数据需要覆盖交互。
4. 不能只相信“可以打开 HTML”，必须和目标截图做视觉对齐验证。
5. 不能把 preview JSON 当成完整数据包；要确认完整 parquet 里是否也只有文本字段，没有静态资源目录。

### 8.3 对我们 useful 数据的建议

1. 我们的每个项目应该是完整目录，而不是单条 HTML 文本。
2. `assets/` 里必须包含渲染关键图片、CSS、字体和 JS。
3. 所有关键资源引用都应改成相对路径，避免 `/static/...` 这种依赖 server root 的路径。
4. 每个项目额外生成一个 `metadata.json`，记录语言、token 数、截图尺寸、外部资源统计、是否包含 JS 交互、是否多页。
5. 每个项目最好保存一份 layout/DOM 摘要，后续可用于过滤和训练。
