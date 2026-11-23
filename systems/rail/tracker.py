
import cv2
import numpy as np


def locate_template(gray, anchor, template, search_margin, clahe):
    """
    在 anchor 周圍搜尋 template。
    使用 CLAHE、TM_CCOEFF_NORMED 與次像素內插。

    回傳：
        (found_x, found_y, confidence)
    """

    x, y, w, h = anchor
    m = search_margin
    fh, fw = gray.shape

    sx1 = max(0, x - m)
    sy1 = max(0, y - m)
    sx2 = min(fw, x + w + m)
    sy2 = min(fh, y + h + m)

    search_area = clahe.apply(gray[sy1:sy2, sx1:sx2])

    if (
        search_area.shape[0] < template.shape[0]
        or search_area.shape[1] < template.shape[1]
    ):
        return None, None, 0.0

    result = cv2.matchTemplate(
        search_area,
        template,
        cv2.TM_CCOEFF_NORMED
    )

    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    px, py = max_loc
    rh, rw = result.shape

    sub_x = float(px)
    sub_y = float(py)

    if 0 < px < rw - 1 and 0 < py < rh - 1:
        yy, xx = np.mgrid[-1:2, -1:2]

        design = np.column_stack((
            (xx * xx).ravel(),
            (yy * yy).ravel(),
            (xx * yy).ravel(),
            xx.ravel(),
            yy.ravel(),
            np.ones(9),
        ))

        values = result[
            py - 1:py + 2,
            px - 1:px + 2
        ].astype(float).ravel()

        try:
            a, b, c, d, e, _ = np.linalg.lstsq(
                design, values, rcond=None
            )[0]

            hessian = np.array((
                (2.0 * a, c),
                (c, 2.0 * b)
            ))

            offset = np.linalg.solve(
                hessian,
                -np.array((d, e))
            )

            if (
                np.all(np.isfinite(offset))
                and np.all(np.abs(offset) <= 1.0)
                and a < 0.0
                and b < 0.0
                and np.linalg.det(hessian) > 1e-9
            ):
                sub_x += float(offset[0])
                sub_y += float(offset[1])

        except np.linalg.LinAlgError:
            pass

    return sx1 + sub_x, sy1 + sub_y, max_val
