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
