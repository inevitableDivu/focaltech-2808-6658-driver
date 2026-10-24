# FocalTech FW9366 / Realtek USB Bridge (2808:6658) Protocol Specification

This document details the reverse-engineered communication protocol, register specifications, and architectural findings for the **FocalTech FW9366** capacitive fingerprint sensor operating through the **Realtek USB 2.0 Bridge** (USB ID `2808:6658`).

---

## 1. Hardware Architecture

* **Vendor ID (VID):** `0x2808`
* **Product ID (PID):** `0x6658` (the only product ID registered by this driver)
* **Other reported product IDs:** `0x9366`, `0x6652`, `0x9201` are unverified here and are not claimed as supported.
* **USB Interface:** Interface `0` (Vendor Specific Class `0xFF`)
* **Endpoints:**
  * `0x01` (EP 1 OUT, Bulk, Max Packet Size 512 bytes): Host-to-Device command & write stream
  * `0x82` (EP 2 IN, Bulk, Max Packet Size 512 bytes): Device-to-Host response & sensor frame stream
* **Sensor Geometry:** $80 \times 64$ pixels ($5,120$ sensels total, physical active area $\approx 3.2\text{ mm} \times 4.0\text{ mm}$)
* **Pixel Bit Depth:** 16-bit unsigned (big-endian), raw frame size = $10,240\text{ bytes}$ ($0x2800$).
* **Matching Architecture:** **Match-on-Host (Imaging Sensor)**. Minutiae extraction and matching is performed on the host CPU.

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
| `0x00B8` (SRAM) | `FW9366_FDT_DELTAS`| 8 $\times$ 16-bit capacitive touch delta values (FW9366 chip default) |
| `0x00E8` (SRAM) | `FW9391_FDT_DELTAS`| 4 $\times$ 16-bit capacitive touch delta values (FW9391 chip variant) |
| `0x0000`..`0x01FF` (SRAM)| `CALIB_DATA` | 512-byte internal calibration registers & ADC mirrors |
| `0x0200`..`0x29FF` (SRAM)| `FRAME_BUFFER` | $10,240$-byte raw capacitive matrix ($80 \times 64$ pixels) |
| `0x1A05` (FIFO) | `SCAN_FIFO` | Streamed output of scanned matrix frame |

The FocalTech Windows UMDF driver package (`2.0.4.91`) includes FW9366
touch-detection code that selects `0x00B8` for its normal variant and
`0x00E8` when an internal chip-variant marker is `0xAA`. The Linux Python
diagnostic therefore reads eight 16-bit values from `0x00B8` for the
registered FW9366 device. This mapping is based on static analysis of the
vendor driver, not a live Windows USB trace.

The native libfprint driver enables FDT with register `0x9A = 0x5A`,
triggers sensing with [`0xC2, 0x3D, 0x00`], and reads eight values from
`0x00B8`. Status `0x54` on register `0x80` is not accepted as proof of a
finger. An earlier successful Python hardware run returned status `0x50` with
deltas `[3098, 3061, 3048, 2952, 2972, 3188, 3158, 877]`; therefore,
`0x03FF` cannot safely be assumed to be the maximum possible delta. A later
false-touch run returned status `0x04` with all eight values equal to
`1028` (`0x0404`) and remained in that state after the finger was lifted.
The detector now accepts a sample only when status is `0x50`, at least two
non-sentinel channels are present, and their values are not all identical;
the same guards are applied in Python and native libfprint. This rejects the
observed flat `0x0404` pattern without imposing a 10-bit ceiling.

The status check is an empirical safeguard: `0x50` was seen with the earlier
successful sample and is documented here as the AFE-ready status, but the
vendor has not confirmed that it guarantees a fresh FDT sample. If samples
remain unready, the missing FDT initialization/refresh sequence may still need
reverse engineering. Short Python SRAM reads fail explicitly instead of being
parsed as complete samples. The `0x00B8` / `0x00E8` variant choice is based on
static analysis of the Windows driver, not a live Windows USB trace.

---

## 5. Operational Sequences

### 5.1. Initialization & AFE Wakeup
1. Send `write_reg(0xC6, 0x00)` (Clear reset register).
2. Send `send_cmd(9)` (`[0x5A, 0xA5, 0x00]`).
3. Poll `read_reg(0x80)` until status is `0x50` (AFE ready).
4. Send `send_cmd(10)` (`[0xA5, 0x5A, 0x00]`).

### 5.2. Image Acquisition
1. Write configuration registers:
   * `write_16bit(0x1801, 0xFCA7)`
   * `write_16bit(0x1800, 0x4FFE)`
2. Send `send_cmd(3)` (`[0xC4, 0x3B, 0x00]`) to trigger scan.
3. Wait $\sim 35\text{ms}$ or poll `read_reg(0x80)` until `0x54` (Scan complete).
4. Read $10,240\text{ bytes}$ from SRAM base `0x0200` (20 chunks $\times 512\text{ bytes}$).
5. Unpack big-endian 16-bit pixels into $80 \times 64$ matrix.

---

## 6. Architectural Challenges & Open Research Problems

### 6.1. Small Aperture Minutiae Extraction
Standard open-source biometric stacks (`libfprint`, NIST NBIS `mindtct`, `bozorth3`) assume a standard 500 DPI scanner capturing at least $10\text{ mm} \times 10\text{ mm}$ of skin area ($200 \times 200+$ pixels). The FW9366 active area is only $\approx 3.2\text{ mm} \times 4.0\text{ mm}$ ($64 \times 80$ sensels). Because only $4\text{ to }6$ minutiae points are typically visible in a single press, standard minutiae-based matchers suffer from low discriminative power without multi-frame composite template stitching.

### 6.2. Internal ADC Recalibration Spikes
The FW9366 chip automatically executes internal reference voltage refreshes every $\sim 1.5\text{s}$, producing a 1-frame transient spike across $5\text{ to }10$ sensels. Host software must employ a multi-frame persistence filter (`touch_streak >= 2`) or moving baseline auto-calibration to avoid false touch triggers.

### 6.3. Fixed-Pattern Noise (FPN) Filtering
Raw sensels have slight silicon DC manufacturing variations. Without dynamic baseline tracking, open-source feature extractors can mistakenly treat static DC variation as ridge structure, resulting in false matching between empty frames.
