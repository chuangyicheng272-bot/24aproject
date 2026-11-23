
from collections import deque

import cv2
import numpy as np


class ImagePreprocessor:
    """Rail 影像前處理：模糊偵測、低光源增強與去雜訊。"""

    def __init__(
        self,
        blur_detect=True,
        low_light=False,
        denoise=True,
        ll_target=120.0,
        blur_ratio=0.4,
    ):
        # 模糊偵測
        self.blur_detect = bool(blur_detect)
        self.focus_history = deque(maxlen=90)
        self.is_blurry = False
        self.blur_ratio = float(blur_ratio)

        # 低光源增強
        self.low_light = bool(low_light)
        self.denoise = bool(denoise)
        self.ll_target = float(ll_target)
        self.ll_gamma = 1.0
        self.ll_mean = 0.0

    def detect_blur(self, gray_raw):
        """
        使用 Laplacian 變異數判斷畫面是否模糊。
        回傳 True 表示模糊。
        """
        if not self.blur_detect:
            self.is_blurry = False
            return False

        focus = float(
            cv2.Laplacian(gray_raw, cv2.CV_64F).var()
        )

        # 前 15 幀作為暖機資料
        if len(self.focus_history) < 15:
            self.focus_history.append(focus)
            self.is_blurry = False
            return False

        baseline = float(
            np.percentile(self.focus_history, 80)
        )

        # 場景本身紋理不足，不進行模糊判斷
        if baseline < 30.0:
            self.focus_history.append(focus)
            self.is_blurry = False
            return False

        self.is_blurry = focus < self.blur_ratio * baseline

        # 模糊影格不可寫入清晰度基準
        if not self.is_blurry:
            self.focus_history.append(focus)

        return self.is_blurry

    @staticmethod
    def gamma_lut(gamma):
        """產生 Gamma 查找表。"""
        lut = (
            np.arange(256, dtype=np.float32) / 255.0
        ) ** gamma

        return np.clip(
            lut * 255.0, 0, 255
        ).astype(np.uint8)

    def enhance_low_light(self, gray):
        """
        低光源增強。
        未啟用時原樣回傳影像。
        """
        mean = float(gray.mean())
        self.ll_mean = mean

        if not self.low_light:
            self.ll_gamma = 1.0
            return gray

        if self.denoise:
            gray = cv2.bilateralFilter(
                gray, 5, 40, 40
            )
            mean = float(gray.mean())

        # 避免除以零或 log(1)
        m = min(254.0, max(1.0, mean)) / 255.0
        target = self.ll_target / 255.0

        desired = float(
            np.log(target) / np.log(m)
        )

        desired = min(2.5, max(0.35, desired))

        # Gamma 時間平滑
        self.ll_gamma += 0.15 * (
            desired - self.ll_gamma
        )

        return cv2.LUT(
            gray,
            self.gamma_lut(self.ll_gamma)
        )

    def apply_display_gamma(self, frame):
        """將目前 Gamma 套用到彩色顯示影像。"""
        if (
            not self.low_light
            or abs(self.ll_gamma - 1.0) < 0.02
        ):
            return frame

        return cv2.LUT(
            frame,
            self.gamma_lut(self.ll_gamma)
        )

    def process(self, frame):
        """
        完整前處理流程。

        回傳：
            gray_raw: 原始灰階影像
            gray: 前處理後影像；模糊時為 None
            is_blurry: 是否模糊
            gamma: 目前 Gamma
            mean_brightness: 原始平均亮度
        """
        if frame is None:
            raise ValueError("輸入影像不可為 None")

        if frame.ndim == 3:
            gray_raw = cv2.cvtColor(
                frame, cv2.COLOR_BGR2GRAY
            )
        elif frame.ndim == 2:
            gray_raw = frame.copy()
        else:
            raise ValueError("不支援的影像維度")

        # 先使用原始灰階影像判斷模糊
        blurry = self.detect_blur(gray_raw)

        if blurry:
            return {
                "gray_raw": gray_raw,
                "gray": None,
                "is_blurry": True,
                "gamma": self.ll_gamma,
                "mean_brightness": float(gray_raw.mean()),
            }

        # 再進行低光源增強與 Gaussian Blur
        gray_enhanced = self.enhance_low_light(gray_raw)

        gray = cv2.GaussianBlur(
            gray_enhanced, (3, 3), 0
        )

        return {
            "gray_raw": gray_raw,
            "gray": gray,
            "is_blurry": False,
            "gamma": self.ll_gamma,
            "mean_brightness": self.ll_mean,
        }
