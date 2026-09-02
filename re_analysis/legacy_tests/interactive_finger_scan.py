import usb.core
import usb.util
import time
from PIL import Image
import numpy as np

VID = 0x2808
PID = 0x6658

dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    print("Device not found!")
    exit(1)

try:
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
except Exception:
    pass

dev.set_configuration()
usb.util.claim_interface(dev, 0)

EP_OUT = 0x01
EP_IN  = 0x82

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

def capture_single_frame():
    # 1. Image Mode configuration
    write_16bit(0x1801, 0xFCA7)
    write_16bit(0x1800, 0x4FFE)
    time.sleep(0.005)
    
    # 2. Trigger scan
    cur_m = read_16bit(0x1800)
    write_16bit(0x1800, cur_m | 0x0001)
    
    # 3. Poll for status 0x54 on reg 0x80 (up to 100ms)
    t0 = time.time()
    for _ in range(50):
        st = read_reg(0x80)
        if st == 0x54:
            break
        time.sleep(0.002)
    # print(f"Scan finished in {(time.time()-t0)*1000:.1f}ms, reg 0x80 = 0x{st:02X}")
    
    # 4. Read FIFO 0x1A05
    raw_data = read_fifo(0x1A05, 10240)
    
    pixels = []
    for i in range(0, len(raw_data), 2):
        px = (raw_data[i] << 8) | raw_data[i+1]
        pixels.append(px)
    
    arr = np.array(pixels, dtype=np.uint16).reshape((80, 64))
    return arr

print("Reading 5 consecutive frames...")
for f in range(5):
    arr = capture_single_frame()
    print(f"Frame {f+1}: min={arr.min()}, max={arr.max()}, mean={arr.mean():.1f}, std={arr.std():.1f}")
    time.sleep(0.1)

usb.util.release_interface(dev, 0)
print("Complete.")
