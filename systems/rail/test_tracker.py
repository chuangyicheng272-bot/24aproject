import cv2
import numpy as np

from systems.rail.tracker import locate_template


def main():
    # 建立測試影像
    np.random.seed(42)
    gray = np.random.randint(
        0, 256, (300, 400), dtype=np.uint8
    )

    # 建立模板
    template = gray[100:140, 150:190].copy()

    # 建立 CLAHE
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    # 搜尋範圍
    anchor = (140, 90, 60, 60)

    result = locate_template(
        gray,
        anchor,
        template,
        search_margin=20,
        clahe=clahe
    )

    x, y, confidence = result

    print("===== Tracker 測試 =====")
    print(f"預期座標： (150, 100)")
    print(f"實際座標： ({x:.4f}, {y:.4f})")
    print(f"Confidence：{confidence:.6f}")

    assert x is not None and y is not None
    assert abs(x - 150) < 0.1
    assert abs(y - 100) < 0.1
    assert confidence > 0.99

    print("Tracker 基準測試通過！")


if __name__ == "__main__":
    main()