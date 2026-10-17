# PDFArchiver

桌面 PDF 归档工具：OCR 识别 + 全文搜索 + 智能分类 + 跨盘安全迁移

## 核心功能

- **扫描索引**：批量扫描 PDF 文档，提取元数据并建立全文索引
- **OCR 识别**：基于 RapidOCR 的离线文字识别，支持中英文
- **全文搜索**：BM25 + trigram 混合检索，200 万行级数据 P95 < 500ms
- **智能分类**：多标签 + 分类树 + 语义向量索引
- **安全归档**：跨盘操作绝不先删源（G19），JSONL journal 崩溃恢复（G17）
- **本地优先**：所有数据存本地 SQLite，无云端依赖

## 技术栈

- **后端**：Python 3.11+，SQLite FTS5
- **前端**：PySide6（Qt 6）
- **OCR**：RapidOCR + ONNX Runtime
- **搜索**：自研 BM25 + trigram 混合引擎
- **向量**：语义索引（实验性）

## 安装

```bash
# 克隆仓库
git clone https://github.com/Lavie-purple/PDFArchiver.git
cd PDFArchiver

# 安装依赖
pip install -r requirements.txt

# 运行
python -m pdfarchiver.app
```

## 项目结构

```
src/pdfarchiver/
├── app.py              # 应用入口
├── config/             # 配置（路径、常量）
├── db/                 # 数据库模型与迁移
├── scan/               # 扫描索引
├── ocr/                # OCR 识别
├── search/             # 全文搜索
├── classify/           # 智能分类
├── archive/            # 归档操作
├── vector/             # 向量索引
└── ui/                 # PySide6 界面
```

## 安全特性

- **G17 Journal**：每个归档操作写 JSONL journal，崩溃后可恢复
- **G19 跨盘安全**：跨盘 copy 先验证目标 SHA256，成功后才删源
- **G18 撤销**：操作队列支持撤销（实验性）

## 性能基线

- 真实语料：10,977 份文档 / 202 万页
- 搜索 P95：2,809ms（200 候选，含 BM25 排序 + snippet）
- 冷启动：< 5s

## 开发

```bash
# 运行测试
pytest tests/

# 运行门禁
python gates/final.py

# G2 搜索基准测试
python scripts/g2_search_benchmark.py
```

## 已知问题

详见 [ISSUES.md](docs/ISSUES.md)

## 许可证

MIT
