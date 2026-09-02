import usb.core
import usb.util
import time
from PIL import Image
import numpy as np
import sys

VID = 0x2808
PID = 0x6658

print(f"Connecting to FocalTech Sensor {VID:04x}:{PID:04x}...")
dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    print("Device not found! Please check permissions.")
    sys.exit(1)

try:
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
except Exception:
    pass

dev.set_configuration()
usb.util.claim_interface(dev, 0)

EP_OUT = 0x01
EP_IN  = 0x82

CMD_TABLE = [
    bytes([0xC0, 0x3F, 0x00]), # 0: Reset / Idle
    bytes([0xC1, 0x3E, 0x00]), # 1
    bytes([0xC2, 0x3D, 0x00]), # 2
    bytes([0xC4, 0x3B, 0x00]), # 3: Trigger Capture
    bytes([0xC8, 0x37, 0x00]), # 4
    bytes([0xD8, 0x27, 0x00]), # 5
    bytes([0xD1, 0x2E, 0x00]), # 6
    bytes([0xD2, 0x2D, 0x00]), # 7
    bytes([0xD4, 0x2B, 0x00]), # 8
    bytes([0x5A, 0xA5, 0x00]), # 9: AFE Wakeup
    bytes([0xA5, 0x5A, 0x00]), # 10: AFE Ready
    bytes([0x70]),             # 11
]

def send_cmd(cmd_idx):
    pkt = CMD_TABLE[cmd_idx]
    dev.write(EP_OUT, pkt, timeout=1000)

def write_reg(reg, val):
    pkt = bytes([0x09, 0xF6, reg & 0xFF, val & 0xFF])
    dev.write(EP_OUT, pkt, timeout=1000)

def read_reg(reg):
    pkt = bytes([0x08, 0xF7, reg & 0xFF, 0x00, 0x00])
    dev.write(EP_OUT, pkt, timeout=1000)
    res = dev.read(EP_IN, 1, timeout=1000)
    return res[0]

def write_16bit(addr, val):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    val_hi = (val >> 8) & 0xFF
    val_lo = val & 0xFF
    pkt = bytes([0x05, 0xFA, addr_hi, addr_lo, 0x00, 0x01, val_lo, val_hi])
    dev.write(EP_OUT, pkt, timeout=1000)

def read_16bit(addr):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, 0x00, 0x01])
    dev.write(EP_OUT, pkt, timeout=1000)
    res = dev.read(EP_IN, 2, timeout=1000)
    return (res[0] << 8) | res[1]

def read_fifo(addr, byte_len):
    words = byte_len // 2
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    words_hi = (words >> 8) & 0xFF
    words_lo = words & 0xFF
    pkt = bytes([0x06, 0xF9, addr_hi, addr_lo, words_hi, words_lo])
    dev.write(EP_OUT, pkt, timeout=1000)
    
    buf = bytearray()
    remaining = byte_len
    while remaining > 0:
        chunk_size = min(remaining, 512)
        chunk = dev.read(EP_IN, chunk_size, timeout=2000)
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)

def modify_bits(val, bit_low, bit_high, new_bits):
    mask = ((1 << (bit_high - bit_low + 1)) - 1) << bit_low
    return (val & ~mask) | ((new_bits << bit_low) & mask)

def setup_full_afe():
    print("Resetting sensor...")
    write_reg(0xC6, 0x00)
    time.sleep(0.01)
    
    send_cmd(9) # Wakeup
    time.sleep(0.01)
    st = read_reg(0x80)
    print(f"AFE Wakeup status: 0x{st:02X}")
    
    send_cmd(10) # Lock
    time.sleep(0.01)
    
    # Configure AFE registers based on fw9366_img_mode_init
    # 1. 0x1801
    write_16bit(0x1801, 0xFCA7)
    
    # 2. 0x1800
    write_16bit(0x1800, 0x4FFE)
    
    # 3. 0x1804 (Timing & reference clock)
    r_1804 = read_16bit(0x1804)
    r_1804 = modify_bits(r_1804, 6, 10, 0x0F)
    r_1804 = modify_bits(r_1804, 3, 3, 1)
    r_1804 = modify_bits(r_1804, 13, 13, 1)
    write_16bit(0x1804, r_1804)
    
    # 4. 0x1807 (ADC bias & filter)
    r_1807 = read_16bit(0x1807)
    r_1807 = modify_bits(r_1807, 5, 13, 1)
    r_1807 = modify_bits(r_1807, 4, 4, 1)
    write_16bit(0x1807, r_1807)
    
    # 5. 0x1806 & 0x180A (Gain & Offset)
    r_1806 = read_16bit(0x1806)
    r_1806 = modify_bits(r_1806, 7, 13, 9)
    write_16bit(0x1806, r_1806)
    
    r_180A = read_16bit(0x180A)
    r_180A = modify_bits(r_180A, 7, 13, 9)
    write_16bit(0x180A, r_180A)
    
    # 6. 0x1887
    write_16bit(0x1887, 0x0000)
    
    # 7. 0x1805
    r_1805 = read_16bit(0x1805)
    r_1805 = modify_bits(r_1805, 4, 4, 1)
    r_1805 = modify_bits(r_1805, 7, 7, 1)
    write_16bit(0x1805, r_1805)
    
    # 8. 0x1811
    r_1811 = read_16bit(0x1811)
    r_1811 = modify_bits(r_1811, 9, 9, 1)
    write_16bit(0x1811, r_1811)
    
    # 9. 0x1883 AFE enable bits
    r_1883 = read_16bit(0x1883)
    r_1883 |= (1 << 5) | (1 << 6)
    write_16bit(0x1883, r_1883)
    
    # 10. Scan rate (reg 0x8E)
    scan_rate = 0x64 * 10000 // 4096
    write_reg(0x8E, scan_rate & 0xFF)
    
    # 11. Timer integration (reg 0x90..0x92)
    write_reg(0x90, 0x00)
    write_reg(0x91, (2000 >> 8) & 0xFF)
    write_reg(0x92, 2000 & 0xFF)
    write_reg(0x90, 0x01)
    
    print("Full AFE initialization complete!")

def scan_frame():
    send_cmd(3) # Trigger
    for _ in range(50):
        st = read_reg(0x80)
        if st == 0x54:
            break
        time.sleep(0.002)
    
    raw = read_fifo(0x1A05, 10240)
    pixels = []
    for i in range(0, len(raw), 2):
        px = (raw[i] << 8) | raw[i+1]
        pixels.append(px)
    return np.array(pixels, dtype=np.uint16).reshape((80, 64))

setup_full_afe()

print("\n========================================================")
print(">>> FINGERPRINT DETECTION TEST READY <<<")
print("We will scan 20 frames over the next 6 seconds.")
print("PLEASE PLACE AND HOLD YOUR FINGER FIRMLY ON THE SENSOR NOW!")
print("========================================================\n")

frames = []
for i in range(1, 21):
    arr = scan_frame()
    p_min, p_max, p_mean, p_std = arr.min(), arr.max(), arr.mean(), arr.std()
    status = "FINGER DETECTED!" if p_std > 5.0 or (p_max - p_min) > 20 else "No Finger / Idle"
    print(f"[{i:2d}/20] Min={p_min:4d} Max={p_max:4d} Mean={p_mean:6.1f} Std={p_std:5.1f}  --> {status}")
    frames.append(arr)
    time.sleep(0.3)

# Find frame with largest variation/contrast
best_frame = max(frames, key=lambda a: a.std())
p_min, p_max = best_frame.min(), best_frame.max()
if p_max > p_min:
    norm = ((best_frame - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
else:
    norm = (best_frame % 256).astype(np.uint8)

img = Image.fromarray(norm, mode='L').resize((256, 320), Image.Resampling.BILINEAR)
img.save("live_fingerprint_best.png")
print("\nSaved best fingerprint capture to: 'live_fingerprint_best.png'")

send_cmd(0)
usb.util.release_interface(dev, 0)
