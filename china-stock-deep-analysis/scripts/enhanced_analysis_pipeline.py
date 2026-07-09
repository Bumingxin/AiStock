#!/usr/bin/env python3
"""
增强版股票分析流水线 - 集成AnySearch实时数据
完整流程: 数据抓取 → 评分 → 同行对比 → AnySearch增强 → 博弈分析 → HTML渲染
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from typing import Dict, List, Any

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anysearch_enhancer import AnySearchEnhancer, enhance_debate_with_anysearch, generate_enhanced_debate_context
from enhanced_debate import EnhancedDebateEngine


class EnhancedAnalysisPipeline:
    """增强版分析流水线"""
    
    def __init__(self, stock_code: str, market: str = "a", industry: str = "", 
                 quick: bool = False, no_debate: bool = False):
        self.stock_code = stock_code
        self.market = market
        self.industry = industry
        self.quick = quick
        self.no_debate = no_debate
        
        # 设置工作目录
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.skill_dir = os.path.dirname(self.base_dir)
        # 使用固定的workspace路径，与generate_stock_dashboard.py一致
        self.work_dir = "/root/.openclaw/workspace/stock_work"
        self.output_dir = "/root/.openclaw/workspace/outputs"
        
        # 确保目录存在
        os.makedirs(self.work_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 文件路径
        self.raw_json_path = os.path.join(self.work_dir, f"{self.stock_code}_raw.json")
        self.dash_json_path = os.path.join(self.work_dir, f"{self.stock_code}_dash.json")
        self.peers_json_path = os.path.join(self.work_dir, f"{self.stock_code}_peers.json")
        self.debate_json_path = os.path.join(self.work_dir, f"{self.stock_code}_ai_debate.json")
        self.html_output_path = os.path.join(self.output_dir, f"stock_{self.stock_code}_{datetime.now().strftime('%Y%m%d')}.html")
        
        # 日期
        self.date = datetime.now().strftime('%Y%m%d')
    
    def run_step(self, step_name: str, command: str) -> bool:
        """运行流水线步骤"""
        print(f"\n{'='*60}")
        print(f"步骤: {step_name}")
        print(f"命令: {command}")
        print(f"{'='*60}")
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                print(f"步骤失败: {step_name}")
                print(f"错误: {result.stderr}")
                return False
            
            print(f"步骤完成: {step_name}")
            if result.stdout:
                print(f"输出: {result.stdout[:500]}...")
            
            return True
            
        except subprocess.TimeoutExpired:
            print(f"步骤超时: {step_name}")
            return False
        except Exception as e:
            print(f"步骤异常: {step_name}, 错误: {str(e)}")
            return False
    
    def step1_fetch_data(self) -> bool:
        """步骤1: 抓取数据"""
        command = f"python3 {self.base_dir}/generate_stock_dashboard.py --code {self.stock_code} --market {self.market} --json"
        
        if self.industry:
            command += f" --industry {self.industry}"
        
        if self.quick:
            command += " --quick"
        
        # 始终跳过基础博弈分析，使用增强版博弈分析
        command += " --no-debate"
        
        return self.run_step("数据抓取", command)
    
    def step2_anysearch_enhancement(self) -> bool:
        """步骤2: AnySearch增强"""
        if not os.path.exists(self.dash_json_path):
            print(f"Dashboard JSON文件不存在: {self.dash_json_path}")
            return False
        
        # 读取股票名称
        try:
            with open(self.dash_json_path, 'r', encoding='utf-8') as f:
                dash_data = json.load(f)
                stock_name = dash_data.get('title', '')
                industry = dash_data.get('industry', '')
        except Exception as e:
            print(f"读取Dashboard JSON失败: {str(e)}")
            return False
        
        if not stock_name:
            print("无法获取股票名称")
            return False
        
        print(f"股票名称: {stock_name}")
        print(f"行业: {industry}")
        
        # 执行AnySearch增强
        try:
            enhanced_data = enhance_debate_with_anysearch(
                self.dash_json_path, self.stock_code, stock_name, industry
            )
            
            # 保存增强数据
            enhanced_json_path = self.dash_json_path.replace("_dash.json", "_enhanced.json")
            with open(enhanced_json_path, 'w', encoding='utf-8') as f:
                json.dump(enhanced_data, f, ensure_ascii=False, indent=2)
            
            print(f"AnySearch增强数据已保存: {enhanced_json_path}")
            return True
            
        except Exception as e:
            print(f"AnySearch增强失败: {str(e)}")
            return False
    
    def step3_debate_analysis(self) -> bool:
        """步骤3: 博弈分析"""
        if self.no_debate:
            print("跳过博弈分析")
            return True
        
        if not os.path.exists(self.dash_json_path):
            print(f"Dashboard JSON文件不存在: {self.dash_json_path}")
            return False
        
        # 读取股票名称
        try:
            with open(self.dash_json_path, 'r', encoding='utf-8') as f:
                dash_data = json.load(f)
                stock_name = dash_data.get('title', '')
                industry = dash_data.get('industry', '')
        except Exception as e:
            print(f"读取Dashboard JSON失败: {str(e)}")
            return False
        
        if not stock_name:
            print("无法获取股票名称")
            return False
        
        # 尝试使用增强版博弈分析
        try:
            engine = EnhancedDebateEngine(self.stock_code, stock_name, industry)
            result = engine.run_enhanced_debate(self.dash_json_path)
            
            # 保存结果
            with open(self.debate_json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print(f"增强版博弈分析结果已保存: {self.debate_json_path}")
            return True
            
        except Exception as e:
            print(f"增强版博弈分析失败: {str(e)}")
            print("尝试使用基础博弈分析...")
            
            # 回退到基础博弈分析
            command = f"python3 {self.base_dir}/debate_engine.py --input {self.dash_json_path} --output {self.debate_json_path}"
            return self.run_step("基础博弈分析", command)
    
    def step4_merge_debate(self) -> bool:
        """步骤4: 合并博弈结果"""
        if self.no_debate:
            print("跳过博弈合并")
            return True
        
        if not os.path.exists(self.debate_json_path):
            print(f"博弈结果文件不存在: {self.debate_json_path}")
            return False
        
        command = f"python3 {self.base_dir}/merge_debate.py --dashboard {self.dash_json_path} --debate {self.debate_json_path}"
        return self.run_step("合并博弈结果", command)
    
    def step5_render_html(self) -> bool:
        """步骤5: 渲染HTML"""
        command = f"python3 {self.base_dir}/render_dashboard.py --input {self.dash_json_path} --out {self.html_output_path}"
        return self.run_step("渲染HTML", command)
    
    def step6_validate(self) -> bool:
        """步骤6: 验证结果"""
        print(f"\n{'='*60}")
        print("步骤: 验证结果")
        print(f"{'='*60}")
        
        # 验证HTML文件
        if not os.path.exists(self.html_output_path):
            print(f"HTML文件不存在: {self.html_output_path}")
            return False
        
        if os.path.getsize(self.html_output_path) == 0:
            print(f"HTML文件为空: {self.html_output_path}")
            return False
        
        # 验证博弈结果
        if not self.no_debate and os.path.exists(self.debate_json_path):
            try:
                with open(self.debate_json_path, 'r', encoding='utf-8') as f:
                    debate_data = json.load(f)
                
                if not debate_data.get('votes'):
                    print("博弈结果缺少votes字段")
                    return False
                
                if len(debate_data['votes']) != 6:
                    print(f"博弈结果votes数量错误: {len(debate_data['votes'])} (应为6)")
                    return False
                
                if not debate_data.get('summary'):
                    print("博弈结果缺少summary字段")
                    return False
                
                if not debate_data.get('action'):
                    print("博弈结果缺少action字段")
                    return False
                
                if not debate_data.get('key_level'):
                    print("博弈结果缺少key_level字段")
                    return False
                
                # 验证AnySearch增强标记
                if debate_data.get('enhanced_with_anysearch'):
                    print("✓ 检测到AnySearch增强标记")
                
                print("✓ 博弈结果验证通过")
                
            except Exception as e:
                print(f"验证博弈结果失败: {str(e)}")
                return False
        
        print("✓ 所有验证通过")
        return True
    
    def run(self) -> bool:
        """运行完整流水线"""
        print(f"\n{'#'*60}")
        print(f"增强版股票分析流水线")
        print(f"股票: {self.stock_code}")
        print(f"市场: {self.market}")
        print(f"行业: {self.industry or '自动识别'}")
        print(f"快速模式: {'是' if self.quick else '否'}")
        print(f"跳过博弈: {'是' if self.no_debate else '否'}")
        print(f"日期: {self.date}")
        print(f"{'#'*60}")
        
        # 执行流水线步骤
        steps = [
            ("数据抓取", self.step1_fetch_data),
            ("AnySearch增强", self.step2_anysearch_enhancement),
            ("博弈分析", self.step3_debate_analysis),
            ("合并博弈结果", self.step4_merge_debate),
            ("渲染HTML", self.step5_render_html),
            ("验证结果", self.step6_validate),
        ]
        
        for step_name, step_func in steps:
            if not step_func():
                print(f"\n流水线在步骤 '{step_name}' 失败")
                return False
        
        print(f"\n{'#'*60}")
        print("流水线完成!")
        print(f"HTML输出: {self.html_output_path}")
        print(f"{'#'*60}")
        
        return True


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='增强版股票分析流水线')
    parser.add_argument('--code', required=True, help='股票代码')
    parser.add_argument('--market', default='a', choices=['auto', 'a', 'hk', 'us'], help='市场类型')
    parser.add_argument('--industry', default='', help='行业类型')
    parser.add_argument('--quick', action='store_true', help='快速模式')
    parser.add_argument('--no-debate', action='store_true', help='跳过博弈分析')
    
    args = parser.parse_args()
    
    # 创建流水线
    pipeline = EnhancedAnalysisPipeline(
        stock_code=args.code,
        market=args.market,
        industry=args.industry,
        quick=args.quick,
        no_debate=args.no_debate
    )
    
    # 运行流水线
    success = pipeline.run()
    
    if success:
        print(f"\n分析完成!")
        print(f"HTML看板: {pipeline.html_output_path}")
        print(f"MEDIA:{pipeline.html_output_path}")
        sys.exit(0)
    else:
        print(f"\n分析失败!")
        sys.exit(1)


if __name__ == "__main__":
    main()
