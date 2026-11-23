
import cv2
import numpy as np

from systems.rail.background import BackgroundTracker


def main():
    print("===== BackgroundTracker 測試 =====")

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    tracker = BackgroundTracker(clahe)

    # 建立測試影像
    rng = np.random.default_rng(42)
    gray = rng.integers(
        0, 256, size=(240, 320), dtype=np.uint8
    )

    roi = (40, 50, 40, 40)

    # 1. 測試背景初始化
    tracker.initialize(gray, roi)

    assert tracker.bg_roi == roi
    assert tracker.bg_template is not None
    assert tracker.bg_template_offset == (40, 50)
    assert tracker.bg_found_x == 40.0
    assert tracker.bg_found_y == 50.0

    print("1. 背景初始化：通過")

    # 2. 測試正常背景追蹤
    def fake_locate(*args):
        return 45.0, 53.0, 0.9

    tracker.track(gray, fake_locate)

    assert tracker.bg_found_x == 45.0
    assert tracker.bg_found_y == 53.0
    assert tracker.bg_confidence == 0.9
    assert len(tracker.bg_hist_x) == 1

    print("2. 正常背景追蹤：通過")

    # 3. 測試低信心值時不更新位置
    previous_x = tracker.bg_found_x
    previous_y = tracker.bg_found_y

    def low_confidence_locate(*args):
        return 70.0, 80.0, 0.1

    tracker.track(gray, low_confidence_locate)

    assert tracker.bg_found_x == previous_x
    assert tracker.bg_found_y == previous_y
    assert len(tracker.bg_hist_x) == 1

    print("3. 低信心值保留上一位置：通過")

    # 4. 測試補償位移
    dx1, dy1 = tracker.calculate_compensated_displacement(
        150.0, 100.0
    )

    dx2, dy2 = tracker.calculate_compensated_displacement(
        152.0, 99.0
    )

    assert np.isclose(dx1, 0.0)
    assert np.isclose(dy1, 0.0)
    assert np.isclose(dx2, 2.0)
    assert np.isclose(dy2, -1.0)

    print("4. 攝影機晃動補償公式：通過")

    # 5. 測試背景 ROI 自動選取
    motion_map = np.zeros((240, 320), dtype=np.float32)

    selected_roi = tracker.pick_background_roi(
        gray,
        motion_map,
        rail_roi=(140, 100, 40, 40)
    )

    assert selected_roi is not None

    print("5. 背景 ROI 自動選取：通過")
    print("   選取結果：", selected_roi)

    print("\nBackgroundTracker 基準測試通過！")


if __name__ == "__main__":
    main()
