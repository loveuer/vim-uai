# vim-uai — Vim Your AI

在 Vim 中用快捷键打开 prompt 弹窗，让 AI 修改当前行或选中的代码。支持 **OpenAI Chat Completions** 和 **Anthropic Messages** 两种 API 协议，也可以配置使用这些协议的代理或本地服务。

## 要求

- Vim 8.2+，包含 `+popupwin`、`+job`、`+channel`。本项目使用 Vim 原生 popup API，暂不支持 Neovim。
- 外部 Python 3.8+，仅使用标准库；不要求 Vim 编译时启用 `+python3`。
- 一个可用的 API 地址、模型和密钥。本地无认证服务可留空密钥。

## 安装

使用 vim-plug 时，在现有的 `plug#begin()` / `plug#end()` 之间添加：

```vim
Plug 'loveuer/vim-uai', {'branch': 'master'}
```

重新加载 vimrc 后执行 `:PlugInstall`。

本地开发可以直接加载项目目录：

```vim
Plug '/path/to/vim-uai', {'as': 'vim-uai'}
```

将路径替换为项目的实际目录，重新加载 vimrc 或重启 Vim 即可生效。

也可以使用 Vim 的原生 package 目录，将整个项目放入：

```text
~/.vim/pack/plugins/start/vim-uai/
```

安装后可以执行 `:helptags ALL` 生成帮助索引，再用 `:help vim-uai` 查看帮助。

在本项目目录中临时试用：

```sh
vim --cmd 'set runtimepath^=.'
```

## 配置

将其中一种配置写入 `~/.vimrc`。模型名称填写所用服务实际支持的名称。

### OpenAI Chat Completions

```vim
let g:vim_uai_provider = 'openai'
let g:vim_uai_api_base = 'https://api.openai.com/v1'
let g:vim_uai_model = 'your-model-name'
" 默认从 OPENAI_API_KEY 环境变量读取；也可以显式设置：
" let g:vim_uai_api_key = $MY_LLM_API_KEY
```

请求地址为 `{api_base}/chat/completions`，密钥放在 `Authorization: Bearer …` 中。

### Anthropic Messages

```vim
let g:vim_uai_provider = 'anthropic'
let g:vim_uai_api_base = 'https://api.anthropic.com/v1'
let g:vim_uai_model = 'your-model-name'
let g:vim_uai_max_tokens = 4096
" 默认从 ANTHROPIC_API_KEY 环境变量读取；也可以显式设置：
" let g:vim_uai_api_key = $MY_LLM_API_KEY
```

请求地址为 `{api_base}/messages`，使用 `x-api-key` 和 `anthropic-version: 2023-06-01`；系统提示词使用独立的 `system` 字段。

`api_base` 包含服务要求的路径前缀（通常是 `/v1`），不要包含 `/chat/completions` 或 `/messages` 本身。切换协议时，如果显式配置过地址和密钥，需要同步修改它们。

其他选项：

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `g:vim_uai_provider` | `'openai'` | `'openai'` 或 `'anthropic'` |
| `g:vim_uai_api_base` | 对应协议的官方地址 | API 基础地址 |
| `g:vim_uai_api_key` | 对应协议的环境变量 | 留空则不发送认证头 |
| `g:vim_uai_model` | `''` | 必须配置 |
| `g:vim_uai_max_tokens` | `4096` | Anthropic 输出 token 上限 |
| `g:vim_uai_timeout` | `90` | HTTP 请求超时，单位秒 |
| `g:vim_uai_send_full_buffer` | `1` | 发送当前 buffer 的完整内容，含未保存修改；设为 `0` 关闭全文发送 |
| `g:vim_uai_context_lines` | `40` | 选区前、后各提供多少行摘录；设为 `0` 不提供摘录，全文发送由上一项独立控制 |
| `g:vim_uai_project_context` | `1` | 附带项目根目录、目录树及项目说明和配置摘录；设为 `0` 关闭 |
| `g:vim_uai_project_root` | `''` | 手动指定项目根目录，支持绝对路径、`~` 或相对 Vim 工作目录的路径；也可设置 buffer 局部的 `b:vim_uai_project_root` |
| `g:vim_uai_project_max_entries` | `200` | 目录树最多包含的路径数量 |
| `g:vim_uai_project_max_depth` | `3` | 目录树深度；`1` 表示只列根目录的直接子项 |
| `g:vim_uai_python` | `'python3'` | Python 可执行文件名称或绝对路径 |
| `g:vim_uai_no_mappings` | `0` | 设为 `1` 禁用默认快捷键 |

## 使用

默认快捷键为 `<leader>ai`。没有自行设置 `mapleader` 时，就是 `\ai`。

1. Normal / Insert 模式：在光标所在行按 `<leader>ai`。
2. Visual 模式：用 `v`、`V` 或 Ctrl-V 选中代码，再按 `<leader>ai`。
3. 在弹窗输入“帮我实现这个 TODO”等指令，按 Enter 发送。
4. 生成后弹窗展示替换代码；按 Enter 应用，按 Esc 放弃。
5. 应用后用 `u` 撤销整次替换，文件由你正常使用 `:write` 保存。

处理单位是**整行**：字符选区和矩形选区也会扩展到涉及的完整行。Normal / Insert 模式的当前行可以被替换为多行，例如将一行 TODO 展开为函数实现。

弹窗使用 Vim 的按键过滤器输入文本，不是一个可进入 Insert 模式的普通 buffer。

| 阶段 | 按键 | 操作 |
| --- | --- | --- |
| 输入 | Enter | 提交 |
| 输入 | Ctrl-J | 插入换行 |
| 输入 | 左 / 右 | 移动输入位置 |
| 输入 | Home / Ctrl-A、End / Ctrl-E | 移到当前输入行首、行尾 |
| 输入 | Backspace / Delete | 删除前一个 / 后一个字符 |
| 输入 | Ctrl-U | 删除输入位置到当前行首的文本 |
| 输入 | Tab | 插入两个空格 |
| 预览 | Enter | 替换原选区 |
| 预览 | j / k、上 / 下 | 滚动代码 |
| 预览 | Ctrl-D / Ctrl-U、PageDown / PageUp | 向下 / 向上滚动半页 |
| 任意阶段 | Esc | 关闭弹窗；请求进行中则终止本地请求进程 |

还可以使用命令：

```vim
:VimUAI
:VimUAI 帮我实现这个 TODO
:'<,'>VimUAI 为选中代码增加错误处理
:10,20VimUAI 重构这段代码
:VimUAICancel
```

命令中的文字会预填入弹窗，仍需 Enter 提交。

自定义快捷键，在 vimrc 中配置：

```vim
let g:vim_uai_no_mappings = 1
nmap <leader>ac <Plug>(vim-uai)
xmap <leader>ac <Plug>(vim-uai)
imap <C-G>a <Plug>(vim-uai)
```

## 发送给模型的上下文

两种 API 协议都会在用户消息中发送相同结构的 JSON：

| 字段 | 内容 |
| --- | --- |
| `instruction` | 弹窗中输入的指令 |
| `timestamp` / `timezone` | 提交请求时的本地时间（包含 UTC 偏移，如 `2026-11-09T15:30:00+0800`）和时区名称 |
| `workdir` | 触发弹窗时 Vim 的工作目录，尊重窗口或标签页的局部目录 |
| `file` / `filepath` | 当前文件名和绝对路径；未命名 buffer 两项均为空字符串 |
| `filetype` | Vim 文件类型 |
| `file_content` | 当前 buffer 全文，包含未保存的修改，换行统一为 LF，并保留有无末尾换行；关闭全文发送时省略此字段 |
| `file_line_count` / `file_modified` | buffer 总行数、是否包含未保存修改 |
| `cursor` | 触发时的光标行号、字符列号 `column`、字节列号 `byte_column` 和当前行内容 `text`，位置均从 1 开始 |
| `selection` | 待替换范围的起始行、结束行（均包含在内）及原文；Normal / Insert 模式为当前行 |
| `context_before` / `context_after` | 选区前后的代码摘录，帮助定位目标范围 |
| `project.root` / `project.root_source` | 项目根目录，以及识别依据（如 `.git`、`go.mod`、`configured`） |
| `project.current_file` | 当前文件相对项目根目录的路径；未命名或位于手动指定根目录之外时为 `null` |
| `project.tree` | 相对项目根目录的文件和目录路径，目录以 `/` 结尾 |
| `project.tree_truncated` | 目录是否因深度、路径数量或扫描数量限制而未完整列出 |
| `project.files` | 项目说明、依赖声明和配置摘录，每项含 `path`、`start_line`、`end_line`、`content`、`truncated` |
| `project.files_truncated` | 是否因文件数量或总字节预算省略后续摘录 |
| `project.unavailable_directories` / `project.unavailable_files` | 无法读取的目录或摘录路径 |

完整文件让模型能够参考其他位置的 import、函数定义、类型和调用关系。系统提示词会说明全文是参考上下文，输出仅用于替换 `selection` 指定的范围。

大文件可以关闭全文发送，改用选区和附近行：

```vim
let g:vim_uai_send_full_buffer = 0
let g:vim_uai_context_lines = 80
```

项目根目录从当前文件的位置向上寻找，优先采用最近的 Git / Mercurial / SVN 根目录（支持 Git worktree 的 `.git` 文件）。没有版本库标记时，采用最近的 `go.mod`、`package.json`、`pyproject.toml`、`Cargo.toml` 等项目标记所在目录。仍未找到时，采用包含当前文件的 Vim 工作目录，或当前文件最近的现有父目录。未命名 buffer 从 Vim 工作目录开始寻找。手动设置 `b:vim_uai_project_root` 或 `g:vim_uai_project_root` 时优先使用该目录。

目录扫描在后台 Python 进程中执行，默认最多列 200 个路径、3 层深度，跳过 `.git`、`node_modules`、`vendor`、虚拟环境和常见构建、缓存目录，不跟随符号链接。目录列表使用固定排除规则，并非完整的 `.gitignore` 解析器。

项目摘录优先包含从项目根目录到当前文件目录之间适用的 `AGENTS.md`，随后收集相关目录的依赖声明、项目根目录的 README，以及 `.editorconfig`、`tsconfig.json`、`Makefile` 等配置。最多收集 12 个文件，每个读取至多 8 KiB，总读取量不超过 32 KiB，并标明截断情况。其他源码文件仅列出路径；当前文件始终使用 Vim buffer 中的版本，不会再附带过期的磁盘副本。

例如可以手动指定项目范围和目录树大小：

```vim
let g:vim_uai_project_root = '~/codes/my-project'
let g:vim_uai_project_max_entries = 300
let g:vim_uai_project_max_depth = 4
```

`g:vim_uai_send_full_buffer = 0` 只关闭当前 buffer 全文。若也要关闭项目目录和文件摘录，设置 `let g:vim_uai_project_context = 0`。

## 行为边界

- 请求异步执行。上述编辑器上下文和输入指令会发送到配置的 API；默认包含当前 buffer 全文，以及有数量和长度限制的项目目录、说明和配置摘录。
- 生成结果只替换原选区。若当前 buffer、内容或可写状态在弹窗打开后发生变化，插件会拒绝应用，请重新触发。
- API 报错、输出为空或响应标明生成被截断时，保留原文并显示错误。当前版本不支持用空响应删除整个选区。
- 密钥通过子进程 stdin 传递，不放入命令行参数或临时文件。关闭弹窗会终止本地进程；服务端是否停止生成取决于 API 服务。
- 当前使用非流式文本请求，不支持工具调用或跨文件编辑。

## 验证

```sh
python3 -m unittest discover -s tests -v
```

测试使用本地 HTTP 模拟服务，覆盖两种协议的字段和认证、时间和路径信息、项目根目录识别、目录和摘录预算、项目上下文开关、完整未保存内容、全文发送开关、中文光标列号、中文输入、多行输入、Normal / Visual / Insert 快捷键、预览、取消、替换、撤销和内容冲突，不需要真实 API Key。

协议参考：[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages)。
