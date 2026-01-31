#!/usr/bin/env python3
"""
Markdown翻译脚本

功能：将英文Markdown文件翻译成中文
- 翻译所有英文文字内容
- 公式保持不变
- 表格、图片、代码框、算法框只翻译必要的注释
- 人名不必翻译
- 保持Markdown格式和结构

使用方法:
    python translate_md.py output/output.md
    
输出：
    在同级目录生成 output_zh.md
"""

import os
import sys
import re
import argparse
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import time
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class ProtectedBlock:
    """受保护的内容块"""
    def __init__(self, placeholder: str, original: str, block_type: str):
        self.placeholder = placeholder
        self.original = original
        self.block_type = block_type


class MarkdownTranslator:
    """Markdown翻译器"""
    
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
    
    def call_api(self, prompt: str, max_tokens: int = 10000) -> str:
        """调用API"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3
        }
        
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
    
    def protect_blocks(self, text: str) -> Tuple[str, List[ProtectedBlock]]:
        """
        保护不需要翻译的块
        返回：(处理后的文本, 保护块列表)
        """
        protected_blocks = []
        protected_index = 0
        
        # 1. 保护代码块 ```...```
        def protect_code_block(match):
            nonlocal protected_index
            placeholder = f"<<<CODE_BLOCK_{protected_index:04d}>>>"
            protected_blocks.append(ProtectedBlock(placeholder, match.group(0), "code_block"))
            protected_index += 1
            return placeholder
        
        text = re.sub(r'```[\s\S]*?```', protect_code_block, text)
        
        # 2. 保护行内代码 `...`
        def protect_inline_code(match):
            nonlocal protected_index
            placeholder = f"<<<INLINE_CODE_{protected_index:04d}>>>"
            protected_blocks.append(ProtectedBlock(placeholder, match.group(0), "inline_code"))
            protected_index += 1
            return placeholder
        
        text = re.sub(r'`[^`]+`', protect_inline_code, text)
        
        # 3. 保护数学公式 $$...$$
        def protect_math_block(match):
            nonlocal protected_index
            placeholder = f"<<<MATH_BLOCK_{protected_index:04d}>>>"
            protected_blocks.append(ProtectedBlock(placeholder, match.group(0), "math_block"))
            protected_index += 1
            return placeholder
        
        text = re.sub(r'\$\$[\s\S]*?\$\$', protect_math_block, text)
        
        # 4. 保护行内数学公式 $...$
        def protect_inline_math(match):
            nonlocal protected_index
            placeholder = f"<<<INLINE_MATH_{protected_index:04d}>>>"
            protected_blocks.append(ProtectedBlock(placeholder, match.group(0), "inline_math"))
            protected_index += 1
            return placeholder
        
        text = re.sub(r'\$[^\$\n]+\$', protect_inline_math, text)
        
        # 5. 保护图片引用 ![...](...)
        def protect_image(match):
            nonlocal protected_index
            placeholder = f"<<<IMAGE_{protected_index:04d}>>>"
            protected_blocks.append(ProtectedBlock(placeholder, match.group(0), "image"))
            protected_index += 1
            return placeholder
        
        text = re.sub(r'!\[[^\]]*\]\([^)]+\)', protect_image, text)
        
        # 6. 保护HTML标签
        def protect_html(match):
            nonlocal protected_index
            placeholder = f"<<<HTML_{protected_index:04d}>>>"
            protected_blocks.append(ProtectedBlock(placeholder, match.group(0), "html"))
            protected_index += 1
            return placeholder
        
        text = re.sub(r'<[^>]+>', protect_html, text)
        
        return text, protected_blocks
    
    def restore_blocks(self, text: str, protected_blocks: List[ProtectedBlock]) -> str:
        """恢复保护的内容块"""
        # 按索引从大到小排序，避免替换时影响其他占位符
        sorted_blocks = sorted(protected_blocks, key=lambda x: x.placeholder, reverse=True)
        
        for block in sorted_blocks:
            if block.placeholder in text:
                text = text.replace(block.placeholder, block.original)
        
        return text
    
    def fix_broken_placeholders(self, text: str, all_blocks: List[ProtectedBlock]) -> str:
        """修复残缺的占位符（如 <<<INLINE_MATH_0053>）"""
        # 查找所有类似占位符但不完整的模式
        # 匹配 <<<TYPE_INDEX> 或 <<<TYPE_INDEX>> 等不完整形式
        broken_pattern = r'<<<([A-Z_]+)_(\d{1,4})>{0,2}'
        
        def fix_placeholder(match):
            block_type = match.group(1)
            index = int(match.group(2))
            
            # 查找对应的完整占位符
            expected_placeholder = f"<<<{block_type}_{index:04d}>>>"
            
            # 在all_blocks中查找
            for block in all_blocks:
                if block.placeholder == expected_placeholder:
                    return block.original
            
            # 如果没找到，返回原文（保留残缺占位符用于调试）
            return match.group(0)
        
        return re.sub(broken_pattern, fix_placeholder, text)
    
    def translate_text(self, text: str) -> str:
        """翻译文本"""
        if not text.strip():
            return text
        
        prompt = f"""请将以下Markdown内容翻译成中文。

**翻译要求**：
1. **翻译所有英文文字**：标题、段落、列表项等都要翻译
2. **保持格式**：保留所有Markdown标记（# ## ### ** * 等）
3. **保护内容不翻译**：
   - 代码块中的代码（只有注释需要翻译）
   - 数学公式
   - 人名（如 John Smith, Alice Johnson）保持英文
   - 专有名词和技术术语（如 Python, TensorFlow, CNN）可以保留英文或翻译
   - 文件路径和URL
   - 参考文献
4. **表格处理**：
   - 表头需要翻译
   - 表格内容如果是数据/代码不翻译
   - 表格内容如果是文字则翻译
5. **学术风格**：使用正式的中文学术语言
6. **保留占位符**：不要修改 <<<XXX_NNNN>>> 格式的占位符

**重要提示**：
- 你会看到一些占位符如 <<<CODE_BLOCK_0000>>>、<<<MATH_BLOCK_0001>>>、<<<IMAGE_0002>>> 等
- 这些是保护的内容，**绝对不要翻译或修改这些占位符**
- 直接保留这些占位符在原文位置，不要删除或更改

待翻译内容：
```markdown
{text}
```

请直接返回翻译后的中文Markdown内容。"""
        
        translated = self.call_api(prompt, max_tokens=10000)
        
        # 清理可能的代码块标记
        translated = re.sub(r'^```markdown\s*', '', translated)
        translated = re.sub(r'\s*```\s*$', '', translated)
        
        return translated
    
    def translate_large_document(self, text: str) -> str:
        """翻译大型文档（分段处理）"""
        # 保护所有内容（一次性保护整个文档）
        print("  🔒 正在保护不需要翻译的内容...")
        protected_text, all_protected_blocks = self.protect_blocks(text)
        print(f"     已保护 {len(all_protected_blocks)} 个内容块")
        
        # 如果文档较小，直接翻译
        if len(protected_text) < 8000:
            print("  🌐 文档较小，直接翻译...")
            translated = self.translate_text(protected_text)
            print("  🔓 正在恢复保护的内容...")
            final_text = self.restore_blocks(translated, all_protected_blocks)
            
            # 修复可能的残缺占位符
            broken_placeholders = re.findall(r'<<<[A-Z_]+_\d{1,4}>{1,2}(?!>)', final_text)
            if broken_placeholders:
                print(f"  ⚠️ 发现 {len(broken_placeholders)} 个残缺的占位符，正在修复...")
                final_text = self.fix_broken_placeholders(final_text, all_protected_blocks)
            
            return final_text
        
        # 大型文档分段翻译
        print(f"  📄 文档较大 ({len(text)} 字符)，将分段翻译...")
        
        # 按段落分割
        lines = protected_text.split('\n')
        chunks = []
        current_chunk_lines = []
        current_size = 0
        chunk_size_limit = 6000
        
        for line in lines:
            line_size = len(line)
            
            if current_size + line_size > chunk_size_limit and current_chunk_lines:
                if line.startswith('#') or line.strip() == '' or line.startswith('---'):
                    chunks.append('\n'.join(current_chunk_lines))
                    current_chunk_lines = [line]
                    current_size = line_size
                else:
                    chunks.append('\n'.join(current_chunk_lines))
                    current_chunk_lines = [line]
                    current_size = line_size
            else:
                current_chunk_lines.append(line)
                current_size += line_size
        
        if current_chunk_lines:
            chunks.append('\n'.join(current_chunk_lines))
        
        print(f"  📦 将分为 {len(chunks)} 段进行翻译")
        
        # 为每个chunk确定包含哪些保护块
        translated_chunks = []
        
        for i, chunk in enumerate(chunks):
            # 找出该chunk包含的保护块
            chunk_blocks = []
            for block in all_protected_blocks:
                if block.placeholder in chunk:
                    chunk_blocks.append(block)
            
            print(f"  🔄 正在翻译第 {i+1}/{len(chunks)} 段 (包含 {len(chunk_blocks)} 个保护块)...")
            
            # 翻译
            translated_chunk = self.translate_text(chunk)
            
            # 恢复该段的保护块
            if chunk_blocks:
                translated_chunk = self.restore_blocks(translated_chunk, chunk_blocks)
            
            translated_chunks.append(translated_chunk)
        
        # 合并所有翻译片段
        full_translated = '\n'.join(translated_chunks)
        
        # 检查并修复残缺的占位符（如 <<<INLINE_MATH_0053>）
        broken_placeholders = re.findall(r'<<<[A-Z_]+_\d{1,4}>{1,2}(?!>)', full_translated)
        if broken_placeholders:
            print(f"  ⚠️ 发现 {len(broken_placeholders)} 个残缺的占位符，正在修复...")
            full_translated = self.fix_broken_placeholders(full_translated, all_protected_blocks)
        
        # 最后检查是否有未恢复的占位符
        remaining_placeholders = re.findall(r'<<<[A-Z_]+_\d{4}>>>', full_translated)
        if remaining_placeholders:
            print(f"  ⚠️ 发现 {len(remaining_placeholders)} 个未恢复的占位符，尝试重新恢复...")
            full_translated = self.restore_blocks(full_translated, all_protected_blocks)
        
        return full_translated
    
    def process_markdown_file(self, input_path: str) -> str:
        """处理Markdown文件"""
        print(f"\n📖 正在读取文件: {input_path}")
        
        # 读取文件
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"✅ 已读取 ({len(content)} 字符)")
        
        # 翻译
        print("\n🌐 开始翻译...")
        translated_content = self.translate_large_document(content)
        
        # 生成输出路径
        input_path_obj = Path(input_path)
        output_path = input_path_obj.parent / f"{input_path_obj.stem}_zh{input_path_obj.suffix}"
        
        # 保存
        print(f"\n💾 保存到: {output_path}")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(translated_content)
        
        # 最终检查 - 检查完整的占位符
        remaining_placeholders = re.findall(r'<<<[A-Z_]+_\d{4}>>>', translated_content)
        
        # 检查残缺的占位符
        broken_placeholders = re.findall(r'<<<[A-Z_]+_\d{1,4}>{1,2}(?!>)', translated_content)
        
        if remaining_placeholders or broken_placeholders:
            if remaining_placeholders:
                print(f"\n⚠️ 警告: 输出中仍有 {len(remaining_placeholders)} 个未恢复的完整占位符")
            if broken_placeholders:
                print(f"\n⚠️ 警告: 输出中仍有 {len(broken_placeholders)} 个残缺的占位符:")
                for ph in broken_placeholders[:5]:
                    print(f"   - {ph}")
                if len(broken_placeholders) > 5:
                    print(f"   ... 还有 {len(broken_placeholders)-5} 个")
            print(f"\n💡 提示: 如果看到占位符，说明该部分内容未被正确恢复")
        else:
            print(f"✅ 所有保护内容已正确恢复")
        
        print(f"\n✅ 翻译完成！")
        print(f"   输入: {input_path}")
        print(f"   输出: {output_path}")
        print(f"   字符数: {len(translated_content)}")
        
        return str(output_path)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="将英文Markdown文件翻译成中文"
    )
    parser.add_argument("input_file", help="输入的英文Markdown文件路径")
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""), help="API密钥")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "https://api.openai.com/v1"), help="API基础URL")
    parser.add_argument("--model", default=os.getenv("MODEL", "gpt-4o"), help="模型名称")
    
    args = parser.parse_args()
    
    # 验证输入文件
    if not os.path.exists(args.input_file):
        print(f"❌ 错误: 文件不存在: {args.input_file}")
        sys.exit(1)
    
    if not args.input_file.endswith('.md'):
        print(f"⚠️  警告: 输入文件不是 .md 文件: {args.input_file}")
    
    # 验证API配置
    if not args.api_key:
        print("❌ 错误: 未配置API密钥（API_KEY）")
        print("请设置环境变量 API_KEY 或使用 --api-key 参数")
        sys.exit(1)
    
    # 创建翻译器
    translator = MarkdownTranslator(
        api_key=args.api_key,
        api_base=args.api_base,
        model=args.model
    )
    
    # 处理文件
    try:
        output_path = translator.process_markdown_file(args.input_file)
        print(f"\n🎉 成功生成中文Markdown文件！")
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
