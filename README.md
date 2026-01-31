# 学术PDF转Markdown工作流

这是一个自动化的学术PDF阅读和翻译工具，可以将英文学术论文转换为结构化的中文Markdown文档。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt
brew install poppler  # macOS（或其他系统见下文）

# 2. 创建.env配置文件
cp .env.example .env
# 编辑 .env 文件，填入你的 API 密钥

# 3. 运行
python academic_reader.py paper.pdf -o ./output
```

## 功能特点

1. **PDF转图片**：将PDF每页转换为高质量PNG图片
2. **多API支持**：支持为不同步骤配置不同API（图片提取/翻译/优化）
3. **逐字翻译**：强化翻译质量，确保内容完整不遗漏
4. **插图提取**：自动识别、截取并保存文中的图片和表格
5. **智能引用**：自动在markdown中插入图片引用，确保正确显示
6. **Markdown排版**：生成格式良好的Markdown文档，保留原文结构
7. **连贯性处理**：保持页面间的逻辑连贯和上下文衔接
8. **最终优化**：对整篇文档进行翻译质量检查和格式统一

## 安装依赖

### 1. 安装Python依赖

```bash
pip install -r requirements.txt
```

### 2. 安装系统依赖（poppler）

**macOS:**
```bash
brew install poppler
```

**Ubuntu/Debian:**
```bash
apt-get install poppler-utils
```

**Windows:**
下载 [poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases/) 并添加到PATH

## 配置方法

### 方案1：单一API配置（简单场景）

所有步骤使用同一个API：

```env
# .env 文件
API_KEY=your_api_key_here
API_BASE=https://api.openai.com/v1
MODEL=gpt-4o
OUTPUT_DIR=./output
```

### 方案2：多API配置（推荐）

为不同步骤配置不同API，优化成本和效果：

```env
# .env 文件

# 图片提取API（需要视觉能力强的模型）
EXTRACTION_API_KEY=sk-xxx
EXTRACTION_API_BASE=https://api.openai.com/v1
EXTRACTION_MODEL=gpt-4o

# 翻译API（可以使用成本更低的模型）
TRANSLATION_API_KEY=sk-yyy
TRANSLATION_API_BASE=https://api.openai.com/v1
TRANSLATION_MODEL=gpt-4o

# 最终优化API（可选，默认使用翻译API）
OPTIMIZATION_API_KEY=sk-zzz

OUTPUT_DIR=./output
DPI=200
```

### 环境变量

```bash
export API_KEY=your_api_key
export MODEL=gpt-4o
python academic_reader.py paper.pdf
```

### 命令行参数

**单一API模式：**
```bash
python academic_reader.py paper.pdf \
  --api-key your_key \
  --model gpt-4o \
  -o ./output
```

**多API模式：**
```bash
python academic_reader.py paper.pdf \
  --extraction-api-key vision_key \
  --extraction-model gpt-4o \
  --translation-api-key translation_key \
  --translation-model gpt-4 \
  -o ./output
```

**优先级**：命令行参数 > 环境变量 > .env文件 > 默认值

## 使用方法

### 支持的API提供商

- **OpenAI**: https://api.openai.com/v1 (gpt-4o, gpt-4-turbo)
- **Groq**: https://api.groq.com/openai/v1 (llama-3.2-90b-vision-preview)
- **Moonshot**: https://api.moonshot.cn/v1
- **Ollama本地部署**: http://localhost:11434/v1
- **其他OpenAI兼容API**

### Python API方式

```python
from academic_reader import AcademicPDFReader, APIConfig

# 配置多个API
extraction_api = APIConfig(
    api_key="vision-api-key",
    api_base="https://api.openai.com/v1",
    model="gpt-4o"
)

translation_api = APIConfig(
    api_key="translation-api-key",
    api_base="https://api.groq.com/openai/v1",
    model="llama-3.2-90b-vision-preview"
)

# 创建阅读器
reader = AcademicPDFReader(
    extraction_api=extraction_api,
    translation_api=translation_api
)

# 处理PDF
output_file = reader.process_pdf(
    pdf_path="paper.pdf",
    output_dir="./output",
    dpi=200
)

print(f"输出文件: {output_file}")
```

## 输出结构

```
output/
├── pages/                    # PDF页面截图
│   ├── page_001.png
│   ├── page_002.png
│   └── ...
├── figures/                  # 提取的插图
│   ├── page1_figure_1.png
│   ├── page2_figure_1.png
│   └── ...
├── tables/                   # 提取的表格
│   ├── page1_table_1.png
│   └── ...
├── output.md                 # 最终Markdown文件
└── summary.json              # 处理摘要
```

## 工作流程

1. **PDF转图片** → 将每页转换为PNG
2. **提取视觉元素** → 使用extraction_api识别并截取Figure和Table
3. **翻译与格式化** → 使用translation_api将英文翻译为中文，生成Markdown
4. **图片引用验证** → 自动检查并修复markdown中的图片引用
5. **最终优化** → 使用optimization_api检查翻译质量、统一格式

## 注意事项

1. **API费用**：使用GPT-4V等多模态模型会产生费用，请确保账户有足够的额度
2. **处理时间**：根据PDF页数和API响应速度，处理可能需要几分钟到几十分钟
3. **隐私**：PDF内容会被发送到第三方API，请勿上传包含敏感信息的文档
4. **网络**：需要稳定的网络连接访问API
5. **质量**：AI翻译可能存在不准确之处，建议人工校对重要文档
6. **多API优势**：
   - 图片提取可以用便宜的模型（如Gemini Flash）
   - 翻译可以用强的模型（如GPT-4o）
   - 降低整体成本

## 示例

### 单一API示例

```bash
python academic_reader.py attention.pdf \
  --api-key sk-xxx \
  --model gpt-4o \
  -o ./attention_output
```

### 多API示例（成本优化）

```bash
# 使用Gemini Flash提取图片（便宜且有视觉能力）
# 使用GPT-4o进行翻译（质量好）
python academic_reader.py paper.pdf \
  --extraction-api-key gemini_key \
  --extraction-api-base https://generativelanguage.googleapis.com/v1beta/openai \
  --extraction-model gemini-1.5-flash \
  --translation-api-key openai_key \
  --translation-model gpt-4o \
  -o ./output
```

## 故障排除

### 问题：pdf2image转换失败
**解决**：确保已安装poppler系统依赖

### 问题：API调用超时
**解决**：检查网络连接，或尝试更换API提供商。在.env中增加`TIMEOUT=180`

### 问题：翻译有遗漏
**解决**：这是多API版本的重点改进。如果仍有遗漏：
- 尝试降低DPI提高图片清晰度
- 使用更强的翻译模型
- 检查API的max_tokens是否足够

### 问题：图片显示不正确
**解决**：
- 确保markdown查看器支持图片显示
- 检查output.md中的图片路径是否正确（应为相对路径如`figures/page1_figure_1.png`）
- 确保figures/和tables/目录存在

### 问题：翻译质量不佳
**解决**：
- 尝试使用更强的模型（如gpt-4o）
- 在最终优化步骤后，手动进行校对
- 对于专业术语，可以在最终Markdown中进行替换

## 许可证

MIT License
