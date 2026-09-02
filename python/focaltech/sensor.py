"""
FocalTech FW9366 (2808:6658) Open-Source Driver Implementation
"""

import time
import usb.core
import usb.util
import numpy as np

VID = 0x2808
PID = 0x6658

CMD_RESET     = bytes([0xC0, 0x3F, 0x00])
CMD_FDT_SENSE = bytes([0xC2, 0x3D, 0x00])
CMD_SCAN_IMG  = bytes([0xC4, 0x3B, 0x00])
CMD_AFE_WAKE  = bytes([0x5A, 0xA5, 0x00])
CMD_AFE_LOCK  = bytes([0xA5, 0x5A, 0x00])


class FocalTechSensor:
    def __init__(self, vid=VID, pid=PID):
        self.vid = vid
        self.pid = pid
        self.dev = None
        self.ep_out = 0x01
        self.ep_in  = 0x82

    def connect(self):
        self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)
        if self.dev is None:
            raise RuntimeError(f"Device {self.vid:04x}:{self.pid:04x} not found.")

        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except Exception:
            pass

        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)

    def disconnect(self):
        if self.dev:
            try:
                self.send_cmd(CMD_RESET)
                usb.util.release_interface(self.dev, 0)
            except Exception:
                pass
            self.dev = None

    def send_cmd(self, cmd_bytes):
        self.dev.write(self.ep_out, cmd_bytes, timeout=1000)

    def write_reg(self, reg, val):
        pkt = bytes([0x09, 0xF6, reg & 0xFF, val & 0xFF])
        self.dev.write(self.ep_out, pkt, timeout=1000)

    def read_reg(self, reg):
        pkt = bytes([0x08, 0xF7, reg & 0xFF, 0x00, 0x00])
        self.dev.write(self.ep_out, pkt, timeout=1000)
        res = self.dev.read(self.ep_in, 1, timeout=1000)
        return res[0]

    def write_16bit(self, addr, val):
        addr_hi = ((addr >> 8) | 0x80) & 0xFF
        addr_lo = addr & 0xFF
        val_hi = (val >> 8) & 0xFF
        val_lo = val & 0xFF
        pkt = bytes([0x05, 0xFA, addr_hi, addr_lo, 0x00, 0x01, val_lo, val_hi])
        self.dev.write(self.ep_out, pkt, timeout=1000)

    def read_16bit(self, addr):
        addr_hi = ((addr >> 8) | 0x80) & 0xFF
        addr_lo = addr & 0xFF
        pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, 0x00, 0x01])
        self.dev.write(self.ep_out, pkt, timeout=1000)
        res = self.dev.read(self.ep_in, 2, timeout=1000)
        return (res[0] << 8) | res[1]

    def read_sram(self, addr, byte_len):
        words = byte_len // 2
        addr_hi = ((addr >> 8) | 0x80) & 0xFF
        addr_lo = addr & 0xFF
        words_hi = (words >> 8) & 0xFF
        words_lo = words & 0xFF
        pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, words_hi, words_lo])
        self.dev.write(self.ep_out, pkt, timeout=1000)
        return list(self.dev.read(self.ep_in, byte_len, timeout=1000))

    def read_sram_bulk(self, addr, byte_len):
        buf = bytearray()
        chunk_size = 512
        words_chunk = chunk_size // 2
        for offset in range(0, byte_len, chunk_size):
            cur_addr = addr + offset
            addr_hi = ((cur_addr >> 8) | 0x80) & 0xFF
            addr_lo = cur_addr & 0xFF
            pkt = bytes([0x04, 0xFB, addr_hi, addr_lo, (words_chunk >> 8) & 0xFF, words_chunk & 0xFF])
            self.dev.write(self.ep_out, pkt, timeout=1000)
            chunk = self.dev.read(self.ep_in, chunk_size, timeout=1000)
            buf.extend(chunk)
        return bytes(buf)

    def init_chip(self):
        self.write_reg(0xC6, 0x00)
        time.sleep(0.01)
        self.send_cmd(CMD_AFE_WAKE)
        time.sleep(0.01)
        self.send_cmd(CMD_AFE_LOCK)
        time.sleep(0.01)

    def enable_finger_detect(self):
        self.write_reg(0x9A, 0x5A)

    def disable_finger_detect(self):
        self.write_reg(0x9A, 0x00)

    def is_finger_present(self):
        self.send_cmd(CMD_FDT_SENSE)
        time.sleep(0.005)
        st_80 = self.read_reg(0x80)
        fdt_data = self.read_sram(0x00E8, 8)
        touch_vals = [(fdt_data[j] << 8) | fdt_data[j+1] for j in range(0, 8, 2)]
        return st_80 == 0x54 or any(v > 50 for v in touch_vals), touch_vals

    def capture_image_frame(self):
        self.disable_finger_detect()
        self.write_16bit(0x1801, 0xFCA7)
        self.write_16bit(0x1800, 0x4FFE)
        time.sleep(0.005)

        self.send_cmd(CMD_SCAN_IMG)
        time.sleep(0.03)

        for _ in range(30):
            if self.read_reg(0x80) == 0x54:
                break
            time.sleep(0.002)

        raw_data = self.read_sram_bulk(0x0000, 10240)
        pixels = []
        for i in range(0, len(raw_data), 2):
            px = (raw_data[i] << 8) | raw_data[i+1]
            pixels.append(px)
        return np.array(pixels, dtype=np.uint16).reshape((80, 64))
