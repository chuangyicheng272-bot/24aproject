from __future__ import annotations

import argparse
import time
from urllib.error import URLError
from urllib.request import urlopen

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise SystemExit(
        "Missing package. Please install OpenCV and NumPy first:\n"
        "  python -m pip install opencv-python numpy\n"
        f"Original error: {exc}"
    )


DEFAULT_PHONE_URL = "http://10.98.150.196:8080"


def candidate_urls(base_url: str) -> list[str]:
    base_url = base_url.rstrip("/")
    known_suffixes = ("/video", "/mjpegfeed", "/shot.jpg")
    if base_url.endswith(known_suffixes):
        return [base_url]
    return [
        f"{base_url}/video",
        f"{base_url}/mjpegfeed",
        f"{base_url}/shot.jpg",
        base_url,
    ]


def can_open_stream(url: str, timeout_seconds: float = 3.0) -> bool:
    cap = cv2.VideoCapture(url)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    return True
            time.sleep(0.1)
        return False
    finally:
        cap.release()


def open_first_working_url(base_url: str) -> str | None:
    for url in candidate_urls(base_url):
        print(f"Trying stream: {url}")
        if can_open_stream(url):
            print(f"Connected: {url}")
            return url
    return None


def show_video_stream(url: str) -> None:
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open camera stream: {url}")

    print("Press q to quit.")
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("No frame received. Check phone IP, port, and camera app stream path.")
            break

        cv2.imshow("Phone Camera Stream", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


def show_snapshot_loop(url: str, interval_seconds: float = 0.1) -> None:
    print("Press q to quit.")
    while True:
        try:
            with urlopen(url, timeout=5) as response:
                data = response.read()
        except URLError as exc:
            print(f"Unable to fetch snapshot: {exc}")
            break

        image = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if frame is None:
            print("Snapshot endpoint did not return a JPEG image.")
            break

        cv2.imshow("Phone Camera Snapshot", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
        time.sleep(interval_seconds)

    cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test phone camera connection with OpenCV.")
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_PHONE_URL,
        help="Phone camera base URL or stream URL, for example http://192.168.1.20:8080",
    )
    args = parser.parse_args()

    url = open_first_working_url(args.url)
    if url is None:
        print("Could not connect to the phone camera.")
        print("Common URLs:")
        print("  IP Webcam:  http://PHONE_IP:8080/video")
        print("  DroidCam:   http://PHONE_IP:4747/video")
        print("  Snapshot:   http://PHONE_IP:8080/shot.jpg")
        return

    if url.endswith("/shot.jpg"):
        show_snapshot_loop(url)
    else:
        show_video_stream(url)


if __name__ == "__main__":
    main()
