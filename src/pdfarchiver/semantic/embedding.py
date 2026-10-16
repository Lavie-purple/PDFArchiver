"""语义嵌入层：把文本块变成 512 维向量。

按 D-036 定：
- 模型：bge-small-zh-v1.5 int8 量化版（22.8MB）
- 后端：DirectML（GPU）优先，CPU 兜底
- 向量维度：512，已归一化（用内积 = 余弦）
- 批大小：16（探针实测最优）

模型路径由 config.paths.models_dir 定，不许出现第二处路径字面量（ISSUES I37）。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from pdfarchiver.config.paths import AppPaths


class EmbeddingService:
    """文本 → 向量。线程安全（ONNX session 本身是线程安全的）。"""

    MODEL_NAME = "bge-small-zh-v1.5"
    MODEL_FILE = "onnx/model_int8.onnx"
    TOKENIZER_FILE = "tokenizer.json"
    DIM = 512
    BATCH_SIZE = 16
    MAX_LENGTH = 256

    def __init__(self, data_root: Path | None = None) -> None:
        from pdfarchiver.config.paths import resolve_data_root
        self._data_root = data_root or resolve_data_root()
        self._paths = AppPaths.resolve(self._data_root)
        self._session: ort.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None

    def _ensure_session(self) -> ort.InferenceSession:
        if self._session is not None:
            return self._session

        model_dir = self._paths.models_dir / self.MODEL_NAME
        model_path = model_dir / self.MODEL_FILE
        tokenizer_path = model_dir / self.TOKENIZER_FILE

        if not model_path.exists():
            raise FileNotFoundError(
                f"语义模型不存在：{model_path}\n"
                f"请先下载 {self.MODEL_NAME} 到 {self._paths.models_dir}"
            )
        if not tokenizer_path.exists():
            raise FileNotFoundError(
                f"分词器不存在：{tokenizer_path}\n"
                f"请先下载 {self.MODEL_NAME} 到 {self._paths.models_dir}"
            )

        # DirectML 优先，CPU 兜底
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self._session = ort.InferenceSession(str(model_path), sess_options=so, providers=providers)
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        return self._session

    def _tokenize(self, texts: list[str]) -> dict[str, np.ndarray]:
        """分词 + 补齐。"""
        assert self._tokenizer is not None
        self._tokenizer.enable_truncation(max_length=self.MAX_LENGTH)
        self._tokenizer.enable_padding(
            pad_id=self._tokenizer.token_to_id("[PAD]") or 0,
            pad_token="[PAD]"
        )
        enc = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        # token_type_ids：单句 BERT 输入恒为 0
        feeds["token_type_ids"] = np.zeros_like(ids)
        return feeds

    def _pool_normalize(self, out: list[np.ndarray], mask: np.ndarray) -> np.ndarray:
        """若图输出是 [B,T,H] 则自己做 mean pooling；若是 [B,H] 直接用。"""
        v = out[0]
        if v.ndim == 3:
            m = mask.astype(np.float32)[:, :, None]
            v = (v * m).sum(1) / np.clip(m.sum(1), 1e-6, None)
        v = v.astype(np.float32)
        return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)

    def embed(self, texts: list[str]) -> np.ndarray:
        """把一批文本变成向量矩阵（N, 512），dtype=float32，已归一化。

        空列表返回 (0, 512) 的空矩阵。
        """
        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32)

        session = self._ensure_session()
        all_embeddings = []

        # 分批处理
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            feeds = self._tokenize(batch)
            outputs = session.run(None, feeds)
            # mean pooling + 归一化
            all_embeddings.append(self._pool_normalize(outputs, feeds["attention_mask"]))

        return np.vstack(all_embeddings).astype(np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        """单条文本 → 向量（512,）。"""
        return self.embed([text])[0]

    def close(self) -> None:
        """释放 ONNX session。"""
        self._session = None
        self._tokenizer = None
