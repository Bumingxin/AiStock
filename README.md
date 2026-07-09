# AI量化选股系统

基于 LLM 的智能量化选股系统，支持批量筛选和单股深度分析，内置多智能体博弈引擎和金融终端级 HTML 看板生成。

在线体验：[stock.aicli.cn](https://stock.aicli.cn/)

## 功能特点

### 批量量化筛选（开始选股）
- 自动抓取全球新闻 → LLM 热点提取 → 板块推荐 → 候选池构建 → 多线程技术研判 → 综合排序
- 导航栏「开始选股」Tab 查看执行进度（8 阶段实时 WebSocket 推送）
- 「分析结果」Tab 查看候选池排行榜，按综合评分排序，支持双击进入 AI 对话
- 「AI对话」Tab 对任意标的进行追问
- 支持 A 股主板，每板块 2-5 只候选

### 单股深度分析（深度分析）
- 输入股票代码，自动抓取行情 / F10 / K 线 → 行业自适应评分 → 自动同行对比 → 多智能体博弈（6 角色） → 生成金融终端级 HTML 看板
- 结果展示：评分环形图 + 行动建议 + 风险等级 + 博弈摘要 + 摘要卡片
- 支持下载完整 HTML 看板（金融终端级深色主题，含 K 线、信号位、评分拆解、风险热力图等）
- 支持导出 PDF（浏览器打印功能，保留完整排版）

### 用户系统
- 多用户支持，JWT Session 认证
- 用户积分制（批量分析 / AI 对话 / 深度分析各自消耗积分）
- 修改昵称、修改密码、历史报告、账单查询
- 管理员后台：用户管理、积分管理、系统配置

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI + WebSocket + SQLite |
| 前端 | 原生 HTML/CSS/JS（无框架依赖） |
| LLM | OpenAI 兼容 API（支持任意兼容端点） |
| 数据源 | 新浪 / 腾讯 / 东方财富 / Yahoo Finance |
| 部署 | Docker |

## 快速开始

### 方式一：一键安装（推荐）

```bash
git clone https://github.com/Bumingxin/AiStock.git
cd AiStock
bash install.sh
```

`install.sh` 会自动完成以下操作：
1. 检查 Docker 环境
2. 创建数据目录（`data/` `results/` `deep_work/` `outputs/`）
3. 生成默认 `config.json`（如不存在）
4. 停止旧容器（如存在）
5. 构建 Docker 镜像
6. 启动新容器并等待服务就绪

安装完成后访问 http://localhost:8000，默认管理员账号：`admin` / `admin123`

> ⚠️ 首次使用请编辑 `config.json` 填入你的 API Key，然后重启容器。

### 方式二：手动安装

```bash
git clone https://github.com/Bumingxin/AiStock.git
cd AiStock

# 生成默认配置
cp config.example.json config.json
# 编辑 config.json，填入你的 API Key

# 构建并启动
docker build -t aistock .
docker run -d \
  --name aistock \
  --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/config.json:/app/config.json \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/results:/app/results \
  -v $(pwd)/deep_work:/app/deep_work \
  -v $(pwd)/outputs:/app/outputs \
  aistock
```

### 方式三：本地开发（不使用 Docker）

```bash
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json 填入 API Key
python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
```

## 配置说明

编辑 `config.json`：

```json
{
  "openai_base_url": "https://api.openai.com/v1",
  "openai_api_key": "your_api_key_here",
  "model": "gpt-4o",
  "top_sectors": 5,
  "top_stocks": 20,
  "min_per_sector": 2,
  "max_per_sector": 5,
  "results_dir": "results",
  "enable_realtime_news": true,
  "news_per_source": 40,
  "news_workers": 12,
  "news_total_limit": 3000,
  "stock_workers": 4,
  "analysis_points_cost": 50,
  "chat_points_cost": 2,
  "default_user_points": 100,
  "deep_analysis_points_cost": 30,
  "enable_anysearch": true
}
```

| 配置项 | 说明 |
|--------|------|
| `openai_base_url` | LLM API 地址（支持 OpenAI / DeepSeek / 本地 Ollama 等） |
| `openai_api_key` | API Key |
| `model` | 模型名称 |
| `top_sectors` | 热门板块数量 |
| `top_stocks` | 每轮分析的候选股票总数 |
| `min_per_sector` / `max_per_sector` | 每板块最少 / 最多候选数 |
| `news_workers` | 新闻抓取并发数 |
| `stock_workers` | 股票分析并发数 |
| `analysis_points_cost` | 批量分析消耗积分 |
| `chat_points_cost` | AI 对话每次消耗积分 |
| `deep_analysis_points_cost` | 深度分析消耗积分 |
| `default_user_points` | 新用户默认积分 |
| `enable_anysearch` | 是否启用联网搜索增强 |

## 常用命令

```bash
# 查看日志
docker logs -f aistock

# 停止容器
docker stop aistock

# 启动容器
docker start aistock

# 重启容器
docker restart aistock

# 重新构建并部署（一键升级）
bash install.sh
```

## 目录结构

```
AiStock/
├── web/                              # Web 应用
│   ├── app.py                        # FastAPI 路由（30+ 接口）
│   ├── templates/                    # HTML 模板
│   │   ├── index.html                # 主页（Tab 切换）
│   │   ├── _top_nav.html             # 顶部导航栏（含用户菜单）
│   │   ├── login.html                # 登录页
│   │   ├── history.html              # 历史报告
│   │   ├── billing.html              # 账单页
│   │   └── admin.html                # 管理员后台
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── deep_analysis/                    # 深度分析模块
│   ├── pipeline.py                   # 深度分析流水线
│   └── scripts/                      # 分析脚本
│       ├── fetch_a_share.py          # A股数据抓取
│       ├── scoring_model.py          # 评分模型
│       ├── auto_comparables.py       # 自动同行对比
│       ├── debate_engine.py          # 多智能体博弈引擎
│       ├── enhanced_debate.py        # 增强博弈
│       ├── merge_debate.py           # 博弈结果合并
│       ├── render_dashboard.py       # HTML 看板渲染
│       └── anysearch_enhancer.py     # 联网搜索增强
├── china-stock-deep-analysis/        # 原始 Skill 参考
├── pipeline.py                       # 批量筛选流水线
├── data_source.py                    # 数据抓取模块
├── llm_client.py                     # LLM 调用模块
├── news_fetcher.py                   # 新闻聚合模块
├── chat_engine.py                    # AI 对话引擎
├── auth.py                           # 用户认证
├── database.py                       # 数据库操作（SQLite）
├── config.py                         # 配置管理
├── Dockerfile
├── install.sh                        # 一键安装/升级脚本
├── requirements.txt
├── config.example.json               # 配置示例
└── .gitignore
```

## 页面说明

| 路径 | 功能 |
|------|------|
| `/` | 主页：开始选股 / 分析结果 / AI 对话 / 深度分析（Tab 切换） |
| `/login` | 登录页 |
| `/history` | 历史报告列表 |
| `/billing` | 账单与积分详情 |
| `/admin` | 管理员后台（仅管理员可见） |

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/analyze` | POST | 启动批量分析 |
| `/api/stop` | POST | 停止分析 |
| `/api/status` | GET | 获取运行状态 |
| `/api/results` | GET | 获取分析结果 |
| `/api/chat` | POST | AI 对话 |
| `/api/deep-analysis/start` | POST | 启动深度分析 |
| `/api/deep-analysis/stop` | POST | 停止深度分析 |
| `/api/deep-analysis/status` | GET | 深度分析状态 |
| `/api/deep-analysis/download/{file}` | GET | 下载 HTML 看板 |
| `/api/deep-analysis/view/{file}` | GET | 在线查看 HTML 看板 |
| `/api/history` | GET | 历史报告列表 |
| `/api/user/info` | GET | 用户信息 |
| `/ws/logs` | WebSocket | 实时日志推送 |

## 注意事项

- 首次使用请编辑 `config.json` 填入你的 API Key
- 数据存储在 `data/` 目录，结果存储在 `results/` 目录
- 深度分析结果存储在 `deep_work/` 和 `outputs/` 目录
- 这些目录都挂载在宿主机，容器重建不会丢失数据
- `config.json` 包含 API Key，已在 `.gitignore` 中排除，不会被提交

## License

MIT
