# Open-Source Linux Driver for FocalTech 2808:6658 Fingerprint Sensor

[![Status: Work in Progress](https://img.shields.io/badge/Status-Work%20in%20Progress-orange.svg)](https://github.com/inevitableDivu/focaltech-2808-6658-driver)
[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)

> ⚠️ **Status: Experimental / Work In Progress (WIP)**  
> This driver is currently under active development and is **not yet fully functional for daily use**.  
> While the USB protocol, register sequences, and raw sensor matrix extraction have been reverse-engineered, the native `libfprint` / `fprintd` integration is still undergoing calibration for touch detection reliability and minutiae extraction. Contributions and feedback are welcome!

---

## 💻 Supported Hardware

| Attribute | Value |
| :--- | :--- |
| **USB Vendor ID** | `0x2808` (Realtek USB2.0 Finger Print Bridge) |
| **USB Product ID** | `0x6658` (FocalTech Fingerprint Device) |
| **Known Alternate PIDs** | `0x9366`, `0x6652`, `0x9201` |
| **Compatible Chips** | FW9366, FW9391, FT9366, FT9201 |
| **Sensor Type** | Capacitive Touch / Imaging ($80 \times 64$ raw sensels) |
| **Architecture** | Match-on-Host (Open-source minutiae extraction via NIST NBIS / Bozorth3) |

---

## 🚦 Current Development Status

- [x] **USB Protocol Analysis:** Reverse-engineered packet structure, endpoint mappings (EP OUT `0x01`, EP IN `0x82`), and AFE command opcodes.
- [x] **Raw Frame Capture:** Successfully extracting 16-bit raw capacitive frames from SRAM base `0x0200`.
- [x] **Python Proof-of-Concept:** Standalone userspace capture and image export working in `python/cli.py`.
- [x] **Arch Linux PKGBUILD:** Automated build script packaging native `libfprint` with driver patch.
- [ ] **`libfprint` Integration:** ⚠️ In progress. Minutiae extraction and hardware touch threshold calibration are still being tuned for consistent enrollment and verification.

---

## 📁 Repository Structure

```
├── docs/
│   └── PROTOCOL.md             # Complete reverse-engineered protocol documentation
├── python/                     # Standalone Python user-space library & test CLI
│   ├── focaltech/
│   │   ├── __init__.py
│   │   └── sensor.py           # Core sensor driver class (PyUSB)
│   └── cli.py                  # Command-line interface tool
├── libfprint-driver/           # Native C driver for libfprint / fprintd & PKGBUILD
│   ├── focaltech_6658.c        # libfprint driver implementation
│   └── PKGBUILD                # Arch Linux package build script
└── .gitignore                  # Excludes proprietary DLLs & biometric data
```

---

## 🚀 Testing with Python (Hardware Verification)

### 1. Set Up `udev` Permissions
To interact with the USB device without requiring root:
```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2808", ATTR{idProduct}=="6658", MODE="0666", GROUP="wheel"' | sudo tee /etc/udev/rules.d/70-focaltech.rules
sudo udevadm control --reload-rules && sudo udevadm trigger --attr-match=idVendor=2808
```

### 2. Install Dependencies
```bash
pip install pyusb numpy pillow
```

### 3. Run Test
```bash
# Test real-time touch detection
python python/cli.py --test

# Capture a test frame
python python/cli.py --capture test_frame.png
```

---

## 📜 Protocol Documentation
For the technical specification of USB packets, register addresses, command opcodes, and SRAM layouts, see [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

---

## 🤝 Contributing
Contributions, issue reports, and packet captures from other hardware revisions are welcome! Feel free to open an issue or submit a pull request.

---

## ⚖️ Legal & Privacy Disclaimer
* This project was created via clean-room reverse engineering of hardware protocols for Linux interoperability.
* **No proprietary binaries or copyrighted vendor blobs are included in this repository.**
* **Never commit personal biometric scan images (`.png`, `.raw`) to public repositories.**
