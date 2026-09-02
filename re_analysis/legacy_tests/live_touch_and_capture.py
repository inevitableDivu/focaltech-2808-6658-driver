import usb.core
import usb.util
import time
from PIL import Image
import numpy as np

dev = usb.core.find(idVendor=0x2808, idProduct=0x6658)
dev.set_configuration()
usb.util.claim_interface(dev, 0)

EP_OUT = 0x01
EP_IN  = 0x82

def send_cmd(cmd_bytes):
    dev.write(EP_OUT, cmd_bytes, timeout=1000)

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

def read_sram(addr, byte_len):
    words = byte_len // 2
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    words_hi = (words >> 8) & 0xFF
    words_lo = words & 0xFF
    pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, words_hi, words_lo])
    dev.write(EP_OUT, pkt, timeout=1000)
    return list(dev.read(EP_IN, byte_len, timeout=1000))

def read_sram_bulk(addr, byte_len):
    buf = bytearray()
    chunk_size = 512
    words_chunk = chunk_size // 2
    for offset in range(0, byte_len, chunk_size):
        cur_addr = addr + offset
        addr_hi = ((cur_addr >> 8) | 0x80) & 0xFF
        addr_lo = cur_addr & 0xFF
        pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, (words_chunk >> 8) & 0xFF, words_chunk & 0xFF])
        dev.write(EP_OUT, pkt, timeout=1000)
        chunk = dev.read(EP_IN, chunk_size, timeout=1000)
        buf.extend(chunk)
    return bytes(buf)

def grab_fingerprint():
    # 1. Wakeup
    send_cmd(bytes([0x5A, 0xA5, 0x00]))
    send_cmd(bytes([0xA5, 0x5A, 0x00]))
    
    # 2. Config Image Mode
    write_16bit(0x1801, 0xFCA7)
    write_16bit(0x1800, 0x4FFE)
    
    # 3. Trigger Scan
    send_cmd(bytes([0xC4, 0x3B, 0x00]))
    time.sleep(0.04)
    
    # 4. Read Image Buffer from SRAM 0x0000
    raw_data = read_sram_bulk(0x0000, 10240)
    
    pixels = []
    for i in range(0, len(raw_data), 2):
        px = (raw_data[i] << 8) | raw_data[i+1]
        pixels.append(px)
    return np.array(pixels, dtype=np.uint16).reshape((80, 64))

print("\n========================================================")
print(">>> FINGERPRINT CAPTURE ENGINE ACTIVE <<<")
print("Place your finger on the sensor. We will capture 3 frames!")
print("========================================================\n")

for f in range(1, 4):
    print(f"Scanning Frame #{f} in 1 second... Place finger firmly!")
    time.sleep(1.0)
    
    arr = grab_fingerprint()
    p_min, p_max, p_mean, p_std = arr.min(), arr.max(), arr.mean(), arr.std()
    unique = len(np.unique(arr))
    print(f"  Frame #{f}: Min={p_min}, Max={p_max}, Mean={p_mean:.1f}, Std={p_std:.1f}, Unique Levels={unique}")
    
    # Contrast normalization
    # Clip extreme outliers (0.5% and 99.5%)
    p_low = np.percentile(arr, 1)
    p_high = np.percentile(arr, 99)
    if p_high > p_low:
        clipped = np.clip(arr, p_low, p_high)
        norm = ((clipped - p_low) / (p_high - p_low) * 255.0).astype(np.uint8)
    else:
        norm = ((arr - p_min) / max(1, p_max - p_min) * 255.0).astype(np.uint8)
        
    img = Image.fromarray(norm, mode='L')
    img_large = img.resize((320, 400), Image.Resampling.BILINEAR)
    img_large.save(f"/home/inevitable/focaltech-2808-6658-driver/fingerprint_scan_{f}.png")
    print(f"  --> Saved to 'fingerprint_scan_{f}.png'!\n")

send_cmd(bytes([0xC0, 0x3F, 0x00])) # Idle
usb.util.release_interface(dev, 0)
print("Capture complete! All fingerprint frames saved.")
