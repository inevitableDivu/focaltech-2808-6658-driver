import usb.core
import usb.util
import time
import sys

VID = 0x2808
PID = 0x6658

print(f"Connecting to FocalTech Sensor {VID:04x}:{PID:04x}...")
dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    print("Device not found!")
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

def send_cmd(cmd_idx):
    table = [
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
    dev.write(EP_OUT, table[cmd_idx], timeout=1000)

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

# Reset & wakeup
write_reg(0xC6, 0x00)
time.sleep(0.01)
send_cmd(9)
time.sleep(0.01)
send_cmd(10)
time.sleep(0.01)

# Enable FDT mode
write_reg(0x9A, 0x5A)

print("\n==========================================================")
print(">>> FINGER TOUCH REAL-TIME MONITOR (15 SECONDS) <<<")
print("TOUCH AND LIFT YOUR FINGER REPEATEDLY ON THE SENSOR NOW!")
print("==========================================================\n")

for i in range(1, 31):
    # Trigger FDT sense
    send_cmd(2)
    time.sleep(0.01)
    
    st_80 = read_reg(0x80)
    st_9b = read_reg(0x9B)
    r_1800 = read_16bit(0x1800)
    r_1801 = read_16bit(0x1801)
    r_1880 = read_16bit(0x1880)
    
    # Read touch delta bytes at 0xE8
    fdt_data = read_sram(0x00E8, 8)
    touch_vals = [(fdt_data[j] << 8) | fdt_data[j+1] for j in range(0, 8, 2)]
    
    touch_indicator = ">>> FINGER TOUCH DETECTED! <<<" if any(v > 10 for v in touch_vals) or st_80 != 0x50 else "Idle / No Touch"
    
    print(f"[{i:2d}/30] Reg80=0x{st_80:02X} 1800=0x{r_1800:04X} 1801=0x{r_1801:04X} 1880=0x{r_1880:04X} TouchDeltas={touch_vals} -> {touch_indicator}")
    time.sleep(0.4)

write_reg(0x9A, 0x00)
send_cmd(0)
usb.util.release_interface(dev, 0)
print("\nTest completed.")
