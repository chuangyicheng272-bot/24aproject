# Railway Vibration Frequency Detector

This project is a desktop app for detecting vibration frequency from a camera, a video file, or a microphone. It is designed for visual inspection of rail or mechanical vibration signals and provides live frequency analysis with a Tkinter-based GUI.

## Features

- Real-time vibration detection using camera input
- Offline analysis from a recorded video file
- High-frequency analysis from microphone input
- Manual or automatic ROI selection for the vibrating target
- Background shake compensation using a static reference region
- Automatic recovery after tracking loss
- Blur detection and pause logic
- Low-light enhancement for weak video input
- Frequency spectrum and waveform visualization
- CSV-based normal-vibration baseline logging
- Reference tone generator for validating measurement accuracy

## Project structure

- `frequency.py` — main GUI application and analysis logic

## Requirements

- Python 3.10+
- Windows is the intended target platform for the GUI and audio setup
- Required packages:
  - `opencv-python`
  - `numpy`
  - `matplotlib`
  - `Pillow`
  - `sounddevice`

## Setup

1. Open a terminal in the project folder.
2. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```powershell
pip install opencv-python numpy matplotlib pillow sounddevice
```

4. Run the app:

```powershell
python frequency.py
```

## Usage

1. Click the source button to choose a data source:
   - Camera (real-time)
   - Video file (offline)
   - Microphone (high-frequency)
2. Select the vibrating area by dragging with the left mouse button.
3. Optionally select a background reference region with the right mouse button.
4. Use the detection direction selector to choose `auto`, `vertical`, `horizontal`, or `both`.
5. Monitor the real-time frequency, waveform, and phase information in the dashboard.
6. Use the reference tone function to verify detector accuracy against a known frequency.

## Notes

- The app uses `TkAgg` for Matplotlib rendering.
- For microphone access, the system must have a valid audio backend available.
- The app writes normal-vibration baseline data to CSV files named `normal_vibration.csv` and `normal_baseline.csv` in the project folder.

## License

This project is provided for local research and analysis use in the current workspace.
