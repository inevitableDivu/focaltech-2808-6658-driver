import usb.core
import usb.util

dev = usb.core.find(idVendor=0x2808, idProduct=0x6658)
dev.set_configuration()
usb.util.claim_interface(dev, 0)

def read_sram(addr, byte_len):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    words = byte_len // 2
    pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, (words >> 8) & 0xFF, words & 0xFF])
    dev.write(0x01, pkt, timeout=1000)
    res = dev.read(0x82, byte_len, timeout=1000)
    return list(res)

for addr in [0x00, 0xB0, 0xB8, 0xE0, 0xE8, 0x1800, 0x1880]:
    try:
        data = read_sram(addr, 18)
        print(f"SRAM 0x{addr:04X} ({len(data)} bytes): {[hex(b) for b in data]}")
    except Exception as e:
        print(f"SRAM 0x{addr:04X} error: {e}")

usb.util.release_interface(dev, 0)
