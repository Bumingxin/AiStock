#!/usr/bin/env bash
# ============================================================
# AI量化选股系统 - 一键安装/升级脚本
# 用法: bash install.sh
# ============================================================

set -euo pipefail

# ── 配置 ────────────────────────────────────────────────────
IMAGE_NAME="aistock"
CONTAINER_NAME="aistock"
HOST_PORT=8000
CONTAINER_PORT=8000

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. 检查 Docker ──────────────────────────────────────────
info "检查 Docker..."
if ! command -v docker &>/dev/null; then
    err "Docker 未安装，请先安装 Docker：https://docs.docker.com/get-docker/"
fi
if ! docker info &>/dev/null 2>&1; then
    err "Docker daemon 未运行，请先启动 Docker"
fi
ok "Docker $(docker --version | awk '{print $3}')"

# ── 2. 创建目录 ─────────────────────────────────────────────
info "创建数据目录..."
for dir in data results deep_work outputs; do
    mkdir -p "$dir"
done
ok "目录就绪: data/ results/ deep_work/ outputs/"

# ── 3. 生成默认配置（如不存在）──────────────────────────────
if [ ! -f config.json ]; then
    info "生成默认 config.json..."
    cat > config.json <<'CFGEOF'
{
  "openai_base_url": "https://api.openai.com/v1",
  "openai_api_key": "your_api_key",
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
CFGEOF
    warn "已生成默认 config.json，请编辑填入你的 API Key 后重启容器"
else
    ok "config.json 已存在，跳过生成"
fi

# ── 4. 停止旧容器 ───────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    info "停止旧容器..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    ok "旧容器已清理"
fi

# ── 5. 构建镜像 ─────────────────────────────────────────────
info "构建 Docker 镜像 (首次可能需要几分钟)..."
docker build -t "$IMAGE_NAME" .
ok "镜像构建完成"

# ── 5.5 确保数据目录存在且可写 ────────────────────────────────
info "确保数据目录权限..."
for dir in data results deep_work outputs; do
    mkdir -p "$dir"
    chmod 777 "$dir"
done
ok "目录权限就绪"

# ── 6. 启动容器 ─────────────────────────────────────────────
info "启动容器..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${HOST_PORT}:${CONTAINER_PORT}" \
    -v "$(pwd)/config.json:/app/config.json" \
    -v "$(pwd)/data:/app/data" \
    -v "$(pwd)/results:/app/results" \
    -v "$(pwd)/deep_work:/app/deep_work" \
    -v "$(pwd)/outputs:/app/outputs" \
    -v "$(pwd)/config.py:/app/config.py:ro" \
    -v "$(pwd)/database.py:/app/database.py:ro" \
    -v "$(pwd)/auth.py:/app/auth.py:ro" \
    -v "$(pwd)/pipeline.py:/app/pipeline.py:ro" \
    -v "$(pwd)/llm_client.py:/app/llm_client.py:ro" \
    -v "$(pwd)/data_source.py:/app/data_source.py:ro" \
    -v "$(pwd)/news_fetcher.py:/app/news_fetcher.py:ro" \
    -v "$(pwd)/chat_engine.py:/app/chat_engine.py:ro" \
    -v "$(pwd)/web:/app/web:ro" \
    -v "$(pwd)/deep_analysis:/app/deep_analysis:ro" \
    "$IMAGE_NAME"

# ── 7. 等待启动 ─────────────────────────────────────────────
info "等待服务启动..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${HOST_PORT}" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if curl -sf "http://localhost:${HOST_PORT}" >/dev/null 2>&1; then
    ok "服务启动成功!"
else
    warn "服务可能还在启动中，请稍后访问 http://localhost:${HOST_PORT}"
fi

# ── 8. 输出信息 ─────────────────────────────────────────────
echo ""
echo "============================================"
echo -e " ${GREEN}AI量化选股系统 安装完成!${NC}"
echo "============================================"
echo ""
echo " 访问地址:  http://localhost:${HOST_PORT}"
echo " 容器名称:  ${CONTAINER_NAME}"
echo " 数据目录:  ${SCRIPT_DIR}/data/"
echo " 结果目录:  ${SCRIPT_DIR}/results/"
echo " 深度分析:  ${SCRIPT_DIR}/deep_work/ + ${SCRIPT_DIR}/outputs/"
echo ""
echo " 管理命令:"
echo "   查看日志:  docker logs -f ${CONTAINER_NAME}"
echo "   停止:      docker stop ${CONTAINER_NAME}"
echo "   重启:      docker restart ${CONTAINER_NAME}"
echo "   重新构建:  bash install.sh"
echo ""
echo -e " ${YELLOW}提示: 首次使用请编辑 config.json 填入 API Key${NC}"
echo ""