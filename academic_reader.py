#!/usr/bin/env python3
"""
学术PDF转Markdown工作流（英文版 - 仅提取不翻译）

工作流程：
1. 提取所有页面插图 → 保存图片
2. 提取所有页面英文文本（保留阅读顺序，跳过图片/表格中的文字）
3. 每页插入对应的图片/表格引用
4. 合并所有带图片引用的页面成完整英文文档

特点：
- 单API配置
- 针对两栏PDF优化阅读顺序
- 图片/表格中的文字不提取
- 仅输出完整英文Markdown（不翻译）
- 每页图片立即插入，文件名对应page_num
"""

import os
import sys
import json
import base64
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import time
from datetime import datetime

from pdf2image import convert_from_path
from PIL import Image
import requests

# 加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class PageContent:
    """页面内容"""
    page_number: int
    image_path: str
    raw_text: str = ""  # 提取的原始英文文本
    processed_markdown: str = ""  # 插入图片后的markdown
    figures: List[Dict] = field(default_factory=list)
    tables: List[Dict] = field(default_factory=list)


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
    
    def call_with_image(self, image_path: str, prompt: str, max_tokens: int = 4096) -> str:
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
            "temperature": 1.0
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


class AcademicPDFReader:
    """学术PDF阅读器（英文提取版）"""
    
    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        max_retries: int = 3,
        timeout: int = 120,
        save_intermediate: bool = True
    ):
        self.api_client = APIClient(api_key, api_base, model, max_retries, timeout)
        self.save_intermediate = save_intermediate
        self.intermediate_dir = None
    
    def setup_intermediate_dirs(self, output_dir: str):
        """设置中间结果目录"""
        if not self.save_intermediate:
            return
        
        self.intermediate_dir = os.path.join(output_dir, "intermediate")
        dirs = [
            os.path.join(self.intermediate_dir, "01_raw_extracted"),     # 原始提取的英文
            os.path.join(self.intermediate_dir, "02_with_images"),       # 插入图片后的每页
        ]
        
        for d in dirs:
            os.makedirs(d, exist_ok=True)
        
        print(f"📁 中间结果将保存在: {self.intermediate_dir}")
    
    def save_intermediate_file(self, step: str, filename: str, content: str):
        """保存中间结果文件"""
        if not self.save_intermediate or not self.intermediate_dir:
            return
        
        step_dir = os.path.join(self.intermediate_dir, step)
        os.makedirs(step_dir, exist_ok=True)
        filepath = os.path.join(step_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        return filepath
    
    def pdf_to_images(self, pdf_path: str, output_dir: str, dpi: int = 200) -> List[str]:
        """将PDF转换为图片"""
        print(f"📄 正在转换PDF: {pdf_path}")
        
        os.makedirs(output_dir, exist_ok=True)
        images = convert_from_path(pdf_path, dpi=dpi)
        
        image_paths = []
        for i, image in enumerate(images, 1):
            image_path = os.path.join(output_dir, f"page_{i:03d}.png")
            image.save(image_path, "PNG")
            image_paths.append(image_path)
            print(f"  ✓ 已保存第 {i}/{len(images)} 页")
        
        print(f"✅ PDF转换完成，共 {len(images)} 页\n")
        return image_paths
    
    def extract_figures_and_tables(
        self, 
        image_path: str, 
        page_num: int,
        output_dir: str
    ) -> Tuple[List[Dict], List[Dict]]:
        """从页面中提取插图和表格"""
        print(f"  🔍 正在识别第 {page_num} 页的插图和表格...")
        
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
            response = self.api_client.call_with_image(image_path, prompt, max_tokens=4096)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = {"figures": [], "tables": []}
        except Exception as e:
            print(f"    ⚠️ 识别失败: {e}")
            data = {"figures": [], "tables": []}
        
        # 创建输出目录
        figures_dir = os.path.join(output_dir, "figures")
        tables_dir = os.path.join(output_dir, "tables")
        os.makedirs(figures_dir, exist_ok=True)
        os.makedirs(tables_dir, exist_ok=True)
        
        figures = []
        tables = []
        
        # 处理插图 - 使用page_num确保文件名对应
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
                
                # 确保文件名包含page_num，便于对应
                safe_id = re.sub(r'[^\w]', '_', fig_id.lower())
                fig_filename = f"page{page_num:03d}_{safe_id}.png"
                
                fig_relative_path = f"figures/{fig_filename}"
                fig_absolute_path = os.path.join(figures_dir, fig_filename)
                cropped.save(fig_absolute_path, "PNG")
                
                figures.append({
                    "id": fig_id,
                    "title": fig.get("title", ""),
                    "path": fig_relative_path,
                    "absolute_path": fig_absolute_path,
                    "filename": fig_filename,
                    "page": page_num
                })
                print(f"    ✓ 已提取插图: {fig_id} → {fig_filename}")
            except Exception as e:
                print(f"    ⚠️ 提取插图失败: {e}")
        
        # 处理表格 - 使用page_num确保文件名对应
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
                
                # 确保文件名包含page_num，便于对应
                safe_id = re.sub(r'[^\w]', '_', tab_id.lower())
                tab_filename = f"page{page_num:03d}_{safe_id}.png"
                
                tab_relative_path = f"tables/{tab_filename}"
                tab_absolute_path = os.path.join(tables_dir, tab_filename)
                cropped.save(tab_absolute_path, "PNG")
                
                tables.append({
                    "id": tab_id,
                    "title": tab.get("title", ""),
                    "path": tab_relative_path,
                    "absolute_path": tab_absolute_path,
                    "filename": tab_filename,
                    "page": page_num
                })
                print(f"    ✓ 已提取表格: {tab_id} → {tab_filename}")
            except Exception as e:
                print(f"    ⚠️ 提取表格失败: {e}")
        
        return figures, tables
    
    def extract_text_from_page(
        self,
        image_path: str,
        page_num: int,
        total_pages: int
    ) -> str:
        """从页面图片中提取英文文本（跳过图片/表格中的文字）"""
        print(f"  📝 正在提取第 {page_num} 页的英文文本（跳过图表文字）...")
        
        prompt = f"""请仔细分析这张学术论文页面的图片，提取页面上的所有英文文本内容。

**重要：提取范围要求**
1. **只提取正文文字**，不包括：
   - ❌ 图片（Figure）中的文字（如图表标签、坐标轴文字等）
   - ❌ 表格（Table）中的文字（如单元格内容、表头文字等）
   - ❌ 图片和表格的标题（Figure X:, Table X:）——这些会单独处理

2. **只提取以下文字内容**：
   - ✓ 标题（Title, Section headers等）
   - ✓ 正文段落
   - ✓ 摘要（Abstract）
   - ✓ 引言（Introduction）
   - ✓ 方法描述
   - ✓ 结果讨论
   - ✓ 结论
   - ✓ 参考文献引用标记
   - ✓ 页眉页脚信息（作者、会议、页码等）

3. **阅读顺序要求**（重要）：
   - 如果页面是**双栏布局**（左右两栏）：
     * 先完整提取**左栏**所有内容（从上到下）
     * 然后提取**右栏**所有内容（从上到下）
     * 不要混排左右栏的内容
   - 如果页面是**单栏布局**：
     * 按正常从上到下顺序提取

4. **格式要求**：
   - 使用Markdown格式
   - 标题用 # ## ### 标记
   - 段落之间保留空行
   - 数学公式保留 LaTeX 格式 $...$ 或 $$...$$

5. **标注插图和表格位置**：
   - 在插图出现的位置标记：[FIGURE: Figure 1]
   - 在表格出现的位置标记：[TABLE: Table 1]
   - 但**不要提取图表内部的文字**

请直接返回提取的文本，使用Markdown格式。不要添加解释。"""
        
        raw_text = self.api_client.call_with_image(image_path, prompt, max_tokens=4096)
        
        # 保存原始提取结果
        self.save_intermediate_file(
            "01_raw_extracted", 
            f"page_{page_num:03d}.md", 
            raw_text
        )
        
        return raw_text
    
    def insert_image_references_for_page(
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
            # 多种可能的标记格式
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
                # 如果标记没找到，在提到figure的文本位置插入
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
                # 如果没找到标记，在文本中插入
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
    
    def process_single_page(
        self,
        image_path: str,
        page_num: int,
        total_pages: int,
        output_dir: str
    ) -> PageContent:
        """处理单页：提取 + 插入图片"""
        print(f"\n📖 正在处理第 {page_num}/{total_pages} 页...")
        
        # 步骤1：提取插图和表格
        figures, tables = self.extract_figures_and_tables(
            image_path, page_num, output_dir
        )
        
        # 步骤2：提取英文文本
        raw_text = self.extract_text_from_page(image_path, page_num, total_pages)
        
        # 步骤3：为该页插入图片引用
        processed_markdown = self.insert_image_references_for_page(
            raw_text, figures, tables, page_num
        )
        
        # 保存带图片的页面
        self.save_intermediate_file(
            "02_with_images",
            f"page_{page_num:03d}.md",
            processed_markdown
        )
        
        result = PageContent(
            page_number=page_num,
            image_path=image_path,
            raw_text=raw_text,
            processed_markdown=processed_markdown,
            figures=figures,
            tables=tables
        )
        
        return result
    
    def post_process_markdown(self, markdown: str) -> str:
        """Markdown后处理"""
        # 清理多余空行
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)
        # 规范图片引用格式
        markdown = re.sub(r'!\[([^\]]*)\]\s*\(\s*([^)]+)\s*\)', r'![\1](\2)', markdown)
        # 清理首尾空行
        markdown = markdown.strip()
        return markdown
    
    def process_pdf(self, pdf_path: str, output_dir: str, dpi: int = 200) -> str:
        """处理完整PDF的主流程"""
        print("=" * 70)
        print("📚 学术PDF转Markdown工作流（英文提取版）")
        print("=" * 70)
        print("\n工作流：")
        print("  1. 提取所有页面插图和表格")
        print("  2. 提取所有页面英文文本（跳过图表文字）")
        print("  3. 每页立即插入对应的图片/表格引用")
        print("  4. 合并所有带图片的页面成完整英文文档\n")
        
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")
        
        # 设置中间结果目录
        self.setup_intermediate_dirs(output_dir)
        
        # 步骤1：PDF转图片
        images_dir = os.path.join(output_dir, "pages")
        image_paths = self.pdf_to_images(pdf_path, images_dir, dpi=dpi)
        total_pages = len(image_paths)
        
        # 步骤2-3：逐页提取并立即插入图片
        print("\n" + "=" * 70)
        print("📖 阶段：提取所有页面并插入图片")
        print("=" * 70)
        
        all_pages_content = []
        all_figures = []
        all_tables = []
        
        for i, image_path in enumerate(image_paths, 1):
            page_content = self.process_single_page(
                image_path, i, total_pages, output_dir
            )
            all_pages_content.append(page_content)
            all_figures.extend(page_content.figures)
            all_tables.extend(page_content.tables)
        
        # 步骤4：合并所有带图片的页面
        print("\n" + "=" * 70)
        print("📝 阶段：合并完整英文文档")
        print("=" * 70)
        
        # 合并所有已处理好的页面（已经包含图片引用）
        full_english_markdown = "\n\n---\n\n".join([p.processed_markdown for p in all_pages_content])
        
        # 后处理
        full_english_markdown = self.post_process_markdown(full_english_markdown)
        
        # 保存最终结果
        output_file = os.path.join(output_dir, "output.md")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(full_english_markdown)
        
        # 保存摘要
        summary = {
            "total_pages": total_pages,
            "figures_count": len(all_figures),
            "tables_count": len(all_tables),
            "total_chars": len(full_english_markdown),
            "figures": [{"id": f["id"], "path": f["path"], "title": f.get("title", ""), "page": f["page"], "filename": f["filename"]} for f in all_figures],
            "tables": [{"id": t["id"], "path": t["path"], "title": t.get("title", ""), "page": t["page"], "filename": t["filename"]} for t in all_tables]
        }
        
        summary_file = os.path.join(output_dir, "summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print("\n" + "=" * 70)
        print("✅ 处理完成！")
        print(f"📄 最终英文Markdown文件: {output_file}")
        if self.save_intermediate:
            print(f"📁 中间结果目录: {self.intermediate_dir}")
        print(f"📊 共 {total_pages} 页，{len(all_figures)} 个插图，{len(all_tables)} 个表格")
        print(f"📋 处理摘要: {summary_file}")
        print(f"📝 总字符数: {len(full_english_markdown)}")
        print("=" * 70)
        
        if self.save_intermediate:
            print("\n📂 中间结果文件：")
            print(f"  - intermediate/01_raw_extracted/    原始提取的英文（未插入图片）")
            print(f"  - intermediate/02_with_images/      已插入图片的每页英文")
        
        return output_file


def main():
    """主函数"""
    import argparse
    
    default_output = os.getenv("OUTPUT_DIR", "./output")
    default_dpi = int(os.getenv("DPI", "200"))
    
    parser = argparse.ArgumentParser(
        description="学术PDF转Markdown工作流（英文提取版）"
    )
    parser.add_argument("pdf_path", help="输入PDF文件路径")
    parser.add_argument("-o", "--output", default=default_output, help="输出目录")
    parser.add_argument("--dpi", type=int, default=default_dpi, help="PDF转图片的DPI")
    parser.add_argument("--no-intermediate", action="store_true", help="不保存中间结果")
    
    # API配置
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""), help="API密钥")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "https://api.openai.com/v1"), help="API基础URL")
    parser.add_argument("--model", default=os.getenv("MODEL", "gpt-4o"), help="模型名称")
    
    args = parser.parse_args()
    
    # 验证API配置
    if not args.api_key:
        print("❌ 错误: 未配置API密钥（API_KEY）")
        sys.exit(1)
    
    # 创建处理器
    reader = AcademicPDFReader(
        api_key=args.api_key,
        api_base=args.api_base,
        model=args.model,
        save_intermediate=not args.no_intermediate
    )
    
    # 处理PDF
    try:
        output_file = reader.process_pdf(args.pdf_path, args.output, dpi=args.dpi)
        print(f"\n🎉 成功生成英文Markdown文件: {output_file}")
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
