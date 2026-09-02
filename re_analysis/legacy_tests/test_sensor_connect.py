import usb.core
import usb.util
import time

VID = 0x2808
PID = 0x6658

print(f"Searching for USB device {VID:04x}:{PID:04x}...")
dev = usb.core.find(idVendor=VID, idProduct=PID)

if dev is None:
    print("Device not found! Check permissions or connection.")
    exit(1)

print("Device found!")
print(f"Manufacturer: {dev.manufacturer}")
print(f"Product:      {dev.product}")

# Check if kernel driver is active (if any) and detach
try:
    if dev.is_kernel_driver_active(0):
        print("Detaching kernel driver on interface 0...")
        dev.detach_kernel_driver(0)
except Exception as e:
    print(f"Kernel driver check: {e}")

try:
    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    print("Successfully claimed interface 0!")
except Exception as e:
    print(f"Error claiming interface: {e}")
    exit(1)

# Endpoint 1 OUT: 0x01
# Endpoint 2 IN:  0x82
EP_OUT = 0x01
EP_IN  = 0x82

def write_reg(reg, val):
    # Opcode 0x09, 0xF6, reg, val
    pkt = bytes([0x09, 0xF6, reg & 0xFF, val & 0xFF])
    dev.write(EP_OUT, pkt, timeout=1000)

def read_reg(reg):
    # Opcode 0x08, 0xF7, reg, 0, 0
    pkt = bytes([0x08, 0xF7, reg & 0xFF, 0x00, 0x00])
    dev.write(EP_OUT, pkt, timeout=1000)
    res = dev.read(EP_IN, 1, timeout=1000)
    return res[0]

def read_chip_id():
    # Let's test reading reg 0xC6 or reg 0x00 / chip ID registers
    # In fw9366_init_chip, it checked reg 0xC6
    print("Testing register write & read on reg 0xC6...")
    try:
        write_reg(0xC6, 0x5A)
        time.sleep(0.005)
        val = read_reg(0xC6)
        print(f"Wrote 0x5A to reg 0xC6, Read back: 0x{val:02X}")
        
        # Test reading common FocalTech chip ID registers (0x00, 0x01, 0xA0, etc.)
        for r in [0x00, 0x01, 0x02, 0x03, 0xC0, 0xC6, 0xD0, 0xE0, 0xF0]:
            try:
                v = read_reg(r)
                print(f"  Reg 0x{r:02X} = 0x{v:02X}")
            except Exception as e:
                print(f"  Reg 0x{r:02X} read error: {e}")
    except Exception as e:
        print(f"Communication error: {e}")

read_chip_id()

usb.util.release_interface(dev, 0)
print("Done test.")

