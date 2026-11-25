import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from core.text_engine import text_engine
from core.database import db

# Create a test synthetic image with text drawn on it
h, w = 600, 800
img = np.ones((h, w, 3), dtype=np.uint8) * 40

# Add title at top
cv2.putText(img, "EXCAVATOR SIMULATOR", (200, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)

# Add vehicle label in center
cv2.rectangle(img, (300, 250), (480, 310), (80, 80, 80), -1)
cv2.putText(img, "CAT-320D", (310, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2)

# Add watermark-like text at bottom right
cv2.putText(img, "Gemini AI 2024", (650, 580), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

test_path = "scratch/test_text_sample.png"
cv2.imwrite(test_path, img)

asset = {
    "id": 999999,
    "original_path": test_path,
    "filename": "test_text_sample.png",
    "width": w,
    "height": h,
    "collection": "test"
}

regions, model_name, model_ver = text_engine.detect_text(asset)
print(f"Detected {len(regions)} regions via {model_name} (v{model_ver}):")
for r in regions:
    print(f" - [{r['category']}] box: ({r['box_x']}, {r['box_y']}, {r['box_w']}x{r['box_h']}), conf: {r['confidence']}, wm: {r['is_watermark_candidate']}")
