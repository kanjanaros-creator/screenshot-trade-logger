import os
import io
import cv2
import pytesseract
import numpy as np
from PIL import Image

TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_LINEAR)
    thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                cv2.THRESH_BINARY, 35, 10)
    return thr

def extract_text_from_image(image_data: io.BytesIO) -> str:
    image = Image.open(image_data).convert("RGB")
    img = np.array(image)[:, :, ::-1]
    proc = _preprocess(img)
    try:
        text = pytesseract.image_to_string(proc, lang="tha+eng")
    except Exception:
        text = pytesseract.image_to_string(proc)
    return text
