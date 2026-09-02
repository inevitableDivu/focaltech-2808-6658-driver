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

def init_sensor():
    write_reg(0xC6, 0x00)
    time.sleep(0.01)
    send_cmd(9)
    time.sleep(0.01)
    send_cmd(10)
    time.sleep(0.01)
    write_16bit(0x1801, 0xFCA7)
    write_16bit(0x1800, 0x4FFE)
    time.sleep(0.01)

def scan_frame():
    send_cmd(3)
    time.sleep(0.005)
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

init_sensor()
print("Sensor initialized successfully!")
print("Starting continuous live scanner (10 frames)...")

for frame_no in range(1, 11):
    arr = scan_frame()
    p_min, p_max, p_mean, p_std = arr.min(), arr.max(), arr.mean(), arr.std()
    print(f"Frame #{frame_no:02d}: Min={p_min:4d}, Max={p_max:4d}, Mean={p_mean:6.1f}, Std={p_std:5.1f}")
    
    # Normalize and save frame
    if p_max > p_min:
        norm = ((arr - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
    else:
        norm = (arr % 256).astype(np.uint8)
    
    img = Image.fromarray(norm, mode='L').resize((256, 320), Image.Resampling.NEAREST)
    img.save(f"frame_{frame_no:02d}.png")
    time.sleep(0.2)

send_cmd(0)
usb.util.release_interface(dev, 0)
print("Saved frames frame_01.png .. frame_10.png")
