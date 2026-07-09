# AI量化选股系统

基于 LLM 的智能量化选股系统，支持批量筛选和单股深度分析。

## 功能特点

### 批量量化筛选
- 自动抓取全球新闻 → LLM热点提取 → 板块推荐 → 候选池构建 → 多线程技术研判 → 综合排序
- 导航栏「运行监控」Tab 查看执行进度（8阶段实时推送）
- 「分析结果」Tab 查看候选池排行榜，按综合评分排序
- 「AI对话」Tab 对任意标的进行追问
- 支持 A股主板，每板块2-5只候选

### 单股深度分析
- 输入股票代码，自动抓取行情/F10/K线 → 行业自适应评分 → 自动同行对比 → 多智能体博弈(6角色) → 生成金融终端级HTML看板
- 结果展示：评分环形图 + 行动建议 + 风险等级 + 博弈摘要 + 摘要卡片
- 支持下载完整HTML看板（金融终端级深色主题，含K线、信号位、评分拆解、风险热力卡等）

## 技术栈

- 后端：Python 3 + FastAPI + WebSocket + SQLite
- 前端：原生 HTML/CSS/JS（无框架依赖）
- LLM：OpenAI兼容API（支持任意兼容端点）
- 数据源：新浪/腾讯/东方财富/Yahoo Finance
- 部署：Docker

## 快速开始

### 一键安装

```bash
git clone <repository-url>
cd aistock
bash install.sh
```

### 手动安装

1. **克隆项目**
   ```bash
   git clone <repository-url>
   cd aistock
   ```

2. **配置 API Key**
   ```bash
   cp config.example.json config.json
   # 编辑 config.json，填入你的 API Key
   ```

3. **构建 Docker 镜像**
   ```bash
   docker build -t ai-stock .
   ```

4. **启动容器**
   ```bash
   docker run -d \
     --name ai-stock \
     -p 8989:8000 \
     -v $(pwd)/config.json:/app/config.json \
     -v $(pwd)/data:/app/data \
     -v $(pwd)/results:/app/results \
     -v $(pwd)/deep_work:/app/deep_work \
     -v $(pwd)/outputs:/app/outputs \
     ai-stock
   ```

5. **访问系统**
   - 浏览器访问: http://localhost:8989
   - 默认管理员账号: admin / admin

## 配置说明

编辑 `config.json`：

```json
{
  "openai_base_url": "https://api.openai.com/v1",
  "openai_api_key": "your_api_key",
  "model": "gpt-4o",
  "top_sectors": 5,
  "top_stocks": 20,
  "analysis_points_cost": 50,
  "chat_points_cost": 2,
  "deep_analysis_points_cost": 30
}
```

## 常用命令

```bash
# 查看日志
docker logs -f ai-stock

# 停止容器
docker stop ai-stock

# 启动容器
docker start ai-stock

# 重启容器
docker restart ai-stock

# 重新构建
docker build -t ai-stock .
docker rm -f ai-stock
docker run -d --name ai-stock -p 8989:8000 \
  -v $(pwd)/config.json:/app/config.json \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/results:/app/results \
  -v $(pwd)/deep_work:/app/deep_work \
  -v $(pwd)/outputs:/app/outputs \
  ai-stock
```

## 目录结构

```
aistock/
├── web/                          # Web应用
│   ├── app.py                    # FastAPI路由
│   ├── templates/                # HTML模板
│   └── static/                   # CSS/JS
├── deep_analysis/                # 深度分析模块
│   ├── __init__.py
│   ├── pipeline.py               # 流水线封装
│   └── scripts/                  # skill脚本
├── china-stock-deep-analysis/    # 原始skill
├── pipeline.py                   # 批量筛选流水线
├── data_source.py                # 数据抓取模块
├── llm_client.py                 # LLM调用模块
├── news_fetcher.py               # 新闻聚合模块
├── chat_engine.py                # AI对话引擎
├── auth.py                       # 用户认证
├── database.py                   # 数据库操作
├── config.py                     # 配置管理
├── Dockerfile
├── install.sh
└── requirements.txt
```

## 注意事项

- 首次使用请编辑 `config.json` 填入你的 API Key
- 数据存储在 `data/` 目录，结果存储在 `results/` 目录
- 深度分析结果存储在 `deep_work/` 和 `outputs/` 目录
- 这些目录都挂载在宿主机，容器重建不会丢失数据

## License

MIT
