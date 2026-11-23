
import cv2
import numpy as np

from systems.rail.preprocessing import ImagePreprocessor


def main():
    print("===== Preprocessing 基準測試 =====")

    # 1. 預設設定
    processor = ImagePreprocessor()

    assert processor.low_light is False
    assert processor.denoise is True
    assert processor.ll_target == 120.0

    print("1. 預設參數：通過")

    # 2. 模糊偵測暖機
    rng = np.random.default_rng(42)

    sharp = rng.integers(
        0, 256, (240, 320), dtype=np.uint8
    )

    for _ in range(15):
        result = processor.process(sharp)

    assert result["is_blurry"] is False
    print("2. 清晰影像暖機：通過")

    # 3. 模糊影像判斷
    blurry = cv2.GaussianBlur(
        sharp, (31, 31), 0
    )

    result = processor.process(blurry)

    assert result["is_blurry"] is True
    assert result["gray"] is None

    print("3. 模糊影像判斷：通過")

    # 4. 低光源關閉時，影像不應被 Gamma 改變
    processor2 = ImagePreprocessor(
        blur_detect=False,
        low_light=False
    )

    dark = np.full(
        (120, 160), 48, dtype=np.uint8
    )

    enhanced = processor2.enhance_low_light(dark)

    assert np.array_equal(dark, enhanced)
    assert processor2.ll_gamma == 1.0

    print("4. 低光源關閉：通過")

    # 5. 低光源增強啟用
    processor3 = ImagePreprocessor(
        blur_detect=False,
        low_light=True,
        denoise=True,
        ll_target=120
    )

    enhanced = processor3.enhance_low_light(dark)

    assert enhanced.shape == dark.shape
    assert processor3.ll_gamma > 0

    print("5. 低光源增強：通過")

    # 6. 完整影像處理流程
    processor4 = ImagePreprocessor(
        blur_detect=False,
        low_light=False
    )

    color_frame = np.zeros(
        (240, 320, 3), dtype=np.uint8
    )

    output = processor4.process(color_frame)

    assert output["gray_raw"].ndim == 2
    assert output["gray"].ndim == 2
    assert output["is_blurry"] is False

    print("6. 完整前處理流程：通過")

    print("\nPreprocessing 基準測試通過！")


if __name__ == "__main__":
    main()
