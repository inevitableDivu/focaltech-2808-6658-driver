import usb.core
import usb.util

dev = usb.core.find(idVendor=0x2808, idProduct=0x6658)
dev.set_configuration()
usb.util.claim_interface(dev, 0)

def read_reg(reg):
    pkt = bytes([0x08, 0xF7, reg & 0xFF, 0x00, 0x00])
    dev.write(0x01, pkt, timeout=1000)
    res = dev.read(0x82, 1, timeout=1000)
    return res[0]

for r in [0x00, 0x01, 0x02, 0x03, 0x13, 0x80, 0x8E, 0x90, 0x9A, 0x9B, 0xC6]:
    val = read_reg(r)
    print(f"Reg 0x{r:02X} = 0x{val:02X} ({val})")

usb.util.release_interface(dev, 0)
