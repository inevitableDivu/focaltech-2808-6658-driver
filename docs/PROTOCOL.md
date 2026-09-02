# FocalTech FW9366 / Realtek USB Bridge (2808:6658) Protocol Specification

This document details the reverse-engineered communication protocol for the **FocalTech FW9366** capacitive fingerprint sensor operating through the **Realtek USB 2.0 Bridge** (USB ID `2808:6658`).

---

## 1. Hardware Architecture

* **Vendor ID (VID):** `0x2808`
* **Product ID (PID):** `0x6658` (Also compatible with `0x9366`, `0x6652`, `0x9201`)
* **USB Interface:** Interface `0` (Vendor Specific Class `0xFF`)
* **Endpoints:**
  * `0x01` (EP 1 OUT, Bulk, Max Packet Size 512 bytes): Host-to-Device command & write stream
  * `0x82` (EP 2 IN, Bulk, Max Packet Size 512 bytes): Device-to-Host response & sensor frame stream
* **Sensor Geometry:** $80 \times 64$ pixels ($5,120$ pixels total)
* **Pixel Bit Depth:** 16-bit unsigned (big-endian), raw frame size = $10,240\text{ bytes}$ ($0x2800$).
* **Matching Architecture:** **Match-on-Host (Imaging Sensor)**. Minutiae extraction and matching is performed on the host CPU using standard open-source engines (e.g. NIST NBIS / Bozorth3).

---

## 2. Command Packet Formats

All communication with the sensor is structured around fixed-header packet types sent over EP `0x01` (OUT) and read from EP `0x82` (IN).

### 2.1. 8-Bit Register Write (`0x09 0xF6`)
* **OUT Packet (4 bytes):**
  `[0x09, 0xF6, reg_addr, reg_val]`
* **Response:** None.

### 2.2. 8-Bit Register Read (`0x08 0xF7`)
* **OUT Packet (5 bytes):**
  `[0x08, 0xF7, reg_addr, 0x00, 0x00]`
* **IN Response (1 byte):**
  `[reg_val]`

### 2.3. 16-Bit / SRAM Memory Write (`0x05 0xFA`)
* **OUT Packet ($6 + N$ bytes):**
  `[0x05, 0xFA, addr_hi | 0x80, addr_lo, words_hi, words_lo, ...data...]`
* **Response:** None.
* **Note:** Word count is $N / 2$.

### 2.4. 16-Bit / SRAM Memory Read (`0x04 0xFB`)
* **OUT Packet (6 bytes):**
  `[0x04, 0xFB, addr_hi | 0x80, addr_lo, words_hi, words_lo]`
* **IN Response ($N$ bytes):**
  `[byte_0, byte_1, ...]`

### 2.5. FIFO Stream Read (`0x06 0xF9`)
* **OUT Packet (6 bytes):**
  `[0x06, 0xF9, addr_hi | 0x80, addr_lo, words_hi, words_lo]`
* **IN Response ($N$ bytes):**
  Streams $N$ bytes across consecutive 512-byte bulk packets on EP `0x82`.

---

## 3. High-Level Command Opcode Table

Standard 3-byte command packets dispatched to the sensor:

| Command Index | Bytes | Description |
| :---: | :--- | :--- |
| `0` | `[0xC0, 0x3F, 0x00]` | Soft Reset / Return to Idle |
| `1` | `[0xC1, 0x3E, 0x00]` | Low-power Standby |
| `2` | `[0xC2, 0x3D, 0x00]` | Trigger FDT (Finger Detect Mode) sense cycle |
| `3` | `[0xC4, 0x3B, 0x00]` | Trigger Full Image Matrix Scan |
| `9` | `[0x5A, 0xA5, 0x00]` | Analog Front-End (AFE) Wakeup / Power-On |
| `10` | `[0xA5, 0x5A, 0x00]` | AFE Ready / Lock Configuration |

---

## 4. Key Registers & Memory Map

| Address / Reg | Name | Description |
| :--- | :--- | :--- |
| `0x80` (8-bit) | `STATUS_REG` | Sensor operational status (`0x50` = AFE ready, `0x54` = Scan complete) |
| `0x8E` (8-bit) | `ADC_CLOCK` | Sensor ADC scan rate divider |
| `0x90`..`0x92` (8-bit) | `TIMER_INTEGRATION`| Capacitive integration duration timer |
| `0x9A` (8-bit) | `FDT_CTRL` | Finger Detection Mode enable (`0x5A` = Enabled, `0x00` = Disabled) |
| `0x9B` (8-bit) | `CHIP_VER` | Chip revision (`0x4C` = Variant `0x13` / `0xAA`) |
| `0xC6` (8-bit) | `RESET_REG` | Chip heartbeat / reset check register |
| `0x1800` (16-bit) | `MODE_CTRL` | Mode control (`0x4FFE` = Image mode, `0x0000` = Idle) |
| `0x1801` (16-bit) | `MODE_STATUS` | Configuration status register (`0xFCA7`) |
| `0x00E8` (SRAM) | `FDT_DELTAS` | 4 $\times$ 16-bit capacitive touch delta values |
| `0x0000`..`0x2800` (SRAM) | `IMAGE_BUFFER`| 10,240-byte active frame pixel buffer |

---

## 5. Sensor Operational Sequences

### 5.1. Initialization & AFE Wakeup
1. Send `write_reg(0xC6, 0x00)` (Clear reset).
2. Send `send_cmd(9)` (`[0x5A, 0xA5, 0x00]`).
3. Poll `read_reg(0x80)` until status is `0x50` (AFE ready).
4. Send `send_cmd(10)` (`[0xA5, 0x5A, 0x00]`).

### 5.2. Finger Presence Detection (FDT Mode)
1. Send `write_reg(0x9A, 0x5A)` (Enable FDT mode).
2. Periodically send `send_cmd(2)` (Trigger FDT sense).
3. Read `read_sram(0x00E8, 8)`.
4. If capacitive deltas exceed the touch threshold ($> 50$) or `read_reg(0x80) == 0x54`, a finger is actively touching the sensor.

### 5.3. Image Acquisition
1. Send `write_reg(0x9A, 0x00)` (Disable FDT mode).
2. Write mode registers:
   * `write_16bit(0x1801, 0xFCA7)`
   * `write_16bit(0x1800, 0x4FFE)`
3. Send `send_cmd(3)` (`[0xC4, 0x3B, 0x00]`).
4. Poll `read_reg(0x80)` until `0x54` (Scan complete).
5. Read $10,240\text{ bytes}$ from SRAM base `0x0000` over EP `0x82`.
6. Unpack big-endian 16-bit pixels into $80 \times 64$ matrix.
