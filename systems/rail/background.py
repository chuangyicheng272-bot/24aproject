
import cv2
import numpy as np


class BackgroundTracker:
    """背景參考 ROI 追蹤與攝影機晃動補償。"""

    def __init__(self, clahe, search_margin=0):
        self.clahe = clahe

        self.bg_roi = None
        self.bg_template = None
        self.bg_template_offset = (0, 0)
        self.bg_search_margin = search_margin

        self.bg_found_x = 0.0
        self.bg_found_y = 0.0
        self.bg_confidence = 0.0

        self.bg_hist_x = []
        self.bg_hist_y = []

        self.comp_baseline = None

    def reset(self):
        """重設背景追蹤狀態。"""
        self.bg_roi = None
        self.bg_template = None
        self.bg_template_offset = (0, 0)
        self.bg_search_margin = 0

        self.bg_found_x = 0.0
        self.bg_found_y = 0.0
        self.bg_confidence = 0.0

        self.bg_hist_x.clear()
        self.bg_hist_y.clear()

        self.comp_baseline = None

    def initialize(self, gray, roi):
        """使用指定 ROI 建立背景模板。"""
        x, y, w, h = roi

        if w <= 0 or h <= 0:
            raise ValueError("背景 ROI 尺寸必須大於 0")

        frame_h, frame_w = gray.shape

        if x < 0 or y < 0 or x + w > frame_w or y + h > frame_h:
            raise ValueError("背景 ROI 超出影像範圍")

        self.bg_roi = roi
        self.bg_template = self.clahe.apply(
            gray[y:y + h, x:x + w]
        ).copy()

        self.bg_template_offset = (x, y)
        self.bg_search_margin = max(w, h)

        self.bg_found_x = float(x)
        self.bg_found_y = float(y)
        self.bg_confidence = 1.0

        self.bg_hist_x.clear()
        self.bg_hist_y.clear()
        self.comp_baseline = None

    def track(self, gray, locate_func):
        """
        追蹤背景位置。

        locate_func 使用原本 tracker.py 的 locate_template。
        """
        if self.bg_roi is None:
            self.bg_confidence = 0.0
            return

        if self.bg_template is None:
            self.initialize(gray, self.bg_roi)
            return

        fx, fy, confidence = locate_func(
            gray,
            self.bg_roi,
            self.bg_template,
            self.bg_search_margin,
            self.clahe
        )

        self.bg_confidence = confidence

        # 保留原始程式的信心門檻
        if fx is None or confidence < 0.2:
            return

        self.bg_found_x = fx
        self.bg_found_y = fy

        bx, by = self.bg_template_offset

        self.bg_hist_x.append(fx - bx)
        self.bg_hist_y.append(fy - by)

        # 保留原本 deque(maxlen=150) 的歷史長度
        if len(self.bg_hist_x) > 150:
            self.bg_hist_x.pop(0)

        if len(self.bg_hist_y) > 150:
            self.bg_hist_y.pop(0)

    def calculate_compensated_displacement(
        self,
        found_x,
        found_y
    ):
        """計算振動物減去背景晃動後的相對位移。"""
        rel_x = found_x - self.bg_found_x
        rel_y = found_y - self.bg_found_y

        if self.comp_baseline is None:
            self.comp_baseline = (rel_x, rel_y)

        dx = rel_x - self.comp_baseline[0]
        dy = rel_y - self.comp_baseline[1]

        return dx, dy

    @staticmethod
    def pick_background_roi(mean_gray, motion_map, rail_roi):
        """從影像中挑選紋理較明顯且移動較少的背景區域。"""
        fh, fw = motion_map.shape

        win = int(min(80, max(32, min(fw, fh) // 8)))

        if fw <= win or fh <= win:
            return None

        step = max(8, win // 2)

        gx = cv2.Sobel(
            mean_gray, cv2.CV_32F, 1, 0, ksize=3
        )
        gy = cv2.Sobel(
            mean_gray, cv2.CV_32F, 0, 1, ksize=3
        )

        grad = cv2.magnitude(gx, gy)

        rx, ry, rw, rh = rail_roi
        best = None
        best_score = -1.0
        best_texture = 0.0

        for y in range(0, fh - win + 1, step):
            for x in range(0, fw - win + 1, step):

                # 排除振動物 ROI 外擴 10 px 的區域
                if (
                    x < rx + rw + 10
                    and x + win > rx - 10
                    and y < ry + rh + 10
                    and y + win > ry - 10
                ):
                    continue

                motion = float(
                    np.mean(motion_map[y:y + win, x:x + win])
                )

                texture = float(
                    np.mean(grad[y:y + win, x:x + win])
                )

                score = texture / (1.0 + 3.0 * motion)

                if score > best_score:
                    best_score = score
                    best_texture = texture
                    best = (x, y, win, win)

        if best is None or best_texture < 8.0:
            return None

        return best
