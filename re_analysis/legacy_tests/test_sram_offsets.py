import usb.core
import usb.util
import time

dev = usb.core.find(idVendor=0x2808, idProduct=0x6658)
dev.set_configuration()
usb.util.claim_interface(dev, 0)

def send_cmd(cmd_bytes):
    dev.write(0x01, cmd_bytes, timeout=1000)

def read_fifo(addr, words):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    pkt = bytes([0x06, 0xF9, addr_hi, addr_lo, (words >> 8) & 0xFF, words & 0xFF])
    dev.write(0x01, pkt, timeout=1000)
    return list(dev.read(0x82, words * 2, timeout=1000))

def read_sram(addr, words):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, (words >> 8) & 0xFF, words & 0xFF])
    dev.write(0x01, pkt, timeout=1000)
    return list(dev.read(0x82, words * 2, timeout=1000))

# Wakeup & trigger scan
send_cmd(bytes([0x5A, 0xA5, 0x00]))
send_cmd(bytes([0xA5, 0x5A, 0x00]))
send_cmd(bytes([0xC4, 0x3B, 0x00]))
time.sleep(0.05)

print("Checking SRAM & FIFO at various base addresses after scan:")
for addr in [0x0000, 0x0100, 0x1000, 0x1800, 0x1900, 0x1A00, 0x1A01, 0x1A05, 0x2000]:
    try:
        sram_res = read_sram(addr, 16)
        fifo_res = read_fifo(addr, 16)
        print(f"Addr 0x{addr:04X}: SRAM={[hex(b) for b in sram_res[:8]]} | FIFO={[hex(b) for b in fifo_res[:8]]}")
    except Exception as e:
        print(f"Addr 0x{addr:04X} error: {e}")

send_cmd(bytes([0xC0, 0x3F, 0x00]))
usb.util.release_interface(dev, 0)
