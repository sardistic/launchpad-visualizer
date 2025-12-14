import time
import math
from collections import deque
import numpy as np
import mido
import sounddevice as sd
import colorsys

try:
    import comtypes
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    HAS_PYCAW = True
except Exception:
    HAS_PYCAW = False

# --- Configuration ---
FPS = 60  # Higher FPS = Lower Latency (Buffer size is smaller)
SAMPLE_RATE = 44100
GRID_W = 8
GRID_H = 8
BANDS = 16 # Increased to 16 for Dual-Spectrum (Top/Bottom split)
PORT_HINT = "Launchpad MK2"

# --- Color Palettes & Mapping ---

def get_rainbow_color(phase):
    """Generate a color from the rainbow spectrum based on phase (0.0-1.0)."""
    # HSV to RGB (0-1)
    r, g, b = colorsys.hsv_to_rgb(phase % 1.0, 1.0, 1.0)
    return int((phase % 1.0) * 127)

def get_fire_color(level):
    """Map level (0.0-1.0) to a fire palette (Red -> Orange -> Yellow -> White)."""
    if level < 0.3: return 5   # Red
    if level < 0.6: return 9   # Orange
    if level < 0.8: return 13  # Yellow
    return 3                   # White/Bright

def get_heatmap_color(level):
    """Map level (0.0-1.0) to Blue->Green->Red."""
    if level < 0.3: return 45 # Blue
    if level < 0.6: return 21 # Green
    return 5                  # Red

# --- Note Mapping ---

def grid_note(x, y):
    return 11 + x + (7 - y) * 10

def top_row_note(x):
    return 91 + x

def right_side_note(y):
    return 104 + (7 - y)

def decode_grid_xy(note):
    # Grid: 11-88 (excluding x9, x0)
    if 11 <= note <= 88:
        n = note - 11
        col = n % 10
        row_top = n // 10
        if 0 <= col <= 7 and 0 <= row_top <= 7:
            return col, 7 - row_top
    return None

def decode_cc_xy(control):
    # Top row CCs are 104-111 on MK2
    if 104 <= control <= 111:
        return (control - 104), 8  # y=8 indicates top row
    return None

def open_ports():
    out_name = in_name = None
    outputs = mido.get_output_names()
    inputs = mido.get_input_names()
    
    print(f"Scanning MIDI Ports...")
    print(f"Outputs found: {outputs}")
    print(f"Inputs found: {inputs}")

    for n in outputs:
        if PORT_HINT in n:
            out_name = n
            break
    for n in inputs:
        if PORT_HINT in n:
            in_name = n
            break
    if not out_name:
        print(f"ERROR: Could not find output port matching '{PORT_HINT}'")
        return None, None, None, None
    try:
        outp = mido.open_output(out_name)
    except Exception as e:
        print(f"Error opening output {out_name}: {e}")
        return None, None, None, None
    inp = None
    if in_name:
        try:
            inp = mido.open_input(in_name)
        except Exception:
            inp = None
    return outp, inp, out_name, in_name

def reset_to_programmer_mode(outp):
    # SysEx to force Session Mode (which allows custom LED control)
    # Header: F0 00 20 29 02 18
    # Command: 22 (Set Session Mode)
    # Value: 00 (Session)
    msg = mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x18, 0x22, 0x00])
    try:
        outp.send(msg)
        time.sleep(0.1) # Wait for device to switch
    except Exception as e:
        print(f"Warning: Failed to send reset SysEx: {e}")

def clear_all(outp):
    # Reset all grid notes
    try:
        # Send Reset SysEx first
        reset_to_programmer_mode(outp)
        
        for x in range(GRID_W):
            for y in range(GRID_H):
                outp.send(mido.Message('note_off', note=grid_note(x, y), velocity=0))
        # Reset top row
        for x in range(GRID_W):
            outp.send(mido.Message('control_change', control=104+x, value=0))
            outp.send(mido.Message('note_off', note=top_row_note(x), velocity=0))
        # Reset right side
        for y in range(GRID_H):
            outp.send(mido.Message('note_off', note=right_side_note(y), velocity=0))
    except Exception as e:
        print(f"Warning: Failed to clear some LEDs: {e}")

def clamp01(v):
    return 0.0 if v <= 0 else (1.0 if v >= 1.0 else v)

def gradient_color(level, mode, beat_phase, x, y):
    v = clamp01(level)
    
    # Mode 0: Standard Green/Yellow/Red Gradient
    if mode == 0:
        return 127 if v > 0.75 else 96 if v > 0.5 else 64 if v > 0.25 else 24
        
    # Mode 1: Smooth Sine Pulse (Pink/Purple)
    if mode == 1:
        return 50 + int(v * 3)
        
    # Mode 2: Beat Pulse (Blue/Cyan)
    if mode == 2:
        p = 0.6 + 0.4 * math.sin(2 * math.pi * beat_phase)
        bright = clamp01(v * p)
        return 30 + int(bright * 5)
    
    # Mode 3: Fire (Red/Orange/Yellow)
    if mode == 3:
        return get_fire_color(v)

    # Mode 4: Rainbow
    if mode == 4:
        hue = (x / 8.0) + (beat_phase * 0.5)
        cycle = [5, 9, 13, 21, 29, 45, 53]
        idx = int(hue * len(cycle)) % len(cycle)
        if v < 0.1: return 0
        return cycle[idx]

    # Mode 5 & 6: Diamond Splash (Esoteric/Deep)
    if mode == 5 or mode == 6:
        # Esoteric palette: Deep Purple -> Teal -> Ethereal Blue
        if v > 0.8: return 37 # Ethereal Blue/Cyan
        if v > 0.5: return 53 # Magenta/Purple
        if v > 0.2: return 81 # Dim Zinc/Blue
        return 49 # Deep Purple

    return int(v * 127)

class VolumeCtl:
    def __init__(self):
        self.ready = False
        if not HAS_PYCAW:
            return
        try:
            dev = AudioUtilities.GetSpeakers()
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self.vol = cast(iface, POINTER(IAudioEndpointVolume))
            self.ready = True
        except Exception:
            self.ready = False
    def get_scalar(self):
        if not self.ready:
            return None
        return float(self.vol.GetMasterVolumeLevelScalar())
    def set_scalar(self, s):
        if not self.ready:
            return
        s = float(min(max(s, 0.0), 1.0))
        self.vol.SetMasterVolumeLevelScalar(s, None)
    def change(self, d):
        if not self.ready:
            return
        cur = self.get_scalar()
        if cur is None:
            return
        self.set_scalar(cur + d)
    def toggle_mute(self):
        if not self.ready:
            return
        self.vol.SetMute(not bool(self.vol.GetMute()), None)

class Particle:
    def __init__(self, x, y, vel_y, color_idx):
        self.x = x
        self.y = float(y)
        self.vel_y = vel_y
        self.color_idx = color_idx
        self.life = 1.0

class Wave:
    def __init__(self, radius=0.0, speed=0.4):
        self.radius = radius
        self.life = 1.0
        self.speed = speed

class State:
    def __init__(self):
        self.mode = 0
        self.brightness = 1.0
        self.gain = 1.0
        self.decay = 0.80 
        self.enable_peaks = True
        self.smooth = np.zeros(BANDS, dtype=np.float32)
        self.peak_hold = np.zeros(BANDS, dtype=np.int32)
        self.peak_decay_ctr = np.zeros(BANDS, dtype=np.int32)
        self.energy_hist = deque(maxlen=round(4 * FPS))
        self.last_onsets = deque(maxlen=8)
        self.bpm = 120.0
        self.last_beat_time = time.time()
        self.beat_phase = 0.0
        self.pressed_at = {}
        self.held = set()
        self.hold_actions = {}
        self.highlight_until = {} 
        self.last_hold_tick = 0.0
        
        # Particles & Waves
        self.particles = []
        self.waves = []
        self.diamond_radius = 0.0 # Smoothed radius for Mode 5/6
        
        # Mode 7 Smoothing Buffer
        self.grid_smooth = np.zeros((GRID_W, GRID_H), dtype=np.float32)
        self.side_smooth = np.zeros(8, dtype=np.float32)
        self.top_smooth = np.zeros(8, dtype=np.float32)
        
        # Auto-Gain Variables
        self.agc_max = 0.01 
        self.agc_decay = 0.995 
        
        # Stream Control
        self.req_new_stream = None

def compute_bands(mono, state):
    # FFT
    n = len(mono)
    fft = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(n, d=1.0 / SAMPLE_RATE)
    
    # Tuned Frequency Ranges (Hz) - Exactly 16 Bands for Dual Spectrum
    # Raised start to 60Hz to cut rumble
    ranges = [
        (60, 100), (100, 150), (150, 250), (250, 400),      # Lows
        (400, 600), (600, 900), (900, 1300), (1300, 2000), # Low-Mids
        (2000, 3000), (3000, 4500), (4500, 6500), (6500, 9000), # High-Mids
        (9000, 11000), (11000, 13500), (13500, 16000), (16000, 20000) # Highs
    ]
    
    # Weighting to balance the spectrum (Dampen loud low-mids)
    weights = [
        0.8, 0.7, 0.7, 0.7,  # Lows (Dampened)
        0.8, 0.9, 1.0, 1.0,  # Low-Mids
        1.1, 1.1, 1.2, 1.2,  # High-Mids (Boosted)
        1.3, 1.3, 1.4, 1.5   # Highs (Boosted significantly)
    ]

    out = []
    for i, (f0, f1) in enumerate(ranges):
        idx = np.where((freqs >= f0) & (freqs < f1))[0]
        if idx.size == 0:
            val = 0.0
        else:
            val = np.sqrt(np.mean(fft[idx]**2))
        out.append(val * weights[i])
    
    arr = np.array(out, dtype=np.float32)
    
    # --- Auto-Gain Control (AGC) ---
    current_max = np.max(arr)
    if current_max > state.agc_max:
        state.agc_max = current_max 
    else:
        state.agc_max *= 0.99 
    
    norm_factor = max(state.agc_max, 0.05)
    arr = np.clip(arr / norm_factor, 0.0, 1.0)
    
    # Aggressive Noise Gate (Raised to 0.2)
    arr[arr < 0.2] = 0.0
    
    return arr

def update_tempo(state, mono):
    e = float(np.sqrt(np.mean(mono ** 2)))
    state.energy_hist.append(e)
    if len(state.energy_hist) >= int(0.5 * FPS):
        avg = float(np.mean(state.energy_hist))
        std = float(np.std(state.energy_hist))
        thr = avg + 0.7 * std
        t = time.time()
        if e > thr and (len(state.last_onsets) == 0 or (t - state.last_onsets[-1]) > 0.25):
            state.last_onsets.append(t)
            # Trigger Wave
            if state.mode == 5:
                state.waves.append(Wave(radius=0.0, speed=0.4))
            elif state.mode == 6:
                state.waves.append(Wave(radius=8.0, speed=-0.4)) # Inward wave
                
            if len(state.last_onsets) >= 2:
                ivals = np.diff(np.array(state.last_onsets))
                if ivals.size > 0:
                    med = float(np.median(ivals))
                    if 0.25 <= med <= 2.0:
                        state.bpm = 60.0 / med
                        state.last_beat_time = t
    period = max(60.0 / max(state.bpm, 1e-6), 1e-3)
    t = time.time()
    state.beat_phase = ((t - state.last_beat_time) % period) / period

def neighbors(x, y):
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            xx, yy = x + dx, y + dy
            if 0 <= xx < GRID_W and 0 <= yy < GRID_H:
                out.append((xx, yy))
    return out

def ripple(state, x, y, ms=200):
    t = time.time() + (ms / 1000.0)
    state.highlight_until[grid_note(x, y)] = t
    for xx, yy in neighbors(x, y):
        state.highlight_until[grid_note(xx, yy)] = t + 0.1

# Global list of candidate devices
AUDIO_DEVICES = []
CURRENT_DEVICE_INDEX = 0

def scan_audio_devices():
    global AUDIO_DEVICES
    AUDIO_DEVICES = []
    print("\nScanning Audio Devices...")
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_input_channels'] > 0:
            AUDIO_DEVICES.append((i, dev['name']))
    print(f"Found {len(AUDIO_DEVICES)} input devices.")
    return AUDIO_DEVICES

def build_stream(device_idx=None):
    block = int(SAMPLE_RATE / FPS)
    
    if not AUDIO_DEVICES:
        scan_audio_devices()
        
    if device_idx is None:
        # Default to first or smart selection
        priorities = ["Stereo Mix", "VoiceMeeter Output", "CABLE Output", "Mix", "Analogue 1 + 2"]
        target = 0
        for i, (idx, name) in enumerate(AUDIO_DEVICES):
            for p in priorities:
                if p.lower() in name.lower():
                    target = i
                    break
            if target != 0: break
        global CURRENT_DEVICE_INDEX
        CURRENT_DEVICE_INDEX = target
        device_idx = AUDIO_DEVICES[target][0]

    dev_name = sd.query_devices(device_idx)['name']
    print(f"--> Opening Audio Device: [{device_idx}] {dev_name}")

    try:
        stream = sd.InputStream(
            device=device_idx,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=block,
            dtype='float32'
        )
        stream.start()
        return stream, block
    except Exception as e:
        print(f"Error opening {dev_name}: {e}")
        return None, None

def cycle_audio(state):
    global CURRENT_DEVICE_INDEX
    if not AUDIO_DEVICES:
        scan_audio_devices()
    
    CURRENT_DEVICE_INDEX = (CURRENT_DEVICE_INDEX + 1) % len(AUDIO_DEVICES)
    idx, name = AUDIO_DEVICES[CURRENT_DEVICE_INDEX]
    print(f"\n[SWITCHING AUDIO] -> [{idx}] {name}")
    
    # Signal main loop to restart stream
    state.req_new_stream = idx

def handle_press(state, volctl, key_id, is_cc=False):
    now = time.time()
    state.pressed_at[key_id] = now
    state.held.add(key_id)

    if is_cc:
        xy = decode_cc_xy(key_id)
        print(f"[INPUT] Control Change: {key_id} (Top Row)")
    else:
        xy = decode_grid_xy(key_id)
        print(f"[INPUT] Note On: {key_id} (Grid/Side)")

    if xy:
        x, y = xy
        
        if not is_cc:
            ripple(state, x, y, 200)
        
        # Top Row (y=8)
        if y == 8:
            if x == 0 and volctl and volctl.ready:
                state.hold_actions[key_id] = ("vol_down", now)
            elif x == 1 and volctl and volctl.ready:
                state.hold_actions[key_id] = ("vol_up", now)
            elif x == 2:
                state.mode = (state.mode - 1) % 8
                print(f"Mode: {state.mode}")
            elif x == 3:
                state.mode = (state.mode + 1) % 8
                print(f"Mode: {state.mode}")
            elif x == 4:
                state.enable_peaks = not state.enable_peaks
            elif x == 5:
                state.decay = max(0.1, state.decay - 0.05)
            elif x == 6:
                state.decay = min(0.99, state.decay + 0.05)
            elif x == 7:
                 if volctl and volctl.ready:
                    state.hold_actions[key_id] = ("mute_arm", now)

    # Check Side Buttons (Column 8 in 0-indexed logic? No, decode_grid_xy handles 0-7)
    # Side buttons on MK2 are 89, 79, 69... 19.
    # 89 is top right side button.
    if not is_cc and key_id == 89:
        print("Side Button 89 Pressed -> Cycling Audio")
        cycle_audio(state)

def handle_release(state, volctl, key_id):
    now = time.time()
    t0 = state.pressed_at.get(key_id, now)
    dur = now - t0
    
    if key_id in state.held:
        state.held.remove(key_id)
        
    if key_id in state.hold_actions:
        action, _ = state.hold_actions.pop(key_id)
        if action == "mute_arm" and volctl and volctl.ready and dur >= 0.4:
            volctl.toggle_mute()
            print(" -> Action: Mute Toggled")

def poll_input(state, volctl, inp):
    if not inp:
        return
    for msg in inp.iter_pending():
        if msg.type == "note_on" and msg.velocity > 0:
            handle_press(state, volctl, msg.note, is_cc=False)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            handle_release(state, volctl, msg.note)
        elif msg.type == "control_change":
            if msg.value > 0:
                handle_press(state, volctl, msg.control, is_cc=True)
            else:
                handle_release(state, volctl, msg.control)

def process_holds(state, volctl):
    if not volctl or not volctl.ready:
        return
    now = time.time()
    if now - state.last_hold_tick < 0.08:
        return
    state.last_hold_tick = now
    for key_id in list(state.held):
        if key_id not in state.hold_actions:
            continue
        action, _ = state.hold_actions[key_id]
        if action == "vol_down":
            volctl.change(-0.02)
        elif action == "vol_up":
            volctl.change(+0.02)


def draw(outp, state, levels):
    # --- 1. Smoothing & Gain ---
    state.smooth = np.maximum(levels * state.gain, state.smooth * state.decay)
    
    # Dynamics Expansion
    disp = np.power(np.clip(state.smooth * state.brightness, 0.0, 1.0), 3.0)
    
    now = time.time()
    
    # --- 2. Particle System & Waves ---
    # Particles
    for i in range(8): 
        # Bottom Spark (Lows)
        if disp[i] > 0.6 and np.random.random() < 0.05: 
             if state.mode == 1:
                h_len = (disp[i] * 4.0)
                y_tip = h_len
                if y_tip < 3.5:
                    c = gradient_color(1.0, state.mode, state.beat_phase, i, int(y_tip))
                    state.particles.append(Particle(i, y_tip, 0.2 + np.random.random()*0.2, c))
             else:
                val = max(disp[i], disp[i+8])
                h = int(val * GRID_H)
                if h >= 1 and h < 8:
                    c = gradient_color(1.0, state.mode, state.beat_phase, i, h)
                    state.particles.append(Particle(i, h, 0.2 + np.random.random() * 0.3, c))

        # Top Spark (Highs)
        if (state.mode == 1) and disp[i+8] > 0.6 and np.random.random() < 0.05:
            h_len = (disp[i+8] * 4.0)
            y_tip = 7.0 - h_len
            if y_tip > 3.5:
                c = gradient_color(1.0, state.mode, state.beat_phase, i, int(y_tip))
                state.particles.append(Particle(i, y_tip, -(0.2 + np.random.random()*0.2), c))

    # Update particles
    alive_particles = []
    for p in state.particles:
        p.y += p.vel_y
        p.life -= 0.05
        if 0 <= p.y < GRID_H and p.life > 0:
            alive_particles.append(p)
    state.particles = alive_particles
    
    # Update Waves
    alive_waves = []
    for w in state.waves:
        w.radius += w.speed
        w.life -= 0.05
        if w.life > 0:
            alive_waves.append(w)
    state.waves = alive_waves

    # --- 3. Rendering ---
    grid_buffer = {} 
    
    for x in range(GRID_W):
        # --- Mode 1: Dual Spectrum (Out-to-In) ---
        if state.mode == 1: 
            lvl_btm = float(disp[x])
            lvl_top = float(disp[x+8])
            
            bar_len_btm = lvl_btm * 4.0
            bar_len_top = lvl_top * 4.0
            
            for y in range(GRID_H):
                is_bottom = (y < int(bar_len_btm))
                is_top = (y >= (8 - int(bar_len_top)))
                
                if is_bottom:
                    grad_pos = y / 3.5
                    vel = gradient_color(grad_pos, state.mode, state.beat_phase, x, y)
                    grid_buffer[(x,y)] = vel
                elif is_top:
                    grad_pos = (7-y) / 3.5
                    vel = gradient_color(grad_pos, state.mode, state.beat_phase, x, y)
                    grid_buffer[(x,y)] = vel
                else:
                    grid_buffer[(x,y)] = 0
        
        # --- Mode 5: Diamond Splash (Volume Reactive - Smoothed) ---
        elif state.mode == 5:
             # Calculate target radius based on volume
             vol_level = np.max(disp) 
             target_radius = 0 if vol_level < 0.15 else (vol_level * 5.5)
             
             # Smooth the radius (Linear Interpolation)
             state.diamond_radius += (target_radius - state.diamond_radius) * 0.1
             radius = state.diamond_radius

             for y in range(GRID_H):
                # Manhattan Distance from Center (3.5, 3.5)
                dist = abs(x - 3.5) + abs(y - 3.5)
                
                vel = 0
                
                # Diamond Body
                if dist < radius:
                    # Gradient: Center = Bright, Edge = Dim
                    # Smoother gradient falloff
                    grad_pos = 1.0 - (dist / 6.0) 
                    vel = gradient_color(grad_pos * vol_level, state.mode, state.beat_phase, x, y)
                
                # Add Wave Effect
                wave_boost = 0
                for w in state.waves:
                    d_wave = abs(dist - w.radius)
                    if d_wave < 1.2: # Wider, softer waves
                        wave_boost += (1.0 - (d_wave/1.2)) * w.life * 0.6 
                
                if wave_boost > 0.1:
                    if vel == 0:
                        vel = 45 if wave_boost > 0.4 else 46 
                    else:
                        if wave_boost > 0.5:
                            vel = 37 # Ethereal Cyan
                
                grid_buffer[(x,y)] = vel

        # --- Mode 6: Diamond Implode (Inward) ---
        elif state.mode == 6:
             # Calculate target radius based on volume
             vol_level = np.max(disp) 
             target_radius = 0 if vol_level < 0.15 else (vol_level * 5.5)
             
             # Smooth the radius
             state.diamond_radius += (target_radius - state.diamond_radius) * 0.1
             radius = state.diamond_radius
             
             # Max distance from center to corner is ~7.0
             threshold_dist = 7.0 - radius

             for y in range(GRID_H):
                dist = abs(x - 3.5) + abs(y - 3.5)
                vel = 0
                
                # Inward Body
                if dist > threshold_dist:
                    if (7.0 - threshold_dist) > 0.01:
                        norm = (dist - threshold_dist) / (7.0 - threshold_dist)
                        grad_pos = 1.0 - norm
                    else:
                        grad_pos = 1.0
                        
                    vel = gradient_color(grad_pos * vol_level, state.mode, state.beat_phase, x, y)

                # Add Wave Effect (Inward waves)
                wave_boost = 0
                for w in state.waves:
                    d_wave = abs(dist - w.radius)
                    if d_wave < 1.2:
                        wave_boost += (1.0 - (d_wave/1.2)) * w.life * 0.6
                
                if wave_boost > 0.1:
                    if vel == 0:
                        vel = 45 if wave_boost > 0.4 else 46 
                    else:
                        if wave_boost > 0.5:
                            vel = 37 
                
                grid_buffer[(x,y)] = vel

        # --- Mode 7: The Oracle (Esoteric Prediction) ---
        elif state.mode == 7:
            # --- Audio Analysis ---
            bass_energy = np.mean(disp[0:4])
            mid_energy = np.mean(disp[4:10])
            high_energy = np.mean(disp[10:16])
            
            # --- 1. Organic Background (Bass/Mid Driven) ---
            t_speed = now * (state.bpm / 120.0) * 0.5
            breath = (0.5 + 0.5 * math.sin(2 * math.pi * state.beat_phase)) * bass_energy
            
            # --- 2. Sparkles (High Frequency Driven) ---
            num_sparkles = 0
            if high_energy > 0.4:
                num_sparkles = int(high_energy * 3)
            
            sparkle_locs = set()
            if num_sparkles > 0:
                for _ in range(num_sparkles):
                    rx, ry = np.random.randint(0, 8), np.random.randint(0, 8)
                    sparkle_locs.add((rx, ry))

            # --- 3. Main Grid Rendering ---
            for x in range(GRID_W):
                for y in range(GRID_H):
                    # Soft, large-scale noise
                    noise = 0.5 + 0.5 * math.sin(x * 0.25 + t_speed) * math.cos(y * 0.25 + t_speed * 0.8)
                    
                    # Target brightness
                    target = noise * 0.3 # Base dim glow
                    target += mid_energy * 0.6 * noise
                    target += breath * 0.4
                    
                    # Sparkles override
                    if (x, y) in sparkle_locs:
                        target = 1.0
                    
                    # Smooth the grid value
                    state.grid_smooth[x, y] += (target - state.grid_smooth[x, y]) * 0.1
                    val = state.grid_smooth[x, y]
                    
                    # Map to Palette
                    vel = 0
                    if val < 0.1: vel = 0
                    elif val < 0.3: vel = 49 # Deep Purple
                    elif val < 0.5: vel = 81 # Dim Zinc
                    elif val < 0.7: vel = 53 # Magenta
                    elif val < 0.9: vel = 37 # Teal
                    else: vel = 3 # White
                    
                    grid_buffer[(x,y)] = vel

        # --- Standard Modes (Bottom-Up) ---
        else:
            lvl = float(max(disp[x], disp[x+8]))
            h = int(lvl * GRID_H) # Use int truncation
            for y in range(GRID_H):
                if y < h:
                    vel = gradient_color(y / 7.0, state.mode, state.beat_phase, x, y)
                    grid_buffer[(x,y)] = vel
                else:
                    grid_buffer[(x,y)] = 0

    # --- Mode 7 Extra LEDs Pass ---
    if state.mode == 7:
        # Re-calc energies
        bass_energy = np.mean(disp[0:4])
        high_energy = np.mean(disp[10:16])
        
        # Side Buttons (Right) -> Bass Meter
        target_bass_h = bass_energy * 9.0
        for i in range(8):
            note = 19 + (i * 10)
            led_target = 1.0 if i < target_bass_h else 0.0
            state.side_smooth[i] += (led_target - state.side_smooth[i]) * 0.15
            s_val = state.side_smooth[i]
            
            vel = 0
            if s_val > 0.1:
                if i < 4: vel = 49
                elif i < 6: vel = 53
                else: vel = 5
            
            if vel > 0:
                outp.send(mido.Message('note_on', note=note, velocity=vel))
            else:
                 outp.send(mido.Message('note_on', note=note, velocity=0))
                 
        # Top Row (CC 104-111) -> Highs Meter
        target_high_w = high_energy * 9.0
        for x in range(8):
            cc = 104 + x
            led_target = 1.0 if x < target_high_w else 0.0
            state.top_smooth[x] += (led_target - state.top_smooth[x]) * 0.15
            t_val = state.top_smooth[x]
            
            vel = 0
            if t_val > 0.1:
                if x < 5: vel = 37
                else: vel = 3
            
            if vel > 0:
                outp.send(mido.Message('control_change', control=cc, value=vel))
            else:
                outp.send(mido.Message('control_change', control=cc, value=0))
                

    # Draw Particles
    for p in state.particles:
        px, py = int(p.x), int(p.y)
        if 0 <= px < GRID_W and 0 <= py < GRID_H:
            grid_buffer[(px, py)] = 3 if p.life > 0.5 else 1

    # Draw Peaks (Disable for Mode 5/6/7)
    if state.enable_peaks and state.mode not in [5, 6, 7]:
        for x in range(GRID_W):
            if state.mode == 1:
                # Dual Peaks
                lvl_btm = float(disp[x])
                lvl_top = float(disp[x+8])
                
                # Bottom Peak
                t_len_btm = lvl_btm * 4.0
                if t_len_btm > (state.peak_hold[x] / 10.0):
                    state.peak_hold[x] = int(t_len_btm * 10)
                    state.peak_decay_ctr[x] = 0
                else:
                    state.peak_decay_ctr[x] += 1
                    if state.peak_decay_ctr[x] >= 4:
                        state.peak_hold[x] = max(0, state.peak_hold[x] - 1)
                        state.peak_decay_ctr[x] = 0
                
                # Top Peak
                t_len_top = lvl_top * 4.0
                if t_len_top > (state.peak_hold[x+8] / 10.0):
                    state.peak_hold[x+8] = int(t_len_top * 10)
                    state.peak_decay_ctr[x+8] = 0
                else:
                    state.peak_decay_ctr[x+8] += 1
                    if state.peak_decay_ctr[x+8] >= 4:
                        state.peak_hold[x+8] = max(0, state.peak_hold[x+8] - 1)
                        state.peak_decay_ctr[x+8] = 0

                # Draw
                y_btm = int(state.peak_hold[x] / 10.0)
                y_top = int(7.0 - (state.peak_hold[x+8] / 10.0))
                
                # Only draw peak if it's within the bar range (0-3 for bottom, 4-7 for top)
                if 0 <= y_btm <= 3: grid_buffer[(x, y_btm)] = 127
                if 4 <= y_top <= 7: grid_buffer[(x, y_top)] = 127
                
            else:
                # Standard Peak (Downmixed)
                lvl = float(max(disp[x], disp[x+8]))
                h = int(lvl * GRID_H)
                
                if h > state.peak_hold[x]:
                    state.peak_hold[x] = h
                    state.peak_decay_ctr[x] = 0
                else:
                    state.peak_decay_ctr[x] += 1
                    if state.peak_decay_ctr[x] >= 4:
                        state.peak_hold[x] = max(0, state.peak_hold[x] - 1)
                        state.peak_decay_ctr[x] = 0
                
                peak_y = state.peak_hold[x] - 1
                if 0 <= peak_y < GRID_H:
                    grid_buffer[(x, peak_y)] = 127

    # Send to Launchpad
    for (x, y), vel in grid_buffer.items():
        n = grid_note(x, y)
        if (n in state.highlight_until) and (now < state.highlight_until[n]):
            outp.send(mido.Message('note_on', note=n, velocity=3)) 
            continue
        outp.send(mido.Message('note_on', note=n, velocity=vel))

    # Mode 7 handles its own side/top updates above.
    # For other modes, we might want to clear them or use them for UI.
    if state.mode != 7:
        outp.send(mido.Message('control_change', control=104+2, value=21))
        outp.send(mido.Message('control_change', control=104+3, value=21))

def main():
    try:
        import mido.backends.rtmidi
        mido.set_backend('mido.backends.rtmidi')
    except Exception:
        pass
    outp, inp, out_name, in_name = open_ports()
    if not outp:
        print("No Launchpad MK2 output found.")
        return
    
    print(f"Connected to {out_name}")
    if inp:
        print(f"Listening on {in_name}")
    
    clear_all(outp)
    state = State()
    volctl = VolumeCtl()
    
    stream, q = build_stream()
    if not stream:
        print("Failed to open any audio stream.")
        return

    last_ports_check = time.time()
    
    print("Visualizer running... Press Ctrl+C to stop.")
    print("Controls:")
    print(" [Top 2/3] Mode  [Top 0/1] Volume")
    print(" [Side 89] CYCLE AUDIO DEVICE (Top Right Button)")
    
    try:
        while True:
            # Handle Stream Restart
            if state.req_new_stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                stream, q = build_stream(state.req_new_stream)
                state.req_new_stream = None
                if not stream:
                    print("Failed to switch stream.")
                    time.sleep(1)
                    continue

            data, _ = stream.read(q)
            if data.shape[1] > 1:
                mono = data.mean(axis=1).astype(np.float32, copy=False)
            else:
                mono = data.flatten().astype(np.float32, copy=False)
                
            bands = compute_bands(mono, state)
            update_tempo(state, mono)
            poll_input(state, volctl, inp)
            process_holds(state, volctl)
            draw(outp, state, bands)
            
            if time.time() - last_ports_check > 3.0:
                ok_out = any(PORT_HINT in n for n in mido.get_output_names())
                if not ok_out:
                    print("Launchpad disconnected!")
                    break
                last_ports_check = time.time()
            time.sleep(1.0 / FPS)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            clear_all(outp)
        except Exception:
            pass
        try:
            stream.stop(); stream.close()
        except Exception:
            pass
        try:
            outp.close()
        except Exception:
            pass
        try:
            if inp:
                inp.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
