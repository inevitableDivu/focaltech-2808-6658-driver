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

def send_cmd(b):
    dev.write(EP_OUT, b, timeout=1000)

def write_reg(reg, val):
    dev.write(EP_OUT, bytes([0x09, 0xF6, reg & 0xFF, val & 0xFF]), timeout=1000)

def read_reg(reg):
    dev.write(EP_OUT, bytes([0x08, 0xF7, reg & 0xFF, 0x00, 0x00]), timeout=1000)
    res = dev.read(EP_IN, 1, timeout=1000)
    return res[0]

def write_16bit(addr, val):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    val_hi = (val >> 8) & 0xFF
    val_lo = val & 0xFF
    pkt = bytes([0x05, 0xFA, addr_hi, addr_lo, 0x00, 0x01, val_lo, val_hi])
    dev.write(EP_OUT, pkt, timeout=1000)

def full_chip_init():
    write_reg(0xC6, 0x00)
    time.sleep(0.01)
    send_cmd(bytes([0x5A, 0xA5, 0x00])) # AFE Wake
    time.sleep(0.01)
    send_cmd(bytes([0xA5, 0x5A, 0x00])) # AFE Ready
    time.sleep(0.01)
    
    # Configure Image Mode
    write_16bit(0x1801, 0xFCA7)
    write_16bit(0x1800, 0x4FFE)

def read_frame_matrix():
    # 1. Trigger image scan via Cmd 3
    send_cmd(bytes([0xC4, 0x3B, 0x00]))
    time.sleep(0.035)
    
    # 2. Read 10,240 bytes (5,120 words) from SRAM 0x0200 in 512-byte chunks
    buf = bytearray()
    for off in range(0, 10240, 512):
        cur_addr = 0x0200 + off
        addr_hi = ((cur_addr >> 8) | 0x80) & 0xFF
        addr_lo = cur_addr & 0xFF
        pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, 0x01, 0x00]) # 256 words = 512 bytes
        dev.write(EP_OUT, pkt, timeout=1000)
        chunk = dev.read(EP_IN, 512, timeout=1000)
        buf.extend(chunk)
    
    pixels = []
    for i in range(0, len(buf), 2):
        px = (buf[i] << 8) | buf[i+1]
        pixels.append(px)
    return np.array(pixels, dtype=np.uint16).reshape((80, 64)), bytes(buf)

full_chip_init()
print("Chip initialized.")
print("\n>>> LIVE SENSOR MONITOR (10 cycles) <<<")
print("Reading continuous frames from SRAM 0x0200...\n")

for cycle in range(1, 11):
    arr, raw = read_frame_matrix()
    p_min, p_max, p_mean, p_std = arr.min(), arr.max(), arr.mean(), arr.std()
    unique_vals = len(np.unique(arr))
    p2, p98 = np.percentile(arr, 2), np.percentile(arr, 98)
    print(f"[{cycle:2d}/10] Min={p_min:4d} Max={p_max:4d} p2={p2:5.1f} p98={p98:5.1f} Mean={p_mean:6.1f} Std={p_std:5.1f} Unique={unique_vals:3d}")
    time.sleep(0.1)

# Reset to Idle
send_cmd(bytes([0xC0, 0x3F, 0x00]))
usb.util.release_interface(dev, 0)
print("\nCompleted successfully.")
