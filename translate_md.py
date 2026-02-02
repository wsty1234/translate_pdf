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
        self.translation_cache = {}
    
    def call_api(self, prompt: str, max_tokens: int = 10000, temperature: float = 0.3) -> str:
        """调用API"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
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
    
    def protect_inline_math_formulas(self, text: str, protected_blocks: List[ProtectedBlock]) -> str:
        """专门处理行内数学公式 $...$，处理嵌套大括号的情况"""
        protected_index = len([b for b in protected_blocks if b.block_type == "inline_math"])
        
        # 使用状态机来处理嵌套的大括号
        result = []
        i = 0
        n = len(text)
        
        while i < n:
            if text[i] == '$':
                # 检查是否是 $$
                if i + 1 < n and text[i + 1] == '$':
                    # 这是 $$...$$ 块，跳过，由其他函数处理
                    result.append(text[i])
                    i += 1
                    continue
                
                # 找到匹配的 $
                start = i
                i += 1
                brace_depth = 0
                
                while i < n:
                    if text[i] == '\\' and i + 1 < n:
                        # 转义字符，跳过下一个字符
                        i += 2
                        continue
                    elif text[i] == '{':
                        brace_depth += 1
                    elif text[i] == '}':
                        brace_depth -= 1
                    elif text[i] == '$' and brace_depth == 0:
                        # 找到匹配的 $
                        i += 1
                        formula = text[start:i]
                        placeholder = f"<<<INLINE_MATH_{protected_index:04d}>>>"
                        protected_blocks.append(ProtectedBlock(placeholder, formula, "inline_math"))
                        result.append(placeholder)
                        protected_index += 1
                        break
                    
                    i += 1
                else:
                    # 没有找到匹配的 $，保留原样
                    result.append(text[start:i])
            else:
                result.append(text[i])
                i += 1
        
        return ''.join(result)
    
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
        
        # 4. 保护行内数学公式 $...$（使用专门的函数处理嵌套大括号）
        text = self.protect_inline_math_formulas(text, protected_blocks)
        
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
    
    def validate_translation_completeness(self, original: str, translated: str) -> Dict[str, any]:
        """验证翻译完整性
        
        Args:
            original: 原始文本
            translated: 翻译后的文本
        
        Returns:
            包含验证结果的字典
        """
        result = {
            "is_valid": True,
            "issues": []
        }
        
        # 1. 检查占位符数量
        original_placeholders = re.findall(r'<<<[A-Z_]+_\d{4}>>>', original)
        translated_placeholders = re.findall(r'<<<[A-Z_]+_\d{4}>>>', translated)
        
        if len(original_placeholders) != len(translated_placeholders):
            result["is_valid"] = False
            result["issues"].append(f"占位符数量不匹配: 原文{len(original_placeholders)}个, 译文{len(translated_placeholders)}个")
        
        # 2. 检查段落数量
        original_paragraphs = [p for p in original.split('\n\n') if p.strip()]
        translated_paragraphs = [p for p in translated.split('\n\n') if p.strip()]
        
        if len(original_paragraphs) != len(translated_paragraphs):
            diff = abs(len(original_paragraphs) - len(translated_paragraphs))
            result["issues"].append(f"段落数量差异: 原文{len(original_paragraphs)}段, 译文{len(translated_paragraphs)}段 (差异{diff}段)")
            if diff > len(original_paragraphs) * 0.2:  # 差异超过20%
                result["is_valid"] = False
        
        # 3. 检查行数
        original_lines = [l for l in original.split('\n') if l.strip()]
        translated_lines = [l for l in translated.split('\n') if l.strip()]
        
        if len(original_lines) != len(translated_lines):
            diff = abs(len(original_lines) - len(translated_lines))
            result["issues"].append(f"行数差异: 原文{len(original_lines)}行, 译文{len(translated_lines)}行 (差异{diff}行)")
            if diff > len(original_lines) * 0.15:  # 差异超过15%
                result["is_valid"] = False
        
        # 4. 检查内容长度比例（中文通常比英文短）
        # 假设中英文比例在 0.5 到 1.2 之间是合理的
        length_ratio = len(translated) / len(original) if len(original) > 0 else 0
        if length_ratio < 0.3 or length_ratio > 1.5:
            result["is_valid"] = False
            result["issues"].append(f"内容长度异常: 中英文比例 {length_ratio:.2f} (预期 0.3-1.5)")
        
        return result
    
    def post_optimize_translation(self, text: str) -> str:
        """翻译后的整体优化
        
        Args:
            text: 翻译后的文本
        
        Returns:
            优化后的文本
        """
        if not text.strip():
            return text
        
        prompt = f"""请对以下中文翻译进行整体优化，提升语言流畅度和连贯性。

**优化要求**：
1. **绝对不能删除任何内容**：这是最重要的原则！只能优化语言表达，不能删除任何段落、句子或词语
2. **保持结构完整**：所有段落、标题、列表项等结构必须保持不变
3. **只润色语言**：优化句式、用词、连接词等，使表达更流畅自然
4. **保持学术风格**：使用正式的中文学术语言
5. **保持格式**：所有Markdown格式标记必须保持不变
6. **保留占位符**：不要修改 <<<XXX_NNNN>>> 格式的占位符

**重要提示**：
- 你的任务只是润色语言，让翻译读起来更流畅
- 不得改变原文的结构和内容数量
- 不得删除任何段落或句子
- 如果某个段落已经有问题，只能优化其表达，不能删除

待优化的中文文本：
```markdown
{text}
```

请直接返回优化后的中文Markdown内容。"""
        
        optimized = self.call_api(prompt, max_tokens=15000, temperature=0.2)
        
        # 清理可能的代码块标记
        optimized = re.sub(r'^```markdown\s*', '', optimized)
        optimized = re.sub(r'\s*```\s*$', '', optimized)
        
        return optimized
    
    def translate_text(self, text: str, context: str = "") -> str:
        """翻译文本
        
        Args:
            text: 要翻译的文本
            context: 上下文信息（前一段的最后几句），用于保持连贯性
        """
        if not text.strip():
            return text
        
        context_part = f"\n\n**上下文参考**（前段末尾，用于保持连贯性，只需翻译本段）：\n```markdown\n{context}\n```\n" if context.strip() else ""
        
        prompt = f"""请将以下Markdown内容翻译成中文。

**翻译要求**：
1. **必须翻译所有英文正文内容**：这是最重要的要求！每个英文句子、每个段落都必须翻译成中文
2. **逐句逐段完整翻译**：不得遗漏任何内容，不得省略任何句子
3. **保持格式**：保留所有Markdown标记（# ## ### ** * 等）
4. **保护内容不翻译**：
   - 代码块中的代码（只有注释需要翻译）
   - 数学公式
   - 人名（如 John Smith, Alice Johnson）保持英文
   - 专有名词和技术术语（如 Python, TensorFlow, CNN）可以保留英文或翻译
   - 文件路径和URL
5. **表格处理**：
   - 表头需要翻译
   - 表格内容如果是数据/代码不翻译
   - 表格内容如果是文字则翻译
6. **学术风格**：使用正式的中文学术语言
7. **保留占位符**：不要修改 <<<XXX_NNNN>>> 格式的占位符

**重要提示**：
- 你会看到一些占位符如 <<<CODE_BLOCK_0000>>>、<<<MATH_BLOCK_0001>>>、<<<INLINE_MATH_0002>>> 等
- 这些是保护的内容，**绝对不要翻译或修改这些占位符**
- 直接保留这些占位符在原文位置，不要删除或更改
- 特别是 <<<INLINE_MATH_XXXX>>> 代表行内数学公式，必须完整保留
- **严禁跳过任何段落或内容不翻译**，必须逐字逐句翻译全部内容

{context_part}
**待翻译内容**（必须全部翻译）：
```markdown
{text}
```

请直接返回翻译后的中文Markdown内容，确保翻译完整，没有遗漏。"""
        
        translated = self.call_api(prompt, max_tokens=10000, temperature=0.3)
        
        # 清理可能的代码块标记
        translated = re.sub(r'^```markdown\s*', '', translated)
        translated = re.sub(r'\s*```\s*$', '', translated)
        
        return translated
    
    def get_context_from_previous_chunk(self, previous_chunk: str, num_lines: int = 3) -> str:
        """从前一段提取末尾几行作为上下文
        
        Args:
            previous_chunk: 前一段的原始内容
            num_lines: 提取的行数
        
        Returns:
            上下文字符串
        """
        if not previous_chunk:
            return ""
        
        lines = [line for line in previous_chunk.split('\n') if line.strip()]
        if not lines:
            return ""
        
        # 提取最后几行
        context_lines = lines[-num_lines:]
        return '\n'.join(context_lines)
    
    def translate_large_document(self, text: str) -> str:
        """翻译大型文档（分段处理）"""
        # 保护所有内容（一次性保护整个文档）
        print("  🔒 正在保护不需要翻译的内容...")
        protected_text, all_protected_blocks = self.protect_blocks(text)
        inline_math_count = len([b for b in all_protected_blocks if b.block_type == "inline_math"])
        math_block_count = len([b for b in all_protected_blocks if b.block_type == "math_block"])
        print(f"     已保护 {len(all_protected_blocks)} 个内容块")
        print(f"        - 行内公式: {inline_math_count}")
        print(f"        - 公式块: {math_block_count}")
        print(f"        - 代码块: {len([b for b in all_protected_blocks if b.block_type == 'code_block'])}")
        print(f"        - 图片: {len([b for b in all_protected_blocks if b.block_type == 'image'])}")
        
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
            
            # 获取前一段的上下文
            context = ""
            if i > 0:
                context = self.get_context_from_previous_chunk(chunks[i-1], num_lines=3)
            
            print(f"  🔄 正在翻译第 {i+1}/{len(chunks)} 段 (包含 {len(chunk_blocks)} 个保护块)...")
            if context:
                print(f"     ✓ 已添加前段上下文 ({len(context)} 字符)")
            
            # 翻译，传入上下文
            translated_chunk = self.translate_text(chunk, context=context)
            
            # 恢复该段的保护块
            if chunk_blocks:
                translated_chunk = self.restore_blocks(translated_chunk, chunk_blocks)
            
            translated_chunks.append(translated_chunk)
        
        # 合并所有翻译片段
        full_translated = '\n'.join(translated_chunks)
        
        # 检查并修复残缺的占位符
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
        
        # 验证翻译完整性
        print("\n🔍 验证翻译完整性...")
        validation_result = self.validate_translation_completeness(content, translated_content)
        
        if validation_result["issues"]:
            for issue in validation_result["issues"]:
                print(f"  ⚠️  {issue}")
            if validation_result["is_valid"]:
                print(f"  ℹ️  翻译基本完整，但存在一些差异")
            else:
                print(f"  ❌ 翻译可能存在问题，建议人工检查")
        else:
            print(f"  ✅ 翻译完整性检查通过")
        
        # 整体优化翻译（提升语言连贯性）
        print("\n✨ 正在进行整体优化...")
        print(f"   原字符数: {len(translated_content)}")
        optimized_content = self.post_optimize_translation(translated_content)
        print(f"   优化后字符数: {len(optimized_content)}")
        
        # 生成输出路径
        input_path_obj = Path(input_path)
        output_path = input_path_obj.parent / f"{input_path_obj.stem}_zh{input_path_obj.suffix}"
        
        # 保存
        print(f"\n💾 保存到: {output_path}")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(optimized_content)
        
        # 最终检查
        remaining_placeholders = re.findall(r'<<<[A-Z_]+_\d{4}>>>', optimized_content)
        broken_placeholders = re.findall(r'<<<[A-Z_]+_\d{1,4}>{1,2}(?!>)', optimized_content)
        
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
        print(f"   最终字符数: {len(optimized_content)}")
        
        return str(output_path)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="将英文Markdown文件翻译成中文"
    )
    parser.add_argument("input_file", help="输入的英文Markdown文件路径")
    parser.add_argument("--api-key", default=os.getenv("TRANSLATE_API_KEY", ""), help="API密钥")
    parser.add_argument("--api-base", default=os.getenv("TRANSLATE_API_BASE", "https://api.openai.com/v1"), help="API基础URL")
    parser.add_argument("--model", default=os.getenv("TRANSLATE_MODEL", "gpt-4o"), help="模型名称")
    
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
