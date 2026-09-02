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
    # byte_len in bytes (e.g. 10240)
    words = byte_len // 2
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    words_hi = (words >> 8) & 0xFF
    words_lo = words & 0xFF
    pkt = bytes([0x06, 0xF9, addr_hi, addr_lo, words_hi, words_lo])
    dev.write(EP_OUT, pkt, timeout=1000)
    
    # Read response in chunks of 512 bytes
    buf = bytearray()
    remaining = byte_len
    while remaining > 0:
        chunk_size = min(remaining, 512)
        chunk = dev.read(EP_IN, chunk_size, timeout=2000)
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)

print("1. Initializing chip...")
# Chip reset / test
write_reg(0xC6, 0x00)
time.sleep(0.01)

# Check mode register
mode = read_16bit(0x1800)
print(f"Current mode register: 0x{mode:04X}")

# Set Image mode
print("2. Setting Image Scan Mode...")
# In fw9366_img_mode_init:
write_16bit(0x1801, 0xFCA7)
write_16bit(0x1800, 0x4FFE) # Trigger scan mode
time.sleep(0.05)

# Trigger scan:
print("3. Triggering scan...")
# In fw9366_trigger_scan (0x180008ce0):
cur_m = read_16bit(0x1800)
write_16bit(0x1800, cur_m | 0x0001)
time.sleep(0.05)

# Poll until ready
for i in range(20):
    st = read_16bit(0x1801)
    # print(f"  Poll status {i}: 0x{st:04X}")
    time.sleep(0.01)

print("4. Reading 10,240 bytes from FIFO 0x1A05...")
raw_data = read_fifo(0x1A05, 10240)
print(f"Read {len(raw_data)} bytes successfully!")

# Parse 80x64 16-bit pixels
pixels = []
for i in range(0, len(raw_data), 2):
    px = (raw_data[i] << 8) | raw_data[i+1]
    pixels.append(px)

arr = np.array(pixels, dtype=np.uint16).reshape((80, 64))
print(f"Raw frame stats: Min={arr.min()}, Max={arr.max()}, Mean={arr.mean():.1f}, Std={arr.std():.1f}")

# Normalize to 8-bit grayscale [0..255]
p_min = arr.min()
p_max = arr.max()
if p_max > p_min:
    norm_arr = ((arr - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
else:
    norm_arr = np.zeros((80, 64), dtype=np.uint8)

img = Image.fromarray(norm_arr, mode='L')
# Resize for easy viewing (e.g. 4x)
img_large = img.resize((256, 320), Image.Resampling.NEAREST)
img_large.save("fingerprint_test.png")
print("Saved fingerprint test image to 'fingerprint_test.png'!")

usb.util.release_interface(dev, 0)
