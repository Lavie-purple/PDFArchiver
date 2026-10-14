"""OCR 能力层：把"识别一页"这件事与"什么时候该识别"隔开。

- `engine.py` 认识 RapidOCR / onnxruntime / provider 选择 / 串行锁，是唯一引擎代码。
- 编排（跑哪些文档、结果写哪、状态怎么流转）在 `services/ocr_service.py`。

依赖方向：本层不许 import `ui` 与 `semantic`（`tests/guards/test_architecture.py` 盯这条）。
"""
