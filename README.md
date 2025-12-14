# Launchpad MK2 Visualizer

A professional-grade Python application that turns your Novation Launchpad MK2 into a high-performance, audio-reactive visualizer.

## Features

- **Audio Reactivity**: Real-time FFT analysis using `sounddevice` and `numpy`.
- **Multiple Modes**:
  - **Dual Spectrum**: Top/Bottom split frequency analysis.
  - **Diamond Splash**: Volume-reactive center pulses with particle effects.
  - **The Oracle**: Esoteric, organic background animations with sparkle overlays.
  - **Fire & Heatmap**: Classic gradient visualizations.
- **Particle System**: Physics-based particles that react to audio peaks.
- **Low Latency**: Optimized for 60 FPS performance.
- **Auto-Gain Control**: Automatically adjusts sensitivity to input volume.

## Requirements

- Python 3.x
- Novation Launchpad MK2 (connected via USB)

### Dependencies

Install the required packages:

```bash
pip install sounddevice numpy mido python-rtmidi
```

*Note: `pycaw` and `comtypes` are optional for Windows system volume control integration.*

## Usage

1. **Connect Launchpad**: Ensure your Launchpad MK2 is connected.
2. **Run the Visualizer**:
   ```bash
   python launchpad_visualizer.py
   ```
3. **Controls**:
   - **Top Row**:
     - Buttons 1-2: Volume Control (if enabled)
     - Buttons 3-4: Previous / Next Mode
     - Button 5: Toggle Peak Indicators
     - Button 6-7: Adjust Decay Rate
     - Button 8: Arm Mute

## Troubleshooting

- **No Audio?**: The script tries to auto-detect your "Stereo Mix" or Loopback interface. If it fails, use the side button (89) to cycle through available audio inputs.
- **MIDI Error**: Ensure no other software (like Ableton Live) has exclusive control over the Launchpad.
