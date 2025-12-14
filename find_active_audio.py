import sounddevice as sd
import numpy as np
import time

print("Scanning input devices for audio signal...")
print("Please play some loud music on your computer now!")
time.sleep(2.0)

candidates = []

for i, dev in enumerate(sd.query_devices()):
    if dev['max_input_channels'] > 0:
        try:
            # Listen for 0.2 seconds
            duration = 0.2
            recording = sd.rec(int(duration * 44100), samplerate=44100, channels=1, device=i, dtype='float32')
            sd.wait()
            
            # Calculate peak volume
            peak = np.max(np.abs(recording))
            
            bar = "#" * int(peak * 50)
            print(f"[{i}] {dev['name']:<40} Peak: {peak:.4f} {bar}")
            
            if peak > 0.01:
                candidates.append((i, dev['name'], peak))
                
        except Exception as e:
            # print(f"[{i}] {dev['name']} - Error: {e}")
            pass

print("\n--- Results ---")
if not candidates:
    print("No audio signal detected on any device. Are you sure music is playing?")
else:
    print("Found signal on:")
    candidates.sort(key=lambda x: x[2], reverse=True)
    for c in candidates:
        print(f"Device ID {c[0]}: {c[1]} (Peak: {c[2]:.2f})")
        
    print(f"\nRECOMMENDATION: Use Device ID {candidates[0][0]}")
