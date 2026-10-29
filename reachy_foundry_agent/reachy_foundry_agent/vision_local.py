"""On-robot person detection using ultralytics (YOLO), if it is installed.

ultralytics/torch live in the Reachy Mini apps venv and are not declared as hard dependencies
of this app, so everything is imported lazily and callers must handle ``is_available() == False``.
"""

from __future__ import annotations

import importlib.util
import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

_PERSON_CLASS = 0  # COCO class id for "person"
MIN_CONFIDENCE = 0.35


class PersonDetector:
    def __init__(self, model: str = "yolov8n.pt") -> None:
        self._model_name = model
        self._model = None
        self._lock = threading.Lock()  # the model is loaded once and used by one thread at a time

    @staticmethod
    def is_available() -> bool:
        return importlib.util.find_spec("ultralytics") is not None

    def _load(self):
        if self._model is None:
            from ultralytics import YOLO  # first use may download the weights

            log.info("loading person detector %s", self._model_name)
            self._model = YOLO(self._model_name)
        return self._model

    def find_person(self, frame_bgr: np.ndarray) -> tuple[float, float] | None:
        """Return the pixel (u, v) of the middle of the biggest person in the frame, or None."""
        with self._lock:
            results = self._load().predict(
                frame_bgr, classes=[_PERSON_CLASS], conf=MIN_CONFIDENCE, imgsz=320, verbose=False
            )
        boxes = results[0].boxes if results else None
        if boxes is None or len(boxes) == 0:
            return None
        xyxy = boxes.xyxy.cpu().numpy()
        areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
        x1, y1, x2, y2 = xyxy[int(np.argmax(areas))]
        # Aim a bit above the box centre: that is the head/face rather than the belly.
        return float((x1 + x2) / 2), float(y1 + 0.35 * (y2 - y1))
