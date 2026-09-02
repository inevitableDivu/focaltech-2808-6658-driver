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

def write_16bit(addr, val):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    val_hi = (val >> 8) & 0xFF
    val_lo = val & 0xFF
    pkt = bytes([0x05, 0xFA, addr_hi, addr_lo, 0x00, 0x01, val_lo, val_hi])
    dev.write(EP_OUT, pkt, timeout=1000)

def read_sram_bulk(addr, byte_len):
    buf = bytearray()
    chunk_size = 512 # read in 512-byte chunks (256 words)
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

print("1. Waking up AFE & Triggering Scan...")
send_cmd(bytes([0x5A, 0xA5, 0x00])) # AFE Wakeup
send_cmd(bytes([0xA5, 0x5A, 0x00])) # AFE Lock
write_16bit(0x1801, 0xFCA7)
write_16bit(0x1800, 0x4FFE)
send_cmd(bytes([0xC4, 0x3B, 0x00])) # Trigger scan
time.sleep(0.05)

print("2. Reading 10,240 bytes from SRAM 0x0000...")
raw_data = read_sram_bulk(0x0000, 10240)
print(f"Read {len(raw_data)} bytes successfully!")

pixels = []
for i in range(0, len(raw_data), 2):
    px = (raw_data[i] << 8) | raw_data[i+1]
    pixels.append(px)

arr = np.array(pixels, dtype=np.uint16).reshape((80, 64))
p_min, p_max, p_mean, p_std = arr.min(), arr.max(), arr.mean(), arr.std()
print(f"Stats: Min={p_min}, Max={p_max}, Mean={p_mean:.1f}, Std={p_std:.1f}, Unique={len(np.unique(arr))}")

# Normalize to 8-bit grayscale
norm = ((arr - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
img = Image.fromarray(norm, mode='L')
img_large = img.resize((320, 400), Image.Resampling.BILINEAR)

out_file = "/home/inevitable/focaltech-2808-6658-driver/real_fingerprint_frame.png"
img_large.save(out_file)
print(f"Saved real fingerprint image to: {out_file}!")

send_cmd(bytes([0xC0, 0x3F, 0x00])) # Idle
usb.util.release_interface(dev, 0)
