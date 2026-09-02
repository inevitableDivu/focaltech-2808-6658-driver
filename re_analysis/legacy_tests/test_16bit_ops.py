import usb.core
import usb.util
import time

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

def read_16bit(addr):
    # addr is 16-bit
    # Let's inspect the exact byte format:
    # Opcode 0x04, 0xFB
    # Addr bytes: (addr >> 8) | 0x80, addr & 0xFF
    # Len: 0x00, 0x01 (or 0x01, 0x00)
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, 0x00, 0x01])
    dev.write(EP_OUT, pkt, timeout=1000)
    res = dev.read(EP_IN, 2, timeout=1000)
    val = (res[0] << 8) | res[1]
    return val, list(res)

def write_16bit(addr, val):
    addr_hi = ((addr >> 8) | 0x80) & 0xFF
    addr_lo = addr & 0xFF
    val_hi = (val >> 8) & 0xFF
    val_lo = val & 0xFF
    pkt = bytes([0x05, 0xFA, addr_hi, addr_lo, 0x00, 0x01, val_lo, val_hi])
    dev.write(EP_OUT, pkt, timeout=1000)

print("Testing 16-bit address reads:")
for test_addr in [0x1800, 0x1801, 0x1805, 0x1808, 0x180D, 0x0000, 0x0002]:
    try:
        val, raw = read_16bit(test_addr)
        print(f"  Addr 0x{test_addr:04X}: val=0x{val:04X} raw={raw}")
    except Exception as e:
        print(f"  Addr 0x{test_addr:04X}: error={e}")

usb.util.release_interface(dev, 0)
