# 小说文件工具

本目录有两个独立命令行工具,均只使用 Python 3.10+ 标准库,无需第三方依赖:

- `check_versions.py`:比较多版本文件(见下)。
- `reformat.py`:重排段落(见文末)。

## 多版本文件比较工具

在本目录下运行:

```sh
python3 check_versions.py .
python3 check_versions.py . --recursive
python3 check_versions.py . --json
python3 check_versions.py . --encoding gb18030
python3 check_versions.py . --min-substring 2
```

识别 `report_v1.txt`、`report_v1.2.txt`、`report-version-2.txt` 等文件名,
支持 `v`、`ver`、`version`、`rev` 标记以及空格、下划线、短横线、点分隔符。
仅将同一目录、相同基本文件名和扩展名的文件分组,按数字版本顺序比较相邻版本。
显式版本组优先保留数字排序,不参与后续模糊分组。
剩余文件只按文件名共享的连续汉字子串分组(默认至少 4 个汉字,可通过 `--min-substring` 调整)。
支持简体、繁体及 Unicode 扩展/兼容汉字;英文、数字、标点不参与子串匹配,也不会被删除后拼接汉字。
排除扩展名,并限制为同目录和相同扩展名(扩展名忽略大小写)。
例如 `长夜明灯_初稿.txt` 和 `修订_长夜明灯.txt` 可以匹配;
`draft_lantern.txt` 和 `lantern_final.txt` 不会匹配。
此限制仅适用于自动子串匹配,`report_v1.txt` 和 `report_v2.txt` 等显式版本组仍可比较。
这只是文件名启发式,不保证是同一文档的版本。
重叠匹配合并为一个连通组,组内不一定每对文件都有共同子串。
没有形成显式版本组的单个版本文件也可参与子串匹配,匹配时去掉其版本后缀。
子串组按文件字节数从小到大比较相邻文件,同大小按文件名排序;大小不代表修订时间。
文本和 JSON 报告均标明匹配类型、共享子串和比较顺序;子串组的 `versions` 为 `null` 列表。
递归扫描不会跨目录合并版本。

每组的最后一个文件视为最新版本。如果旧版本中有最新版本里不存在的行
(忽略首尾空格和空行),报告会输出 `WARNING` 并列出文件名、行号和该行内容;
JSON 报告对应 `latest` 和 `missing_from_latest` 字段。被改写的句子也会被列出。

报告包含内容是否完全相同、字节数变化、文本增加/删除行数、相似度和变化位置,
除上述 WARNING 中的缺失行外,不会输出文件正文或推断语义。替换行同时计入删除和增加。
自动识别 UTF-8 和带 BOM 的 UTF-16;二进制或无法解码的文件只报告大小和 SHA-256。
其他文本编码可通过 `--encoding` 明确指定;行尾或编码变化会单独提示。
扫描默认仅包含当前目录,跳过符号链接,绝不修改被扫描文件。
整个文件读入内存进行比较,适合普通文档,不适合超大文件。
成功(包括发现差异)退出码为 0,目录/读取/解码错误退出码为 2。

运行工具测试:

```sh
python3 -m unittest test_check_versions -v
```

## 段落重排工具

```sh
python3 reformat.py                   # 预览当前目录所有 txt,不修改文件
python3 reformat.py 山中信_定稿.txt     # 预览单个文件
python3 reformat.py 山中信_定稿.txt --write   # 覆盖原文件
python3 reformat.py . --encoding gb18030
```

规则:空行分隔段落;被硬换行拆开的行合并(中文直接相连,两侧都是英文/数字时补一个空格),
但行尾是句末标点(。!?…”」』)等)的行会结束当前段落,所以"每句一行"的文本不会被合成一整段,
每句各成一段;多个空行合并为一个;每段首行缩进两个全角空格。
文件开头的单行短标题(多段文件中的第一段,不超过 40 字)不缩进。
默认只输出到终端,加 `--write` 才覆盖原文件。重复运行结果不变。
测试:`python3 -m unittest test_reformat -v`
