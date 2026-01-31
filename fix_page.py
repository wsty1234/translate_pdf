#!/usr/bin/env python3
"""
单独页面修复脚本

功能：当发现 intermediate 目录中某页有问题时，
可以单独重新处理该页面并替换原文件，然后重新合并完整的 output.md

使用方法:
    # 修复第5页
    python fix_page.py output 5
    
    # 修复多页
    python fix_page.py output 3,5,7
    
    # 只生成单页文件，不重新合并 output.md
    python fix_page.py output 5 --no-merge
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import time
from datetime import datetime
import base64

from pdf2image import convert_from_path
from PIL import Image
import requests

# 加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class APIClient:
    """API客户端"""
    
    def __init__(self, api_key: str, api_base: str, model: str, max_retries: int = 3, timeout: int = 120):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def encode_image_to_base64(self, image_path: str) -> str:
        """将图片编码为base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def call_with_image(self, image_path: str, prompt: str, max_tokens: int = 10000) -> str:
        """调用多模态API（带图片）"""
        base64_image = self.encode_image_to_base64(image_path)
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2
        }
        
        return self._make_request(payload)
    
    def _make_request(self, payload: dict) -> str:
        """发送请求"""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                print(f"  ⚠️ API调用失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        
        raise last_error if last_error else RuntimeError("API调用失败")


class PageFixer:
    """页面修复器"""
    
    def __init__(
        self,
        output_dir: str,
        api_key: str,
        api_base: str,
        model: str,
        max_retries: int = 3,
        timeout: int = 120
    ):
        self.output_dir = Path(output_dir)
        self.api_client = APIClient(api_key, api_base, model, max_retries, timeout)
        
        # 验证目录结构
        self.pages_dir = self.output_dir / "pages"
        self.figures_dir = self.output_dir / "figures"
        self.tables_dir = self.output_dir / "tables"
        self.intermediate_dir = self.output_dir / "intermediate"
        self.raw_extracted_dir = self.intermediate_dir / "01_raw_extracted"
        self.with_images_dir = self.intermediate_dir / "02_with_images"
        
        if not self.pages_dir.exists():
            raise FileNotFoundError(f"pages 目录不存在: {self.pages_dir}")
    
    def get_total_pages(self) -> int:
        """获取总页数"""
        page_files = list(self.pages_dir.glob("page_*.png"))
        return len(page_files)
    
    def extract_figures_and_tables(
        self, 
        image_path: str, 
        page_num: int
    ) -> Tuple[List[Dict], List[Dict]]:
        """从页面中提取插图和表格（覆盖原文件）"""
        print(f"  🔍 正在重新识别第 {page_num} 页的插图和表格...")
        
        prompt = """请分析这张学术论文页面，识别所有的插图（figures）和表格（tables）。

识别要求：
1. 识别 Figure/Fig. 和 Table，获取编号和标题
2. 边界框坐标 [x_min, y_min, x_max, y_max]（相对于图片的百分比）
3. 紧密包围整个插图/表格及其标题

输出JSON格式：
{
    "figures": [
        {"id": "Figure 1", "title": "...", "bbox": [0.1, 0.2, 0.9, 0.6]}
    ],
    "tables": [
        {"id": "Table 1", "title": "...", "bbox": [0.1, 0.7, 0.9, 0.95]}
    ]
}

没有找到则返回空数组。只返回JSON。"""
        
        try:
            response = self.api_client.call_with_image(image_path, prompt, max_tokens=10000)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = {"figures": [], "tables": []}
        except Exception as e:
            print(f"    ⚠️ 识别失败: {e}")
            data = {"figures": [], "tables": []}
        
        # 确保输出目录存在
        self.figures_dir.mkdir(exist_ok=True)
        self.tables_dir.mkdir(exist_ok=True)
        
        figures = []
        tables = []
        
        # 处理插图
        img = Image.open(image_path)
        width, height = img.size
        
        for fig in data.get("figures", []):
            try:
                bbox = fig.get("bbox", [0, 0, 1, 1])
                left = max(0, int(bbox[0] * width))
                top = max(0, int(bbox[1] * height))
                right = min(width, int(bbox[2] * width))
                bottom = min(height, int(bbox[3] * height))
                
                if right - left < 50 or bottom - top < 50:
                    continue
                
                cropped = img.crop((left, top, right, bottom))
                fig_id = fig.get("id", f"Figure_{page_num}")
                
                # 确保文件名包含page_num
                safe_id = re.sub(r'[^\w]', '_', fig_id.lower())
                fig_filename = f"page{page_num:03d}_{safe_id}.png"
                
                fig_relative_path = f"figures/{fig_filename}"
                fig_absolute_path = self.figures_dir / fig_filename
                cropped.save(fig_absolute_path, "PNG")
                
                figures.append({
                    "id": fig_id,
                    "title": fig.get("title", ""),
                    "path": fig_relative_path,
                    "absolute_path": str(fig_absolute_path),
                    "filename": fig_filename,
                    "page": page_num
                })
                print(f"    ✓ 已提取/覆盖插图: {fig_id} → {fig_filename}")
            except Exception as e:
                print(f"    ⚠️ 提取插图失败: {e}")
        
        # 处理表格
        for tab in data.get("tables", []):
            try:
                bbox = tab.get("bbox", [0, 0, 1, 1])
                left = max(0, int(bbox[0] * width))
                top = max(0, int(bbox[1] * height))
                right = min(width, int(bbox[2] * width))
                bottom = min(height, int(bbox[3] * height))
                
                if right - left < 50 or bottom - top < 50:
                    continue
                
                cropped = img.crop((left, top, right, bottom))
                tab_id = tab.get("id", f"Table_{page_num}")
                
                safe_id = re.sub(r'[^\w]', '_', tab_id.lower())
                tab_filename = f"page{page_num:03d}_{safe_id}.png"
                
                tab_relative_path = f"tables/{tab_filename}"
                tab_absolute_path = self.tables_dir / tab_filename
                cropped.save(tab_absolute_path, "PNG")
                
                tables.append({
                    "id": tab_id,
                    "title": tab.get("title", ""),
                    "path": tab_relative_path,
                    "absolute_path": str(tab_absolute_path),
                    "filename": tab_filename,
                    "page": page_num
                })
                print(f"    ✓ 已提取/覆盖表格: {tab_id} → {tab_filename}")
            except Exception as e:
                print(f"    ⚠️ 提取表格失败: {e}")
        
        return figures, tables
    
    def extract_text_from_page(
        self,
        image_path: str,
        page_num: int,
        total_pages: int
    ) -> str:
        """从页面图片中提取英文文本"""
        print(f"  📝 正在重新提取第 {page_num} 页的英文文本...")
        
        prompt = f"""请仔细分析这张学术论文页面的图片，提取页面上的所有英文文本内容。

**重要：提取范围要求**
1. **只提取正文文字**，不包括：
   - ❌ 图片（Figure）中的文字
   - ❌ 表格（Table）中的文字
   - ❌ 图片和表格的标题（Figure X:, Table X:）

2. **只提取以下文字内容**：
   - ✓ 标题（Title, Section headers等）
   - ✓ 正文段落
   - ✓ 摘要、引言、方法、结果、结论
   - ✓ 参考文献引用标记
   - ✓ 页眉页脚信息

3. **阅读顺序要求**：
   - 双栏布局：先左栏后右栏
   - 单栏布局：从上到下

4. **格式要求**：
   - 使用Markdown格式
   - 标题用 # ## ### 标记
   - 段落之间保留空行
   - 数学公式保留 LaTeX 格式

5. **标注插图和表格位置**：
   - 在插图出现的位置标记：[FIGURE: Figure 1]
   - 在表格出现的位置标记：[TABLE: Table 1]

请直接返回提取的文本。"""
        
        raw_text = self.api_client.call_with_image(image_path, prompt, max_tokens=10000)
        
        # 保存到中间结果
        self.raw_extracted_dir.mkdir(parents=True, exist_ok=True)
        raw_file = self.raw_extracted_dir / f"page_{page_num:03d}.md"
        with open(raw_file, 'w', encoding='utf-8') as f:
            f.write(raw_text)
        print(f"    ✓ 已保存原始提取: {raw_file}")
        
        return raw_text
    
    def insert_image_references(
        self,
        markdown: str,
        figures: List[Dict],
        tables: List[Dict],
        page_num: int
    ) -> str:
        """为单页插入图片引用"""
        print(f"  🖼️  正在为第 {page_num} 页插入图片引用...")
        
        inserted_count = 0
        
        # 替换 [FIGURE: X] 标记
        for fig in figures:
            fig_id = fig["id"]
            patterns = [
                rf'\[FIGURE:\s*{re.escape(fig_id)}\]',
                rf'\[FIGURE:\s*{re.escape(fig_id.replace(" ", ""))}\]',
                rf'\[FIGURE:\s*{re.escape(fig_id.replace("Figure ", "Fig. "))}\]',
            ]
            
            for pattern in patterns:
                if re.search(pattern, markdown, re.IGNORECASE):
                    img_ref = f'\n\n![{fig_id}: {fig.get("title", "")}]({fig["path"]})\n\n'
                    markdown = re.sub(pattern, img_ref, markdown, flags=re.IGNORECASE, count=1)
                    inserted_count += 1
                    print(f"    ✓ 已插入 {fig_id}")
                    break
            else:
                # 如果没找到标记，在文本中插入
                text_patterns = [
                    rf'{re.escape(fig_id)}[\s\.,;:]',
                    rf'{re.escape(fig_id.replace(" ", ""))}[\s\.,;:]',
                ]
                for text_pattern in text_patterns:
                    match = re.search(text_pattern, markdown, re.IGNORECASE)
                    if match:
                        insert_pos = match.start()
                        img_ref = f'\n\n![{fig_id}: {fig.get("title", "")}]({fig["path"]})\n\n'
                        markdown = markdown[:insert_pos] + img_ref + markdown[insert_pos:]
                        inserted_count += 1
                        print(f"    ✓ 已在文本位置插入 {fig_id}")
                        break
        
        # 替换 [TABLE: X] 标记
        for tab in tables:
            tab_id = tab["id"]
            patterns = [
                rf'\[TABLE:\s*{re.escape(tab_id)}\]',
                rf'\[TABLE:\s*{re.escape(tab_id.replace(" ", ""))}\]',
            ]
            
            for pattern in patterns:
                if re.search(pattern, markdown, re.IGNORECASE):
                    img_ref = f'\n\n![{tab_id}: {tab.get("title", "")}]({tab["path"]})\n\n'
                    markdown = re.sub(pattern, img_ref, markdown, flags=re.IGNORECASE, count=1)
                    inserted_count += 1
                    print(f"    ✓ 已插入 {tab_id}")
                    break
            else:
                text_patterns = [
                    rf'{re.escape(tab_id)}[\s\.,;:]',
                    rf'{re.escape(tab_id.replace(" ", ""))}[\s\.,;:]',
                ]
                for text_pattern in text_patterns:
                    match = re.search(text_pattern, markdown, re.IGNORECASE)
                    if match:
                        insert_pos = match.start()
                        img_ref = f'\n\n![{tab_id}: {tab.get("title", "")}]({tab["path"]})\n\n'
                        markdown = markdown[:insert_pos] + img_ref + markdown[insert_pos:]
                        inserted_count += 1
                        print(f"    ✓ 已在文本位置插入 {tab_id}")
                        break
        
        print(f"    总计插入 {inserted_count} 个图片/表格")
        
        return markdown
    
    def fix_single_page(self, page_num: int) -> str:
        """修复单页"""
        print(f"\n{'='*70}")
        print(f"🔧 正在修复第 {page_num} 页")
        print(f"{'='*70}")
        
        # 检查原始图片是否存在
        image_path = self.pages_dir / f"page_{page_num:03d}.png"
        if not image_path.exists():
            raise FileNotFoundError(f"第 {page_num} 页图片不存在: {image_path}")
        
        total_pages = self.get_total_pages()
        
        # 步骤1：提取插图和表格（覆盖原文件）
        figures, tables = self.extract_figures_and_tables(str(image_path), page_num)
        
        # 步骤2：提取英文文本
        raw_text = self.extract_text_from_page(str(image_path), page_num, total_pages)
        
        # 步骤3：插入图片引用
        processed_markdown = self.insert_image_references(raw_text, figures, tables, page_num)
        
        # 步骤4：保存到中间结果（覆盖原文件）
        self.with_images_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.with_images_dir / f"page_{page_num:03d}.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(processed_markdown)
        
        print(f"\n✅ 第 {page_num} 页修复完成！")
        print(f"   原始图片: {image_path}")
        print(f"   提取文件: {self.raw_extracted_dir / f'page_{page_num:03d}.md'}")
        print(f"   最终文件: {output_file}")
        print(f"   图片数: {len(figures)}, 表格数: {len(tables)}")
        
        return str(output_file)
    
    def merge_all_pages(self):
        """重新合并所有页面生成 output.md"""
        print(f"\n{'='*70}")
        print("📝 正在重新合并所有页面...")
        print(f"{'='*70}")
        
        total_pages = self.get_total_pages()
        print(f"  总页数: {total_pages}")
        
        # 收集所有页面
        all_pages = []
        missing_pages = []
        
        for i in range(1, total_pages + 1):
            page_file = self.with_images_dir / f"page_{i:03d}.md"
            if page_file.exists():
                with open(page_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                all_pages.append(content)
                print(f"  ✓ 已加载第 {i} 页")
            else:
                missing_pages.append(i)
                print(f"  ⚠️  第 {i} 页文件不存在: {page_file}")
        
        if missing_pages:
            print(f"\n⚠️  警告: 以下页面文件缺失: {missing_pages}")
            print(f"   这些页面将不会被包含在最终的 output.md 中")
            response = input("   是否继续? (y/n): ")
            if response.lower() != 'y':
                print("   操作已取消")
                return None
        
        # 合并
        full_markdown = "\n\n---\n\n".join(all_pages)
        
        # 后处理
        full_markdown = re.sub(r'\n{3,}', '\n\n', full_markdown)
        full_markdown = re.sub(r'!\[([^\]]*)\]\s*\(\s*([^)]+)\s*\)', r'![\1](\2)', full_markdown)
        full_markdown = full_markdown.strip()
        
        # 保存
        output_file = self.output_dir / "output.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(full_markdown)
        
        print(f"\n✅ 合并完成！")
        print(f"   输出文件: {output_file}")
        print(f"   包含页面: {len(all_pages)}/{total_pages}")
        print(f"   总字符数: {len(full_markdown)}")
        
        return str(output_file)
    
    def update_summary(self, page_num: int, figures: List[Dict], tables: List[Dict]):
        """更新 summary.json"""
        summary_file = self.output_dir / "summary.json"
        
        if summary_file.exists():
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary = json.load(f)
        else:
            summary = {
                "total_pages": self.get_total_pages(),
                "figures_count": 0,
                "tables_count": 0,
                "figures": [],
                "tables": []
            }
        
        # 移除旧的该页数据
        summary["figures"] = [f for f in summary.get("figures", []) if f.get("page") != page_num]
        summary["tables"] = [t for t in summary.get("tables", []) if t.get("page") != page_num]
        
        # 添加新数据
        for fig in figures:
            summary["figures"].append({
                "id": fig["id"],
                "path": fig["path"],
                "title": fig.get("title", ""),
                "page": fig["page"],
                "filename": fig["filename"]
            })
        
        for tab in tables:
            summary["tables"].append({
                "id": tab["id"],
                "path": tab["path"],
                "title": tab.get("title", ""),
                "page": tab["page"],
                "filename": tab["filename"]
            })
        
        # 更新计数
        summary["figures_count"] = len(summary["figures"])
        summary["tables_count"] = len(summary["tables"])
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print(f"  ✓ 已更新 {summary_file}")


def parse_page_numbers(page_str: str) -> List[int]:
    """解析页码字符串"""
    pages = []
    
    # 支持格式: "5" 或 "3,5,7" 或 "1-5" 或 "1-5,7,9-11"
    parts = page_str.split(',')
    
    for part in parts:
        part = part.strip()
        if '-' in part:
            # 范围格式: 1-5
            start, end = part.split('-')
            pages.extend(range(int(start), int(end) + 1))
        else:
            # 单页格式: 5
            pages.append(int(part))
    
    return sorted(list(set(pages)))  # 去重并排序


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="修复PDF处理中的单个或多个页面"
    )
    parser.add_argument("output_dir", help="输出目录路径（包含pages/、intermediate/等）")
    parser.add_argument("pages", help="要修复的页码，支持格式: 5 | 3,5,7 | 1-5 | 1-5,7,9-11")
    parser.add_argument("--no-merge", action="store_true", help="不重新合并 output.md")
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""), help="API密钥")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "https://api.openai.com/v1"), help="API基础URL")
    parser.add_argument("--model", default=os.getenv("MODEL", "gpt-4o"), help="模型名称")
    
    args = parser.parse_args()
    
    # 验证输出目录
    if not os.path.exists(args.output_dir):
        print(f"❌ 错误: 输出目录不存在: {args.output_dir}")
        sys.exit(1)
    
    # 验证API配置
    if not args.api_key:
        print("❌ 错误: 未配置API密钥（API_KEY）")
        print("请设置环境变量 API_KEY 或使用 --api-key 参数")
        sys.exit(1)
    
    # 解析页码
    try:
        page_numbers = parse_page_numbers(args.pages)
        print(f"📄 将修复以下页面: {page_numbers}")
    except Exception as e:
        print(f"❌ 错误: 无法解析页码 '{args.pages}': {e}")
        sys.exit(1)
    
    # 创建修复器
    try:
        fixer = PageFixer(
            output_dir=args.output_dir,
            api_key=args.api_key,
            api_base=args.api_base,
            model=args.model
        )
    except Exception as e:
        print(f"❌ 错误: 初始化失败: {e}")
        sys.exit(1)
    
    # 修复每一页
    all_figures = []
    all_tables = []
    
    try:
        for page_num in page_numbers:
            try:
                fixer.fix_single_page(page_num)
                # 这里需要重新获取figures和tables来更新summary
                # 简化处理：用户可以通过完整重跑来更新summary
            except Exception as e:
                print(f"\n❌ 修复第 {page_num} 页时失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # 重新合并
        if not args.no_merge:
            fixer.merge_all_pages()
        else:
            print(f"\n⚠️  跳过了重新合并 output.md（使用 --no-merge 参数）")
            print(f"   修复的页面文件已保存到 intermediate/02_with_images/")
        
        print(f"\n🎉 修复完成！")
        
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
