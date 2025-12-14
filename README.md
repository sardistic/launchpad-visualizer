# Audio Device Scanner

A utility script to identify active audio input devices on your system, specifically designed to help configure the Launchpad Visualizer.

## Purpose

This script (`find_active_audio.py`) scans all available audio input devices to find which one is currently receiving audio. This is useful for determining the correct device index to use in the main visualizer script.

## Usage

1. **Play Audio**: Start playing music or generate sound on your computer (e.g., Spotify, YouTube).
2. **Run Script**: Execute the script from your terminal:
   ```bash
   python find_active_audio.py
   ```
3. **Wait**: The script will listen for approximately 0.2 seconds on each input device.
4. **View Results**: 
    - Real-time volume bars will show for each device.
    - A summary will list all devices where a signal was detected.
    - The script will recommend the best Device ID to use.

## Dependencies

- `sounddevice`
- `numpy`
