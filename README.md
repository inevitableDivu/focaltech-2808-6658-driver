# Open-Source Linux Driver for FocalTech 2808:6658 Fingerprint Sensor

This repository provides an open-source driver and protocol specification for the **FocalTech FW9366 / Realtek USB 2.0 Bridge** fingerprint sensor (`2808:6658`).

---

## 💻 Supported Hardware

| Attribute | Value |
| :--- | :--- |
| **USB Vendor ID** | `0x2808` (Realtek USB2.0 Finger Print Bridge) |
| **USB Product ID** | `0x6658` (FocalTech Fingerprint Device) |
| **Compatible Chips** | FW9366, FW9391, FT9366, FT9201 |
| **Sensor Type** | Capacitive Touch / Imaging ($80 \times 64$ pixels) |
| **Architecture** | Match-on-Host (Open-source minutiae matching via NIST NBIS / Bozorth3) |

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
├── libfprint-driver/           # Native C driver for libfprint / fprintd
│   └── (In development)
└── .gitignore                  # Excludes proprietary DLLs & biometric images
```

---

## 🚀 Quick Start (Testing with Python)

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
For the complete technical specification of USB packets, register addresses, command opcodes, and SRAM layouts, see [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

---

## ⚖️ Legal & Privacy Disclaimer
* This project was created via clean-room reverse engineering of hardware protocols for Linux interoperability.
* **No proprietary binaries or copyrighted vendor blobs are included in this repository.**
* **Never commit personal biometric scan images (`.png`, `.raw`) to public repositories.**
