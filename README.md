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

## Controls

The application uses the Top Row (Automap buttons) and the Side Column for control.

```text
       [V-] [V+] [<<] [>>] [PK] [D-] [D+] [M!]
      +----+----+----+----+----+----+----+----+
      |    |    |    |    |    |    |    |    | [AU]
      |    |    |    |    |    |    |    |    |
      |    |    |    |    |    |    |    |    |
      |    |    |    |    |    |    |    |    |
      |         V I S U A L I Z E R           |
      |               G R I D                 |
      |    |    |    |    |    |    |    |    |
      |    |    |    |    |    |    |    |    |
      +----+----+----+----+----+----+----+----+
```

| Button Label | Function | Description |
| :--- | :--- | :--- |
| **V- / V+** | Volume Control | Decrease / Increase system volume (Windows only). |
| **<< / >>** | Mode Selection | Cycle through visualizer modes (Prev / Next). |
| **PK** | Peak Toggle | Toggle floating peak indicators (Mode 1 only). |
| **D- / D+** | Decay Rate | Adjust visual decay speed (Slower/Faster). |
| **M!** | Mute Arm | Hold for 0.4s to toggle system mute (prevents accidental presses). |
| **AU** | Input Cycle | Top-right side button. Cycles through available audio input devices. |

## Usage

1. **Connect Launchpad**: Ensure your Launchpad MK2 is connected.
2. **Run the Visualizer**:
   ```bash
   python launchpad_visualizer.py
   ```

## Troubleshooting

- **No Audio?**: The script tries to auto-detect your "Stereo Mix" or Loopback interface. If it fails, use the side button (89) labeled `[AU]` above to cycle through available audio inputs until you see activity.
- **MIDI Error**: Ensure no other software (like Ableton Live) has exclusive control over the Launchpad.
