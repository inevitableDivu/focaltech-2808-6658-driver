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
    bytes([0xC2, 0x3D, 0x00]), # 2: FDT scan trigger
    bytes([0xC4, 0x3B, 0x00]), # 3: Image scan trigger
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
    dev.write(EP_OUT, CMD_TABLE[cmd_idx], timeout=1000)

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

def read_sram(addr, byte_len):
    words = byte_len // 2
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    words_hi = (words >> 8) & 0xFF
    words_lo = words & 0xFF
    pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, words_hi, words_lo])
    dev.write(EP_OUT, pkt, timeout=1000)
    res = dev.read(EP_IN, byte_len, timeout=1000)
    return list(res)

print("1. Initializing Sensor...")
write_reg(0xC6, 0x00)
time.sleep(0.01)
send_cmd(9)
time.sleep(0.01)
send_cmd(10)
time.sleep(0.01)

# Enable FDT sensing mode
write_reg(0x9A, 0x5A)

print("\n==========================================================")
print(">>> WAITING FOR YOUR FINGER TOUCH... <<<")
print("PLACE YOUR FINGER ON THE SENSOR NOW TO SCAN!")
print("==========================================================\n")

touch_detected = False
for check in range(60): # 15 seconds window
    send_cmd(2) # sense touch
    time.sleep(0.01)
    
    st_80 = read_reg(0x80)
    fdt_data = read_sram(0x00E8, 8)
    touch_vals = [(fdt_data[j] << 8) | fdt_data[j+1] for j in range(0, 8, 2)]
    
    if st_80 == 0x54 or any(v > 50 for v in touch_vals):
        print(f"✅ FINGER TOUCH DETECTED! (Status=0x{st_80:02X}, TouchDeltas={touch_vals})")
        touch_detected = True
        break
    
    time.sleep(0.2)

if not touch_detected:
    print("Timeout waiting for finger touch. Proceeding to trigger scan anyway...")

# Switch to Image Mode
print("2. Switching to Image Mode & Triggering High-Resolution Scan...")
write_reg(0x9A, 0x00) # Disable FDT
write_16bit(0x1801, 0xFCA7)
write_16bit(0x1800, 0x4FFE)
time.sleep(0.01)

# Trigger scan
send_cmd(3)
time.sleep(0.01)

for _ in range(50):
    st = read_reg(0x80)
    if st == 0x54:
        break
    time.sleep(0.002)

print(f"3. Scan complete (status 0x{st:02X}). Reading 10,240 bytes frame buffer from FIFO...")
raw_data = read_fifo(0x1A05, 10240)

pixels = []
for i in range(0, len(raw_data), 2):
    px = (raw_data[i] << 8) | raw_data[i+1]
    pixels.append(px)

arr = np.array(pixels, dtype=np.uint16).reshape((80, 64))
p_min, p_max, p_mean, p_std = arr.min(), arr.max(), arr.mean(), arr.std()
print(f"4. Frame Statistics: Min={p_min}, Max={p_max}, Mean={p_mean:.1f}, Std={p_std:.1f}")

# Normalize to 8-bit grayscale
if p_max > p_min:
    norm = ((arr - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
else:
    norm = (arr % 256).astype(np.uint8)

img = Image.fromarray(norm, mode='L')
img_upscaled = img.resize((320, 400), Image.Resampling.BILINEAR)

out_file = "/home/inevitable/focaltech-2808-6658-driver/my_fingerprint.png"
img_upscaled.save(out_file)
print(f"🎉 Fingerprint image saved successfully to: {out_file}!")

# Reset to Idle
send_cmd(0)
usb.util.release_interface(dev, 0)
