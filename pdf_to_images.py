#!/usr/bin/env python3
"""
PDF分解脚本

功能：将PDF转换为页面图片
- 输入：PDF文件路径
- 输出：output/pages/ 目录下的 page_001.png, page_002.png...

使用方法:
    python pdf_to_images.py paper.pdf -o ./output
    
输出：
    - output/pages/page_001.png
    - output/pages/page_002.png
    - ...
"""

import os
import sys
import argparse
from pathlib import Path

from pdf2image import convert_from_path


def pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 200) -> int:
    """
    将PDF转换为图片
    
    Args:
        pdf_path: PDF文件路径
        output_dir: 输出目录（图片将保存到 output_dir/pages/）
        dpi: 转换DPI
    
    Returns:
        转换的页数
    """
    print(f"📄 正在转换PDF: {pdf_path}")
    
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")
    
    # 创建 pages 目录
    pages_dir = os.path.join(output_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    
    # 转换PDF
    print(f"  使用DPI={dpi}转换中...")
    images = convert_from_path(pdf_path, dpi=dpi)
    
    # 保存每页
    for i, image in enumerate(images, 1):
        image_path = os.path.join(pages_dir, f"page_{i:03d}.png")
        image.save(image_path, "PNG")
        print(f"  ✓ 已保存第 {i}/{len(images)} 页: page_{i:03d}.png")
    
    print(f"\n✅ 转换完成！共 {len(images)} 页")
    print(f"📁 图片保存位置: {pages_dir}")
    
    return len(images)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="将PDF转换为页面图片"
    )
    parser.add_argument("pdf_path", help="输入PDF文件路径")
    parser.add_argument("-o", "--output", default="./output", 
                       help="输出目录（默认: ./output，图片将保存到 output/pages/）")
    parser.add_argument("--dpi", type=int, default=200, 
                       help="PDF转图片的DPI（默认: 200）")
    
    args = parser.parse_args()
    
    try:
        total_pages = pdf_to_images(args.pdf_path, args.output, dpi=args.dpi)
        print(f"\n🎉 成功转换 {total_pages} 页！")
        print(f"\n下一步请运行:")
        print(f"  python academic_reader.py {os.path.join(args.output, 'pages')} -o {args.output}")
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
