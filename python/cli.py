#!/usr/bin/env python3
import time
import argparse
from focaltech import FocalTechSensor
from PIL import Image
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="FocalTech 2808:6658 Driver CLI")
    parser.add_argument("--test", action="store_true", help="Test sensor connection & touch detection")
    parser.add_argument("--capture", type=str, help="Capture single frame to specified PNG file")
    args = parser.parse_args()

    sensor = FocalTechSensor()
    print("Connecting to sensor...")
    sensor.connect()
    sensor.init_chip()
    print("Sensor initialized successfully.")

    if args.test:
        print("Enabling Finger Detection Mode. Touch the sensor now!")
        sensor.enable_finger_detect()
        for i in range(1, 21):
            touch, vals = sensor.is_finger_present()
            status = ">>> FINGER DETECTED! <<<" if touch else "Idle"
            print(f"[{i:2d}/20] Touch={touch} (Deltas={vals}) --> {status}")
            time.sleep(0.3)
        sensor.disable_finger_detect()

    if args.capture:
        print("Capturing frame...")
        arr = sensor.capture_image_frame()
        p_min, p_max = arr.min(), arr.max()
        if p_max > p_min:
            norm = ((arr - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
        else:
            norm = (arr % 256).astype(np.uint8)
        img = Image.fromarray(norm, mode='L').resize((320, 400), Image.Resampling.BILINEAR)
        img.save(args.capture)
        print(f"Frame saved to {args.capture}")

    sensor.disconnect()

if __name__ == "__main__":
    main()
