#!/usr/bin/env python3
"""
AnySearch增强模块 - 为股票分析提供实时新闻、公告、研报等数据
集成到博弈分析流程中，增强六个分析师角色的分析深度
"""

import json
import subprocess
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class SearchConfig:
    """搜索配置"""
    cli_path: str = "/root/.openclaw/skills/anysearch/scripts/anysearch_cli.py"
    max_results: int = 5
    timeout: int = 30

class AnySearchEnhancer:
    """AnySearch增强器"""
    
    def __init__(self, config: SearchConfig = None):
        self.config = config or SearchConfig()
        self.cache = {}  # 缓存get_sub_domains结果
        
    def _run_cli(self, command: str) -> Dict[str, Any]:
        """运行anysearch CLI命令"""
        try:
            full_cmd = f"python3 {self.config.cli_path} {command}"
            result = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.config.timeout
            )
            
            if result.returncode != 0:
                return {"error": result.stderr, "success": False}
            
            # 尝试解析JSON输出
            try:
                data = json.loads(result.stdout)
                return {"data": data, "success": True}
            except json.JSONDecodeError:
                # 如果不是JSON，返回原始文本
                return {"text": result.stdout, "success": True}
                
        except subprocess.TimeoutExpired:
            return {"error": "命令执行超时", "success": False}
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_sub_domains(self, domain: str = "finance") -> Dict[str, Any]:
        """获取子域信息（带缓存）"""
        if domain in self.cache:
            return self.cache[domain]
        
        result = self._run_cli(f"get_sub_domains --domain {domain}")
        if result["success"]:
            self.cache[domain] = result
        return result
    
    def search_news(self, stock_name: str, stock_code: str, 
                   period: str = "7d") -> Dict[str, Any]:
        """搜索股票相关新闻"""
        # 获取finance域的子域信息
        sub_domains = self.get_sub_domains("finance")
        
        # 搜索A股公告
        announcement_query = f"{stock_name} {stock_code} 公告"
        announcement_cmd = f'search "{announcement_query}" --domain finance --sub_domain finance.news --sdp type=announcement,cn_code={stock_code}.SH,period={period} --max_results {self.config.max_results}'
        announcement_result = self._run_cli(announcement_cmd)
        
        # 搜索财经新闻
        news_query = f"{stock_name} {stock_code} 最新消息"
        news_cmd = f'search "{news_query}" --domain finance --sub_domain finance.news --sdp type=flash,period={period} --max_results {self.config.max_results}'
        news_result = self._run_cli(news_cmd)
        
        return {
            "announcements": announcement_result,
            "news": news_result,
            "stock_name": stock_name,
            "stock_code": stock_code,
            "period": period
        }
    
    def search_research(self, stock_name: str, stock_code: str) -> Dict[str, Any]:
        """搜索研报和分析师观点"""
        # 搜索研报
        research_query = f"{stock_name} 研报 分析师"
        research_cmd = f'search "{research_query}" --domain finance --sub_domain finance.news --sdp type=general --max_results {self.config.max_results}'
        research_result = self._run_cli(research_cmd)
        
        # 搜索行业分析
        industry_query = f"{stock_name} 行业分析 竞争格局"
        industry_cmd = f'search "{industry_query}" --domain finance --sub_domain finance.news --sdp type=general --max_results {self.config.max_results}'
        industry_result = self._run_cli(industry_cmd)
        
        return {
            "research": research_result,
            "industry": industry_result,
            "stock_name": stock_name,
            "stock_code": stock_code
        }
    
    def search_sentiment(self, stock_name: str, stock_code: str) -> Dict[str, Any]:
        """搜索市场情绪和社交媒体讨论"""
        # 搜索股吧/雪球讨论
        sentiment_query = f"{stock_name} 股吧 讨论"
        sentiment_cmd = f'search "{sentiment_query}" --max_results {self.config.max_results}'
        sentiment_result = self._run_cli(sentiment_cmd)
        
        # 搜索投资者情绪
        investor_query = f"{stock_name} 投资者 情绪"
        investor_cmd = f'search "{investor_query}" --max_results {self.config.max_results}'
        investor_result = self._run_cli(investor_cmd)
        
        return {
            "sentiment": sentiment_result,
            "investor": investor_result,
            "stock_name": stock_name,
            "stock_code": stock_code
        }
    
    def search_catalysts(self, stock_name: str, stock_code: str, 
                        industry: str = "") -> Dict[str, Any]:
        """搜索潜在催化剂"""
        catalysts = []
        
        # 搜索政策动态
        policy_query = f"{stock_name} 政策 扶持"
        policy_cmd = f'search "{policy_query}" --domain finance --sub_domain finance.news --sdp type=general --max_results 3'
        policy_result = self._run_cli(policy_cmd)
        catalysts.append({"type": "policy", "data": policy_result})
        
        # 搜索技术突破
        tech_query = f"{stock_name} 技术 突破 创新"
        tech_cmd = f'search "{tech_query}" --domain finance --sub_domain finance.news --sdp type=general --max_results 3'
        tech_result = self._run_cli(tech_cmd)
        catalysts.append({"type": "technology", "data": tech_result})
        
        # 搜索行业动态
        if industry:
            industry_dynamics_query = f"{industry} 行业 动态 趋势"
            industry_dynamics_cmd = f'search "{industry_dynamics_query}" --domain finance --sub_domain finance.news --sdp type=general --max_results 3'
            industry_dynamics_result = self._run_cli(industry_dynamics_cmd)
            catalysts.append({"type": "industry", "data": industry_dynamics_result})
        
        return {
            "catalysts": catalysts,
            "stock_name": stock_name,
            "stock_code": stock_code,
            "industry": industry
        }
    
    def search_anomaly_reason(self, stock_name: str, stock_code: str, 
                             anomaly_date: str, anomaly_type: str) -> Dict[str, Any]:
        """搜索K线异常原因"""
        # 构建搜索查询
        if anomaly_type == "大跌":
            query = f"{stock_name} {anomaly_date} 大跌 原因"
        elif anomaly_type == "大涨":
            query = f"{stock_name} {anomaly_date} 大涨 原因"
        else:
            query = f"{stock_name} {anomaly_date} 异动 原因"
        
        search_cmd = f'search "{query}" --domain finance --sub_domain finance.news --sdp type=flash --max_results {self.config.max_results}'
        search_result = self._run_cli(search_cmd)
        
        # 搜索公告
        announcement_query = f"{stock_name} {anomaly_date} 公告"
        announcement_cmd = f'search "{announcement_query}" --domain finance --sub_domain finance.news --sdp type=announcement,cn_code={stock_code}.SH --max_results 3'
        announcement_result = self._run_cli(announcement_cmd)
        
        return {
            "reason": search_result,
            "announcements": announcement_result,
            "stock_name": stock_name,
            "stock_code": stock_code,
            "anomaly_date": anomaly_date,
            "anomaly_type": anomaly_type
        }
    
    def batch_search(self, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量并行搜索"""
        # 构建JSON查询数组
        queries_json = json.dumps(queries, ensure_ascii=False)
        
        # 写入临时文件
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(queries_json)
            temp_file = f.name
        
        try:
            cmd = f'batch_search --queries @{temp_file}'
            result = self._run_cli(cmd)
            return result
        finally:
            os.unlink(temp_file)


def enhance_debate_with_anysearch(dash_json_path: str, stock_code: str, 
                                 stock_name: str, industry: str = "") -> Dict[str, Any]:
    """
    使用AnySearch增强博弈分析数据
    
    Args:
        dash_json_path: dashboard JSON文件路径
        stock_code: 股票代码
        stock_name: 股票名称
        industry: 行业（可选）
    
    Returns:
        增强数据字典
    """
    enhancer = AnySearchEnhancer()
    
    # 读取dashboard JSON
    with open(dash_json_path, 'r', encoding='utf-8') as f:
        dash_data = json.load(f)
    
    # 获取K线异常数据
    kline_data = dash_data.get('kline', [])
    anomalies = []
    
    # 检查异常K线（单日涨跌>10%）
    for kline in kline_data:
        if kline.get('open') and kline.get('close'):
            change_pct = (kline['close'] - kline['open']) / kline['open'] * 100
            if abs(change_pct) > 10:
                anomaly_type = "大涨" if change_pct > 0 else "大跌"
                anomalies.append({
                    "date": kline['date'],
                    "type": anomaly_type,
                    "change_pct": change_pct
                })
    
    # 执行增强搜索
    enhanced_data = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "industry": industry,
        "timestamp": datetime.now().isoformat(),
        "news": {},
        "research": {},
        "sentiment": {},
        "catalysts": {},
        "anomalies": []
    }
    
    # 1. 搜索新闻和公告
    print(f"搜索 {stock_name}({stock_code}) 新闻和公告...")
    enhanced_data["news"] = enhancer.search_news(stock_name, stock_code)
    
    # 2. 搜索研报和分析师观点
    print(f"搜索 {stock_name}({stock_code}) 研报和分析师观点...")
    enhanced_data["research"] = enhancer.search_research(stock_name, stock_code)
    
    # 3. 搜索市场情绪
    print(f"搜索 {stock_name}({stock_code}) 市场情绪...")
    enhanced_data["sentiment"] = enhancer.search_sentiment(stock_name, stock_code)
    
    # 4. 搜索潜在催化剂
    print(f"搜索 {stock_name}({stock_code}) 潜在催化剂...")
    enhanced_data["catalysts"] = enhancer.search_catalysts(stock_name, stock_code, industry)
    
    # 5. 搜索异常原因
    if anomalies:
        print(f"搜索 {stock_name}({stock_code}) K线异常原因...")
        for anomaly in anomalies[:3]:  # 最多处理3个异常
            anomaly_reason = enhancer.search_anomaly_reason(
                stock_name, stock_code, anomaly['date'], anomaly['type']
            )
            enhanced_data["anomalies"].append({
                "date": anomaly['date'],
                "type": anomaly['type'],
                "change_pct": anomaly['change_pct'],
                "reason": anomaly_reason
            })
    
    return enhanced_data


def parse_search_results(text: str) -> Dict[str, Any]:
    """解析AnySearch返回的Markdown格式搜索结果"""
    import re
    
    result = {
        "has_data": False,
        "count": 0,
        "items": [],
        "keywords": [],
        "summary": ""
    }
    
    if not text or "Search Results" not in text:
        return result
    
    # 提取结果数量
    count_match = re.search(r'\((\d+) results', text)
    if count_match:
        result["count"] = int(count_match.group(1))
    
    # 提取每个结果
    items = re.findall(r'### \d+\. (.+?)(?=### \d+\.|$)', text, re.DOTALL)
    for item in items[:5]:  # 最多处理5个结果
        item_text = item.strip()
        if item_text:
            result["items"].append(item_text)
    
    # 提取关键词
    keywords = re.findall(r'\*\*(.+?)\*\*', text)
    result["keywords"] = list(set(keywords))[:10]  # 去重，最多10个
    
    result["has_data"] = result["count"] > 0 or len(result["items"]) > 0
    result["summary"] = f"获取到{result['count']}条结果，包含{len(result['items'])}条详细信息"
    
    return result


def generate_enhanced_debate_context(enhanced_data: Dict[str, Any]) -> str:
    """
    生成增强的博弈分析上下文文本
    
    Args:
        enhanced_data: 增强数据字典
    
    Returns:
        格式化的上下文文本
    """
    context_parts = []
    
    # 新闻摘要
    if enhanced_data.get("news"):
        context_parts.append("=== 最新新闻和公告 ===")
        news = enhanced_data["news"]
        
        # 解析公告数据
        if news.get("announcements", {}).get("success"):
            parsed = parse_search_results(news["announcements"].get("text", ""))
            if parsed["has_data"]:
                context_parts.append(f"【公告】{parsed['summary']}")
                for item in parsed["items"][:3]:
                    context_parts.append(f"- {item[:200]}")
        
        # 解析新闻数据
        if news.get("news", {}).get("success"):
            parsed = parse_search_results(news["news"].get("text", ""))
            if parsed["has_data"]:
                context_parts.append(f"【财经新闻】{parsed['summary']}")
                for item in parsed["items"][:3]:
                    context_parts.append(f"- {item[:200]}")
    
    # 研报摘要
    if enhanced_data.get("research"):
        context_parts.append("\n=== 研报和分析师观点 ===")
        research = enhanced_data["research"]
        
        if research.get("research", {}).get("success"):
            parsed = parse_search_results(research["research"].get("text", ""))
            if parsed["has_data"]:
                context_parts.append(f"【研报】{parsed['summary']}")
                for item in parsed["items"][:3]:
                    context_parts.append(f"- {item[:200]}")
        
        if research.get("industry", {}).get("success"):
            parsed = parse_search_results(research["industry"].get("text", ""))
            if parsed["has_data"]:
                context_parts.append(f"【行业分析】{parsed['summary']}")
                for item in parsed["items"][:3]:
                    context_parts.append(f"- {item[:200]}")
    
    # 市场情绪
    if enhanced_data.get("sentiment"):
        context_parts.append("\n=== 市场情绪 ===")
        sentiment = enhanced_data["sentiment"]
        
        if sentiment.get("sentiment", {}).get("success"):
            parsed = parse_search_results(sentiment["sentiment"].get("text", ""))
            if parsed["has_data"]:
                context_parts.append(f"【投资者讨论】{parsed['summary']}")
                for item in parsed["items"][:3]:
                    context_parts.append(f"- {item[:200]}")
    
    # 催化剂
    if enhanced_data.get("catalysts"):
        context_parts.append("\n=== 潜在催化剂 ===")
        catalysts = enhanced_data["catalysts"]
        for cat in catalysts.get("catalysts", []):
            if cat.get("data", {}).get("success"):
                parsed = parse_search_results(cat["data"].get("text", ""))
                if parsed["has_data"]:
                    context_parts.append(f"【{cat['type']}】{parsed['summary']}")
                    for item in parsed["items"][:2]:
                        context_parts.append(f"- {item[:200]}")
    
    # 异常原因
    if enhanced_data.get("anomalies"):
        context_parts.append("\n=== K线异常原因 ===")
        for anomaly in enhanced_data["anomalies"]:
            context_parts.append(f"【{anomaly['date']} {anomaly['type']} {anomaly['change_pct']:.2f}%】")
            if anomaly.get("reason", {}).get("reason", {}).get("success"):
                parsed = parse_search_results(anomaly["reason"]["reason"].get("text", ""))
                if parsed["has_data"]:
                    context_parts.append(f"  原因分析: {parsed['summary']}")
                    for item in parsed["items"][:2]:
                        context_parts.append(f"  - {item[:200]}")
    
    return "\n".join(context_parts)


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) < 4:
        print("用法: python anysearch_enhancer.py <dash_json_path> <stock_code> <stock_name> [industry]")
        sys.exit(1)
    
    dash_json_path = sys.argv[1]
    stock_code = sys.argv[2]
    stock_name = sys.argv[3]
    industry = sys.argv[4] if len(sys.argv) > 4 else ""
    
    # 执行增强
    enhanced_data = enhance_debate_with_anysearch(
        dash_json_path, stock_code, stock_name, industry
    )
    
    # 生成上下文
    context = generate_enhanced_debate_context(enhanced_data)
    
    # 输出结果
    print(context)
    
    # 保存到文件
    output_path = dash_json_path.replace("_dash.json", "_enhanced.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(enhanced_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n增强数据已保存到: {output_path}")
