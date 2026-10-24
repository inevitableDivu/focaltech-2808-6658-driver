# Open-Source Linux Driver for FocalTech 2808:6658 Fingerprint Sensor

[![Status: Work in Progress](https://img.shields.io/badge/Status-Work%20in%20Progress-orange.svg)](https://github.com/inevitableDivu/focaltech-2808-6658-driver)
[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html)

> ⚠️ **Status: Experimental / Research Prototype (Work In Progress)**  
> This driver is currently under active research and development and is **not yet suitable for daily biometric authentication**.  
> While the low-level USB transport, command framing, and raw sensor matrix extraction have been fully reverse-engineered, integrating compact match-on-host sensors with open-source matching algorithms (`libfprint`, NIST `mindtct`, `bozorth3`) involves significant architectural challenges detailed below.

---

## 💻 Supported Hardware

| Attribute | Value |
| :--- | :--- |
| **USB Vendor ID** | `0x2808` (Realtek USB2.0 Finger Print Bridge) |
| **USB Product ID** | `0x6658` (FocalTech Fingerprint Device) |
| **Other reported PIDs** | `0x9366`, `0x6652`, `0x9201` (unverified; not registered by this driver) |
| **Reported chip families** | FW9366, FW9391, FT9366, FT9201 (not all verified; only USB ID `2808:6658` is registered) |
| **Sensor Type** | Capacitive Touch / Imaging ($80 \times 64$ raw sensels, $\approx 3.2\text{ mm} \times 4.0\text{ mm}$) |
| **Architecture** | Match-on-Host (Host-based minutiae extraction and matching) |

---

## 🚦 Current Development Status

- [x] **USB Protocol Reverse-Engineering:** Complete packet structure, endpoint mappings (EP OUT `0x01`, EP IN `0x82`), AFE register sequence, and memory readout opcodes.
- [x] **Raw Frame Acquisition:** Successfully extracting 16-bit big-endian capacitive image matrices from SRAM base `0x0200` and FIFO `0x1A05`.
- [x] **Python Userspace Toolkit:** Standalone diagnostic and frame export tool (`python/cli.py`).
- [x] **Arch Linux PKGBUILD:** Automated compilation script for patched `libfprint-focaltech-6658`.
- [x] **Touch Noise Filtering:** Dynamic Exponential Moving Average (EMA) baseline tracking and 2-frame persistence debouncing to filter periodic internal ADC recalibration spikes.
- [ ] **Reliable Match-on-Host Authentication:** ⚠️ Ongoing challenge due to tiny sensor dimensions ($64 \times 80$) and NIST NBIS algorithm limitations.

---

## 🔬 Technical Challenges & Open Problems

Reverse-engineering tiny capacitive match-on-host fingerprint sensors under Linux presents several deep technical obstacles:

### 1. Small Sensor Geometry vs. NIST NBIS (`mindtct` / `bozorth3`)
* **Physical Dimension:** The sensor matrix is only $64 \times 80$ sensels ($\approx 3.2\text{ mm} \times 4.0\text{ mm}$).
* **NIST NBIS Design Assumptions:** Standard `libfprint` uses the NIST NBIS algorithm suite (`mindtct` for feature extraction and `bozorth3` for matching), which was historically designed for full-sized $500\text{ DPI}$ optical/flatbed fingerprint scanners ($256 \times 360+$ pixels).
* **Low Minutiae Density:** A partial press on a $64 \times 80$ matrix typically captures only $4\text{ to }6$ distinct minutiae points. For `bozorth3`, 4 minutiae points is right on the statistical boundary between genuine verification and false accepts/rejects.

### 2. Fixed-Pattern Noise (FPN) & Silicon DC Bias
* Empty sensor frames contain static silicon DC bias patterns (fixed-pattern noise) from physical chip manufacture.
* Without aggressive dynamic baseline tracking and contrast gating, open-source minutiae extractors can detect pseudo-minutiae along these static grid lines, causing empty sensor frames to match other empty frames with 100% false confidence.

### 3. Periodic Hardware ADC Recalibration Glitches
* The FocalTech FW9366 hardware chip automatically executes an internal ADC reference voltage refresh every $\sim 1.5\text{ seconds}$.
* This produces a transient single-frame ($60\text{ms}$) burst where 5–10 sensels spike in value. A multi-frame persistence filter (`touch_streak >= 2`) is required to prevent these internal hardware calibration bursts from triggering false touch events.

### 4. Proprietary Vendor DSP Pipeline
* The proprietary Windows driver (`ftWbioUmdfDriverV2.dll`) relies on custom Gabor wavelet filter banks, adaptive directional flow smoothing, and multi-frame composite template stitching specifically tuned for the FW9366 silicon geometry.
* Standard `libfprint` image pipelines lack built-in multi-frame composite image stitchers for press sensors, making reliable feature extraction significantly harder on compact chips.

---

## 📁 Repository Structure

```
├── docs/
│   ├── PROTOCOL.md             # Reverse-engineered USB protocol & architecture
│   └── LINUX-SETUP.md          # Linux dependency, build, fprintd, and test guide
├── python/                     # Standalone Python user-space diagnostic tool
│   ├── focaltech/
│   │   ├── __init__.py
│   │   └── sensor.py           # Core sensor driver class (PyUSB)
│   └── cli.py                  # CLI frame capture & touch testing
├── libfprint-driver/           # Native C driver for libfprint & Arch PKGBUILD
│   ├── focaltech_6658.c        # libfprint driver implementation
│   └── PKGBUILD                # Arch Linux package build script
├── scripts/                    # Linux setup, fprintd integration, and test helpers
├── requirements.txt            # Python toolkit dependencies
└── .gitignore                  # Excludes proprietary DLLs & biometric data
```

---

## Native libfprint / fprintd troubleshooting

The Arch recipe requests all registered libfprint drivers so the custom `focaltech_6658` backend is not silently excluded by a default-driver selection. After installation, restart the daemon and inspect its logs:

```bash
sudo systemctl restart fprintd
fprintd-list "$USER"
journalctl -u fprintd -b --no-pager
```

A successful compile is not proof that enrollment works. The backend is experimental and must be tested on the exact sensor revision. Check the Meson summary for `focaltech_6658` and confirm that another system libfprint library is not shadowing the packaged build.

For repeatable Linux dependency setup, a local upstream libfprint build, opt-in
fprintd integration, and non-destructive testing scripts, see
[`docs/LINUX-SETUP.md`](docs/LINUX-SETUP.md). The explicit integration option
changes the fprintd service and device access rule; read its warnings before
running it.

## 🚀 Testing with Python (Hardware Verification)

### Python Diagnostic Toolkit
```bash
# Install supported Linux packages and create the project-local environment
scripts/setup-linux.sh

# Test real-time touch detection
.venv/bin/python python/cli.py --test

# Capture a raw sensor frame (contains biometric data; keep it private)
.venv/bin/python python/cli.py --capture private-frame.png
```

The scripts do not install permissive USB permissions such as world-writable
`0666` rules. See the setup guide for supported distributions and fprintd
integration steps.

---

## 📜 Protocol Documentation
For the full technical specification of USB packets, register addresses, command opcodes, and memory layouts, see [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

---

## 🤝 Contributing
Contributions, research ideas, DSP filter implementations, and packet captures from other hardware revisions are warmly welcome! Feel free to open an issue or submit a pull request.

---

## ⚖️ Legal & Privacy Disclaimer
* This project was created via clean-room reverse engineering of hardware protocols for Linux interoperability.
* **No proprietary binaries or copyrighted vendor blobs are included in this repository.**
* **Never commit personal biometric scan images (`.png`, `.raw`) to public repositories.**
