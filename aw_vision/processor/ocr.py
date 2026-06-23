"""OCR extraction, caveman summarization and screenshot optimization."""
import time
from datetime import datetime
from pathlib import Path

import ollama

from aw_vision.config import config
from aw_vision.processor.text import caveman_compress_text


class OcrMixin:
    def extract_ocr_text(self, img_path: Path, rec_id: str = None, keep_alive: int = 0) -> str:
        """Call local Ollama OCR model to extract all readable text from screenshot."""
        try:
            msg = f"Running OCR on screenshot using model: {config.ocr_model}"
            if rec_id:
                self.log_step(rec_id, msg)
            else:
                print(f"[{datetime.now()}] {msg}")
            client = ollama.Client(host=config.ollama_host)
            prompt = "Extract all readable text, titles, labels, or content from this desktop screenshot exactly as shown. Do not explain, describe, or add any meta-commentary. Just output the extracted text."
            response = client.chat(
                model=config.ocr_model,
                messages=[{"role": "user", "content": prompt, "images": [str(img_path)]}],
                options={"temperature": 0.1},
                keep_alive=keep_alive,
            )
            ocr_text = response.get("message", {}).get("content", "").strip()
            msg2 = f"OCR Extracted text length: {len(ocr_text)}"
            if rec_id:
                self.log_step(rec_id, msg2)
            else:
                print(f"[{datetime.now()}] {msg2}")
            return ocr_text
        except Exception as e:
            err_msg = f"Error running OCR with Ollama model {config.ocr_model}: {e}"
            if rec_id:
                self.log_step(rec_id, err_msg)
            else:
                print(err_msg)
            return ""

    def summarize_ocr_text(self, ocr_text: str, max_chars: int = 1200) -> str:
        """Pre-process, compress using Caveman style, and truncate OCR text to fit within constraints."""
        if not ocr_text:
            return ""

        compressed = caveman_compress_text(ocr_text)
        if len(compressed) <= max_chars:
            return compressed

        # Truncate and append truncation message
        truncated = compressed[:max_chars]
        last_pipe = truncated.rfind(" | ")
        if last_pipe > max_chars // 2:
            truncated = truncated[:last_pipe]

        return truncated + f" ... [OCR Text truncated from {len(compressed)} to {len(truncated)} chars]"

    def optimize_image(self, img_path: Path, rec_id: str, max_size: int = 1200):
        """Resize image to a maximum dimension of max_size maintaining aspect ratio, saving disk space and speeding up vision/OCR models."""
        if not img_path.exists():
            return
        try:
            from PIL import Image
            with Image.open(img_path) as img:
                width, height = img.size
                if max(width, height) <= max_size:
                    return

                self.log_step(rec_id, f"Optimizing screenshot dimensions (original: {width}x{height}) to max {max_size}px...")
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                img.save(img_path, "PNG", optimize=True)
                new_width, new_height = img.size
                self.log_step(rec_id, f"Screenshot successfully optimized to {new_width}x{new_height}.")
        except Exception as e:
            self.log_step(rec_id, f"Warning: Could not optimize screenshot {img_path.name}: {e}")
