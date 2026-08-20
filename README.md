# Reality Travel MCP

一个可以独立运行、持续保存状态的真实世界旅行 MCP。它把地点解析、当前天气、Google 历史街景、旅行状态与关键原话档案放在同一个服务里，但不把普通聊天复制进旅行档案。

项目保留原作“小小与程渝”的默认角色、`chengyu` traveler_id 和 K-pax 作品气质。其他使用者可以通过环境变量覆盖显示名与 traveler_id；不配置时，看到的仍然是原作版本。

## 能力

- `travel_start(place)`：开始一段新旅程。
- `travel_list()` / `switch_journey(...)`：查看并切回保留的旧旅程。
- `travel_status()`：读取当前状态，不移动也不消耗街景图片配额。
- `continue_journey()`：隔一段时间回来，刷新当地时间、天气与街景。
- `look_around(direction|heading)`：在同一 panorama 转动视角。
- `move(destination)`：前往明确地点。
- `move(heading, distance_m)`：最多 500 米的试探移动；找不到附近街景时原地不动。
- `record_travel_words(...)`：保存实际说出或写下的关键原话。
- `create_postcard(text, image_prompt)`：保存旅行明信片正文，并可选生成配图。
- `record_travel_log(...)`：为一次旅行行动保存独立的第一人称“走过的路”。
- `end_journey()`：结束并归档当前旅程。
- 自带只读旅行面板、历史档案和临时隐藏/恢复时间线节点。

本项目不承诺沿道路连续导航，也不包含附近餐厅搜索、电台和商品系统。

## 数据边界

- Open-Meteo：地点、时区、当前天气和海拔；无需 API key。
- Google Street View Static API：可选的历史街景、拍摄日期、panorama 坐标和朝向。
- Google 街景图片只做短时缓存，数据库保存 metadata，不永久保存图片。
- 普通聊天不进入档案。自动关键节点是落地与离开；其他原话需要主动标记。
- 每个 `traveler_id` 拥有独立旅程，默认值为 `chengyu`。
- 运行数据默认写入 `data/` 与 `cache/`，两者均不应提交到 Git。

## 环境要求

- Python 3.11 或更新版本
- Windows PowerShell、macOS 或 Linux
- 可访问 Open-Meteo；街景功能另需 Google Street View Static API key

## 安装

### Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-reality-travel.ps1
Copy-Item .env.example .env
.\start-reality-travel.ps1
```

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
python -m reality_travel.server
```

默认地址：

- 面板：`http://127.0.0.1:3023/?traveler=chengyu`
- MCP：`http://127.0.0.1:3023/mcp`
- 健康检查：`http://127.0.0.1:3023/api/health`

不配置 Google key 时，地点、天气、档案和文字明信片仍可运行，只是街景不可用。

## 配置

复制 `.env.example` 为 `.env`，按需填写。`.env` 已被 `.gitignore` 排除，不要提交真实 key、token 或私人路径。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `REALITY_TRAVEL_DEFAULT_TRAVELER_ID` | `chengyu` | MCP 工具和面板使用的默认 traveler_id |
| `REALITY_TRAVEL_TRAVELER_NAME` | `程渝` | 旅行者显示名 |
| `REALITY_TRAVEL_COMPANION_NAME` | `小小` | 同行者显示名与提示词称呼 |
| `REALITY_TRAVEL_HOST` | `127.0.0.1` | HTTP 监听地址 |
| `REALITY_TRAVEL_PORT` | `3023` | HTTP 监听端口 |
| `REALITY_TRAVEL_PUBLIC_BASE_URL` | 由 host/port 生成 | 媒体文件对外基址 |
| `REALITY_TRAVEL_DATA_DIR` | `./data` | SQLite 数据目录 |
| `REALITY_TRAVEL_CACHE_DIR` | `./cache` | 街景和明信片缓存目录 |
| `GOOGLE_STREET_VIEW_API_KEY` | 空 | 可选 Google Street View Static API key |
| `REALITY_TRAVEL_IMAGE_GENERATOR_MODULE` | 空 | 可选的生图适配模块路径 |
| `REALITY_TRAVEL_IMAGE_GENERATOR_FUNCTION` | `generate_codex_image` | 模块内异步函数名 |
| `REALITY_TRAVEL_IMAGE_GENERATOR_PROVIDER` | `external_module` | 写入明信片 metadata 的提供方名称 |

## 本地 stdio MCP

Windows：

```powershell
.\.venv\Scripts\python.exe -m reality_travel.server --stdio
```

macOS / Linux：

```bash
./.venv/bin/python -m reality_travel.server --stdio
```

HTTP MCP 客户端应连接 `http://127.0.0.1:3023/mcp`。stdio 客户端则将上面的命令与参数写入其 MCP 配置。

## 可选明信片生图

项目默认不依赖任何外部生图源码。未设置 `REALITY_TRAVEL_IMAGE_GENERATOR_MODULE` 时，`create_postcard` 仍会保存正文；传入 `image_prompt` 只会得到“生图未配置”的非致命结果。

适配模块需提供一个异步函数，默认函数名为 `generate_codex_image`，接口为：

```python
async def generate_codex_image(prompt, output_dir, filename_prefix="postcard"):
    # 在 output_dir 中生成 png/jpg/jpeg/webp，并返回 pathlib.Path
    ...
```

也可以通过 `REALITY_TRAVEL_IMAGE_GENERATOR_FUNCTION` 指定其他函数名，通过 `REALITY_TRAVEL_IMAGE_GENERATOR_PROVIDER` 标记提供方。

## K-pax 原始接入方式

Reality Travel 最初作为 K-pax 的独立 HTTP MCP 使用，别名建议为 `REALITY`。K-pax 只保留连接、当轮街景附件转换和关键可见回复归档钩子；旅行状态与档案始终归本服务所有。

原作中的 K-pax 明信片配图由 `aion-chat/codex_image_gen.py` 提供。独立仓库不再硬编码任何 K-pax 本机路径；如需沿用该适配器，请在本机 `.env` 中显式设置：

```dotenv
REALITY_TRAVEL_IMAGE_GENERATOR_MODULE=/path/to/K-pax/aion-chat/codex_image_gen.py
REALITY_TRAVEL_IMAGE_GENERATOR_FUNCTION=generate_codex_image
REALITY_TRAVEL_IMAGE_GENERATOR_PROVIDER=kpax_codex_imagegen
```

没有 K-pax 时无需设置这些变量，也可以接入遵循同一函数接口的其他生成器。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

或在已激活的虚拟环境中运行 `python -m pytest`。

## 隐私与发布检查

- 不要提交 `.env`、数据库、街景/明信片缓存、日志、虚拟环境或测试缓存。
- 分享运行日志或数据库前，先检查其中的地点、坐标、旅行原话和 source_message_id。
- 发布前可运行 `git status --ignored` 确认本地数据均处于忽略状态。

## License

[MIT](LICENSE)
