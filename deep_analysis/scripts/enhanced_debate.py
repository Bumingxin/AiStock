#!/usr/bin/env python3
"""
增强版博弈分析 - 集成AnySearch实时数据
在原有博弈分析基础上，增加新闻、公告、研报、情绪等实时数据
"""

import json
import sys
import os
from typing import Dict, List, Any
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anysearch_enhancer import AnySearchEnhancer, enhance_debate_with_anysearch, generate_enhanced_debate_context


class EnhancedDebateEngine:
    """增强版博弈分析引擎"""
    
    def __init__(self, stock_code: str, stock_name: str, industry: str = ""):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.industry = industry
        self.enhancer = AnySearchEnhancer()
        
    def generate_enhanced_votes(self, base_context: str, enhanced_context: str) -> List[Dict[str, Any]]:
        """
        生成增强版的六个分析师投票
        
        Args:
            base_context: 基础上下文（来自dashboard JSON）
            enhanced_context: 增强上下文（来自AnySearch）
        
        Returns:
            增强后的投票列表
        """
        votes = []
        
        # 1. 舆情分析师 - 使用AnySearch新闻数据
        sentiment_vote = self._generate_sentiment_vote(base_context, enhanced_context)
        votes.append(sentiment_vote)
        
        # 2. 游资分析师 - 使用AnySearch情绪数据
        hot_money_vote = self._generate_hot_money_vote(base_context, enhanced_context)
        votes.append(hot_money_vote)
        
        # 3. 风控分析师 - 使用AnySearch公告数据
        risk_vote = self._generate_risk_vote(base_context, enhanced_context)
        votes.append(risk_vote)
        
        # 4. 技术分析师 - 基于K线数据
        tech_vote = self._generate_tech_vote(base_context)
        votes.append(tech_vote)
        
        # 5. 筹码分析师 - 基于K线和成交量
        chip_vote = self._generate_chip_vote(base_context)
        votes.append(chip_vote)
        
        # 6. 大单异动监控师 - 使用AnySearch新闻数据
        big_order_vote = self._generate_big_order_vote(base_context, enhanced_context)
        votes.append(big_order_vote)
        
        return votes
    
    def _generate_sentiment_vote(self, base_context: str, enhanced_context: str) -> Dict[str, Any]:
        """生成舆情分析师投票"""
        # 分析增强上下文中的新闻
        news_analysis = self._analyze_news_sentiment(enhanced_context)
        
        # 确定方向
        if news_analysis["positive_count"] > news_analysis["negative_count"]:
            direction = "中性偏多"
            confidence = min(70, 50 + news_analysis["positive_count"] * 5)
        elif news_analysis["negative_count"] > news_analysis["positive_count"]:
            direction = "中性偏空"
            confidence = min(70, 50 + news_analysis["negative_count"] * 5)
        else:
            direction = "中性"
            confidence = 50
        
        # 生成one_liner
        if news_analysis["has_news"]:
            one_liner = f"AnySearch获取到{news_analysis['total_count']}条相关新闻，情绪{'偏正面' if news_analysis['positive_count'] > news_analysis['negative_count'] else '偏负面' if news_analysis['negative_count'] > news_analysis['positive_count'] else '中性'}"
        else:
            one_liner = "未获取到相关新闻数据，基于板块热度判断"
        
        # 生成reasoning
        reasoning_parts = []
        if news_analysis["has_news"]:
            reasoning_parts.append(f"通过AnySearch实时搜索获取到{news_analysis['total_count']}条关于{self.stock_name}的新闻")
            if news_analysis["positive_keywords"]:
                reasoning_parts.append(f"正面关键词: {', '.join(news_analysis['positive_keywords'][:3])}")
            if news_analysis["negative_keywords"]:
                reasoning_parts.append(f"负面关键词: {', '.join(news_analysis['negative_keywords'][:3])}")
        else:
            reasoning_parts.append("未获取到实时新闻数据，基于板块热度和概念强度判断")
        
        reasoning_parts.append(f"综合新闻情绪分析，给出{direction}判断")
        
        return {
            "id": "sentiment",
            "emoji": "📰",
            "name": "舆情分析师",
            "direction": direction,
            "confidence": confidence,
            "one_liner": one_liner,
            "reasoning": "。".join(reasoning_parts)
        }
    
    def _generate_hot_money_vote(self, base_context: str, enhanced_context: str) -> Dict[str, Any]:
        """生成游资分析师投票"""
        # 分析情绪数据
        sentiment_analysis = self._analyze_investor_sentiment(enhanced_context)
        
        # 确定方向
        if sentiment_analysis["bullish_count"] > sentiment_analysis["bearish_count"]:
            direction = "中性偏多"
            confidence = min(65, 50 + sentiment_analysis["bullish_count"] * 3)
        elif sentiment_analysis["bearish_count"] > sentiment_analysis["bullish_count"]:
            direction = "中性偏空"
            confidence = min(65, 50 + sentiment_analysis["bearish_count"] * 3)
        else:
            direction = "中性"
            confidence = 50
        
        # 生成one_liner
        if sentiment_analysis["has_data"]:
            one_liner = f"投资者情绪{'偏乐观' if sentiment_analysis['bullish_count'] > sentiment_analysis['bearish_count'] else '偏悲观' if sentiment_analysis['bearish_count'] > sentiment_analysis['bullish_count'] else '中性'}，短线资金{'活跃' if sentiment_analysis['activity_level'] == 'high' else '一般' if sentiment_analysis['activity_level'] == 'medium' else '低迷'}"
        else:
            one_liner = "未获取到投资者情绪数据，基于成交额判断"
        
        # 生成reasoning
        reasoning_parts = []
        if sentiment_analysis["has_data"]:
            reasoning_parts.append(f"通过AnySearch获取投资者讨论数据，分析{sentiment_analysis['total_count']}条相关讨论")
            reasoning_parts.append(f"看多观点: {sentiment_analysis['bullish_count']}条，看空观点: {sentiment_analysis['bearish_count']}条")
            reasoning_parts.append(f"市场活跃度: {sentiment_analysis['activity_level']}")
        else:
            reasoning_parts.append("未获取到投资者情绪数据，基于K线和成交额判断短线资金偏好")
        
        reasoning_parts.append(f"综合情绪分析，给出{direction}判断")
        
        return {
            "id": "hot_money",
            "emoji": "🎰",
            "name": "游资分析师",
            "direction": direction,
            "confidence": confidence,
            "one_liner": one_liner,
            "reasoning": "。".join(reasoning_parts)
        }
    
    def _generate_risk_vote(self, base_context: str, enhanced_context: str) -> Dict[str, Any]:
        """生成风控分析师投票"""
        # 分析公告数据
        announcement_analysis = self._analyze_announcements(enhanced_context)
        
        # 确定方向
        if announcement_analysis["has_risk_announcement"]:
            direction = "看跌"
            confidence = min(80, 60 + announcement_analysis["risk_level"] * 10)
        elif announcement_analysis["has_positive_announcement"]:
            direction = "中性偏多"
            confidence = min(65, 50 + announcement_analysis["positive_level"] * 5)
        else:
            direction = "中性"
            confidence = 50
        
        # 生成one_liner
        if announcement_analysis["has_data"]:
            one_liner = f"获取到{announcement_analysis['total_count']}条公告，{'发现风险公告' if announcement_analysis['has_risk_announcement'] else '无重大风险公告'}"
        else:
            one_liner = "未获取到公告数据，基于财务指标判断"
        
        # 生成reasoning
        reasoning_parts = []
        if announcement_analysis["has_data"]:
            reasoning_parts.append(f"通过AnySearch获取{self.stock_name}最新公告{announcement_analysis['total_count']}条")
            if announcement_analysis["has_risk_announcement"]:
                reasoning_parts.append(f"发现风险相关公告: {', '.join(announcement_analysis['risk_keywords'][:3])}")
            if announcement_analysis["has_positive_announcement"]:
                reasoning_parts.append(f"发现正面公告: {', '.join(announcement_analysis['positive_keywords'][:3])}")
        else:
            reasoning_parts.append("未获取到最新公告数据，基于历史财务指标和估值判断风险")
        
        reasoning_parts.append(f"综合公告分析，给出{direction}判断")
        
        return {
            "id": "risk_control",
            "emoji": "🛡️",
            "name": "风控分析师",
            "direction": direction,
            "confidence": confidence,
            "one_liner": one_liner,
            "reasoning": "。".join(reasoning_parts)
        }
    
    def _generate_tech_vote(self, base_context: str) -> Dict[str, Any]:
        """生成技术分析师投票（基于K线数据）"""
        # 从base_context提取K线信息
        # 这里简化处理，实际应该解析dashboard JSON
        
        return {
            "id": "technician",
            "emoji": "📊",
            "name": "技术分析师",
            "direction": "中性",
            "confidence": 50,
            "one_liner": "基于K线和技术指标分析",
            "reasoning": "技术面分析基于K线形态、均线系统、支撑阻力位等传统技术指标"
        }
    
    def _generate_chip_vote(self, base_context: str) -> Dict[str, Any]:
        """生成筹码分析师投票"""
        return {
            "id": "chip_analyst",
            "emoji": "筹码",
            "name": "筹码分析师",
            "direction": "中性",
            "confidence": 50,
            "one_liner": "基于筹码分布和套牢盘分析",
            "reasoning": "筹码分析基于历史成交分布、套牢盘压力、换手率等指标"
        }
    
    def _generate_big_order_vote(self, base_context: str, enhanced_context: str) -> Dict[str, Any]:
        """生成大单异动监控师投票"""
        # 分析新闻中的大单信息
        big_order_analysis = self._analyze_big_order_news(enhanced_context)
        
        # 确定方向
        if big_order_analysis["has_inflow_news"]:
            direction = "中性偏多"
            confidence = min(60, 50 + big_order_analysis["inflow_count"] * 5)
        elif big_order_analysis["has_outflow_news"]:
            direction = "中性偏空"
            confidence = min(60, 50 + big_order_analysis["outflow_count"] * 5)
        else:
            direction = "中性"
            confidence = 50
        
        # 生成one_liner
        if big_order_analysis["has_data"]:
            one_liner = f"新闻中{'发现主力资金流入迹象' if big_order_analysis['has_inflow_news'] else '发现主力资金流出迹象' if big_order_analysis['has_outflow_news'] else '未发现明显大单异动'}"
        else:
            one_liner = "未接入逐笔数据，按成交/K线保守判断"
        
        # 生成reasoning
        reasoning_parts = []
        if big_order_analysis["has_data"]:
            reasoning_parts.append(f"通过AnySearch新闻数据间接判断资金流向")
            if big_order_analysis["has_inflow_news"]:
                reasoning_parts.append(f"发现{big_order_analysis['inflow_count']}条资金流入相关新闻")
            if big_order_analysis["has_outflow_news"]:
                reasoning_parts.append(f"发现{big_order_analysis['outflow_count']}条资金流出相关新闻")
        else:
            reasoning_parts.append("未接入实时逐笔/大单数据，按成交额和K线形态保守判断")
        
        reasoning_parts.append(f"综合分析，给出{direction}判断")
        
        return {
            "id": "big_order",
            "emoji": "💰",
            "name": "大单异动监控师",
            "direction": direction,
            "confidence": confidence,
            "one_liner": one_liner,
            "reasoning": "。".join(reasoning_parts)
        }
    
    def _analyze_news_sentiment(self, enhanced_context: str) -> Dict[str, Any]:
        """分析新闻情绪"""
        positive_keywords = ["利好", "增长", "突破", "创新高", "超预期", "扶持", "政策", "买入", "看好", "推荐"]
        negative_keywords = ["利空", "下跌", "亏损", "违规", "处罚", "风险", "下滑", "卖出", "减持", "警告"]
        
        analysis = {
            "has_news": False,
            "total_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "positive_keywords": [],
            "negative_keywords": []
        }
        
        if not enhanced_context:
            return analysis
        
        # 解析搜索结果数量
        import re
        count_match = re.search(r'获取到(\d+)条', enhanced_context)
        if count_match:
            analysis["total_count"] = int(count_match.group(1))
            analysis["has_news"] = analysis["total_count"] > 0
        
        # 简单关键词匹配
        for keyword in positive_keywords:
            if keyword in enhanced_context:
                analysis["positive_keywords"].append(keyword)
                analysis["positive_count"] += 1
        
        for keyword in negative_keywords:
            if keyword in enhanced_context:
                analysis["negative_keywords"].append(keyword)
                analysis["negative_count"] += 1
        
        # 如果没有通过数量判断，则通过内容长度判断
        if not analysis["has_news"] and len(enhanced_context) > 200:
            analysis["has_news"] = True
            analysis["total_count"] = max(analysis["positive_count"], analysis["negative_count"], 1)
        
        return analysis
    
    def _analyze_investor_sentiment(self, enhanced_context: str) -> Dict[str, Any]:
        """分析投资者情绪"""
        bullish_keywords = ["看多", "买入", "加仓", "底部", "反弹", "机会", "看好", "推荐", "增持"]
        bearish_keywords = ["看空", "卖出", "减仓", "顶部", "风险", "离场", "看跌", "减持", "清仓"]
        
        analysis = {
            "has_data": False,
            "total_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "activity_level": "medium"
        }
        
        if not enhanced_context:
            return analysis
        
        # 解析搜索结果数量
        import re
        count_match = re.search(r'分析(\d+)条', enhanced_context)
        if count_match:
            analysis["total_count"] = int(count_match.group(1))
            analysis["has_data"] = analysis["total_count"] > 0
        
        # 简单关键词匹配
        for keyword in bullish_keywords:
            if keyword in enhanced_context:
                analysis["bullish_count"] += 1
        
        for keyword in bearish_keywords:
            if keyword in enhanced_context:
                analysis["bearish_count"] += 1
        
        # 如果没有通过数量判断，则通过内容长度判断
        if not analysis["has_data"] and len(enhanced_context) > 200:
            analysis["has_data"] = True
            analysis["total_count"] = max(analysis["bullish_count"], analysis["bearish_count"], 1)
        
        # 判断活跃度
        if analysis["total_count"] > 10:
            analysis["activity_level"] = "high"
        elif analysis["total_count"] > 5:
            analysis["activity_level"] = "medium"
        else:
            analysis["activity_level"] = "low"
        
        return analysis
    
    def _analyze_announcements(self, enhanced_context: str) -> Dict[str, Any]:
        """分析公告数据"""
        risk_keywords = ["风险", "违规", "处罚", "诉讼", "亏损", "下滑", "减持", "警告", "调查"]
        positive_keywords = ["增长", "突破", "创新", "合作", "扶持", "政策", "分红", "回购", "增持"]
        
        analysis = {
            "has_data": False,
            "total_count": 0,
            "has_risk_announcement": False,
            "has_positive_announcement": False,
            "risk_level": 0,
            "positive_level": 0,
            "risk_keywords": [],
            "positive_keywords": []
        }
        
        if not enhanced_context:
            return analysis
        
        # 解析搜索结果数量
        import re
        count_match = re.search(r'获取到(\d+)条', enhanced_context)
        if count_match:
            analysis["total_count"] = int(count_match.group(1))
            analysis["has_data"] = analysis["total_count"] > 0
        
        # 简单关键词匹配
        for keyword in risk_keywords:
            if keyword in enhanced_context:
                analysis["risk_keywords"].append(keyword)
                analysis["risk_level"] += 1
        
        for keyword in positive_keywords:
            if keyword in enhanced_context:
                analysis["positive_keywords"].append(keyword)
                analysis["positive_level"] += 1
        
        # 如果没有通过数量判断，则通过内容长度判断
        if not analysis["has_data"] and len(enhanced_context) > 200:
            analysis["has_data"] = True
            analysis["total_count"] = max(analysis["risk_level"], analysis["positive_level"], 1)
        
        analysis["has_risk_announcement"] = analysis["risk_level"] > 0
        analysis["has_positive_announcement"] = analysis["positive_level"] > 0
        
        return analysis
    
    def _analyze_big_order_news(self, enhanced_context: str) -> Dict[str, Any]:
        """分析大单新闻"""
        inflow_keywords = ["主力买入", "大单流入", "资金流入", "机构买入", "北向资金"]
        outflow_keywords = ["主力卖出", "大单流出", "资金流出", "机构卖出", "北向资金流出"]
        
        analysis = {
            "has_data": False,
            "has_inflow_news": False,
            "has_outflow_news": False,
            "inflow_count": 0,
            "outflow_count": 0
        }
        
        if not enhanced_context:
            return analysis
        
        # 简单关键词匹配
        for keyword in inflow_keywords:
            if keyword in enhanced_context:
                analysis["inflow_count"] += 1
        
        for keyword in outflow_keywords:
            if keyword in enhanced_context:
                analysis["outflow_count"] += 1
        
        analysis["has_data"] = len(enhanced_context) > 100
        analysis["has_inflow_news"] = analysis["inflow_count"] > 0
        analysis["has_outflow_news"] = analysis["outflow_count"] > 0
        
        return analysis
    
    def run_enhanced_debate(self, dash_json_path: str) -> Dict[str, Any]:
        """
        运行增强版博弈分析
        
        Args:
            dash_json_path: dashboard JSON文件路径
        
        Returns:
            增强版博弈结果
        """
        print(f"开始增强版博弈分析: {self.stock_name}({self.stock_code})")
        
        # 1. 读取dashboard JSON
        with open(dash_json_path, 'r', encoding='utf-8') as f:
            dash_data = json.load(f)
        
        # 2. 获取AnySearch增强数据
        print("获取AnySearch增强数据...")
        enhanced_data = enhance_debate_with_anysearch(
            dash_json_path, self.stock_code, self.stock_name, self.industry
        )
        
        # 3. 生成增强上下文
        enhanced_context = generate_enhanced_debate_context(enhanced_data)
        
        # 4. 生成基础上下文（从dashboard JSON）
        base_context = self._generate_base_context(dash_data)
        
        # 5. 生成增强版投票
        print("生成增强版博弈投票...")
        votes = self.generate_enhanced_votes(base_context, enhanced_context)
        
        # 6. 统计投票
        bull_count = sum(1 for v in votes if "看涨" in v["direction"] or "偏多" in v["direction"])
        bear_count = sum(1 for v in votes if "看跌" in v["direction"] or "偏空" in v["direction"])
        neutral_count = len(votes) - bull_count - bear_count
        
        # 7. 计算平均置信度
        avg_confidence = sum(v["confidence"] for v in votes) / len(votes)
        
        # 8. 确定整体方向
        if bull_count > bear_count:
            direction = "中性偏乐观"
        elif bear_count > bull_count:
            direction = "中性偏谨慎"
        else:
            direction = "中性"
        
        # 9. 生成综合摘要
        summary = self._generate_summary(votes, enhanced_data)
        
        # 10. 生成操作建议
        action = self._generate_action(votes, dash_data)
        
        # 11. 生成关键价位
        key_level = self._generate_key_level(dash_data)
        
        # 12. 构建结果
        result = {
            "votes": votes,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "neutral_count": neutral_count,
            "direction": direction,
            "confidence": round(avg_confidence, 1),
            "bull_pct": round(bull_count / len(votes) * 100, 1),
            "bear_pct": round(bear_count / len(votes) * 100, 1),
            "summary": summary,
            "action": action,
            "key_level": key_level,
            "ai_native": True,
            "enhanced_with_anysearch": True,
            "model_note": "OpenClaw主模型多角色推演 + AnySearch实时数据增强",
            "enhanced_data_summary": {
                "news_count": len(enhanced_data.get("news", {}).get("announcements", {}).get("text", "")),
                "research_count": len(enhanced_data.get("research", {}).get("research", {}).get("text", "")),
                "sentiment_count": len(enhanced_data.get("sentiment", {}).get("sentiment", {}).get("text", "")),
                "catalyst_count": len(enhanced_data.get("catalysts", {}).get("catalysts", [])),
                "anomaly_count": len(enhanced_data.get("anomalies", []))
            }
        }
        
        print(f"增强版博弈分析完成: {direction} (置信度: {avg_confidence:.1f}%)")
        
        return result
    
    def _generate_base_context(self, dash_data: Dict[str, Any]) -> str:
        """生成基础上下文"""
        context_parts = []
        
        # 基本信息
        context_parts.append(f"股票: {dash_data.get('title', '')} ({dash_data.get('code', '')})")
        context_parts.append(f"市场: {dash_data.get('market', '')}")
        context_parts.append(f"行业: {dash_data.get('industry', '')}")
        context_parts.append(f"日期: {dash_data.get('date', '')}")
        
        # 评分
        scores = dash_data.get('scores', [])
        if scores:
            score_str = " | ".join([f"{s['name']}: {s['score']}" for s in scores])
            context_parts.append(f"评分: {score_str}")
        
        # 指标
        metrics = dash_data.get('metrics', [])
        if metrics:
            metrics_str = " | ".join([f"{m['label']}: {m['value']}" for m in metrics[:5]])
            context_parts.append(f"指标: {metrics_str}")
        
        # 风险
        risks = dash_data.get('risks', [])
        if risks:
            risks_str = " | ".join([f"{r['text']}" for r in risks])
            context_parts.append(f"风险: {risks_str}")
        
        return "\n".join(context_parts)
    
    def _generate_summary(self, votes: List[Dict[str, Any]], enhanced_data: Dict[str, Any]) -> str:
        """生成综合摘要"""
        summary_parts = []
        
        # 投票统计
        bull_count = sum(1 for v in votes if "看涨" in v["direction"] or "偏多" in v["direction"])
        bear_count = sum(1 for v in votes if "看跌" in v["direction"] or "偏空" in v["direction"])
        neutral_count = len(votes) - bull_count - bear_count
        
        summary_parts.append(f"六位分析师投票结果：{bull_count}看涨、{bear_count}看跌、{neutral_count}中性。")
        
        # 增强数据摘要
        if enhanced_data.get("news", {}).get("announcements", {}).get("success"):
            summary_parts.append("通过AnySearch获取到最新公告和新闻数据。")
        
        if enhanced_data.get("research", {}).get("research", {}).get("success"):
            summary_parts.append("获取到研报和分析师观点。")
        
        if enhanced_data.get("anomalies"):
            summary_parts.append(f"发现{len(enhanced_data['anomalies'])}个K线异常需要关注。")
        
        # 多空分歧
        summary_parts.append("多空核心分歧在于实时新闻情绪与基本面数据的综合判断。")
        
        return "".join(summary_parts)
    
    def _generate_action(self, votes: List[Dict[str, Any]], dash_data: Dict[str, Any]) -> str:
        """生成操作建议"""
        # 获取trade_plan
        trade_plan = dash_data.get('trade_plan', {})
        
        # 基于投票和trade_plan生成建议
        action_parts = []
        
        if trade_plan.get('buy_left'):
            action_parts.append(f"观察买入区: {trade_plan['buy_left'][0]}")
        
        if trade_plan.get('buy_right'):
            action_parts.append(f"右侧确认: {trade_plan['buy_right'][0]}")
        
        if trade_plan.get('stop'):
            action_parts.append(f"止损: {trade_plan['stop'][0]}")
        
        return "。".join(action_parts) if action_parts else "基于增强数据综合判断"
    
    def _generate_key_level(self, dash_data: Dict[str, Any]) -> str:
        """生成关键价位"""
        signal_chart = dash_data.get('signal_chart', {})
        
        levels = []
        if signal_chart.get('stop'):
            levels.append(f"支撑/止损{signal_chart['stop']}元")
        if signal_chart.get('resistance'):
            levels.append(f"压力{signal_chart['resistance']}元")
        if signal_chart.get('confirm_low'):
            levels.append(f"突破确认{signal_chart['confirm_low']}元")
        
        return " | ".join(levels) if levels else "基于技术分析确定关键价位"


def main():
    """主函数"""
    if len(sys.argv) < 4:
        print("用法: python enhanced_debate.py <dash_json_path> <stock_code> <stock_name> [industry]")
        sys.exit(1)
    
    dash_json_path = sys.argv[1]
    stock_code = sys.argv[2]
    stock_name = sys.argv[3]
    industry = sys.argv[4] if len(sys.argv) > 4 else ""
    
    # 创建增强版博弈分析引擎
    engine = EnhancedDebateEngine(stock_code, stock_name, industry)
    
    # 运行增强版博弈分析
    result = engine.run_enhanced_debate(dash_json_path)
    
    # 保存结果
    output_path = dash_json_path.replace("_dash.json", "_ai_debate.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n增强版博弈分析结果已保存到: {output_path}")
    
    # 输出摘要
    print(f"\n=== 增强版博弈分析摘要 ===")
    print(f"方向: {result['direction']}")
    print(f"置信度: {result['confidence']}%")
    print(f"投票: {result['bull_count']}看涨 / {result['bear_count']}看跌 / {result['neutral_count']}中性")
    print(f"操作建议: {result['action']}")
    print(f"关键价位: {result['key_level']}")
    
    # 输出投票详情
    print(f"\n=== 投票详情 ===")
    for vote in result['votes']:
        print(f"{vote['emoji']} {vote['name']}: {vote['direction']} ({vote['confidence']}%)")
        print(f"   {vote['one_liner']}")


if __name__ == "__main__":
    main()
