#!/usr/bin/env python3
from evdev import InputDevice, list_devices, ecodes

print("N.O.R.M. touch probe")
print("====================")

devices = []
for path in list_devices():
    dev = InputDevice(path)
    devices.append(dev)
    print(f"{path}: {dev.name}")

touch = None

for dev in devices:
    if "QDtech" in dev.name or "touch" in dev.name.lower():
        touch = dev
        break

if touch is None:
    touch = InputDevice("/dev/input/event0")

print()
print(f"Using: {touch.path} / {touch.name}")
print("Touch the screen. Press CTRL+C to stop.")
print()

for event in touch.read_loop():
    if event.type == ecodes.EV_KEY:
        print("KEY", ecodes.KEY.get(event.code, event.code), event.value)

    elif event.type == ecodes.EV_ABS:
        print("ABS", ecodes.ABS.get(event.code, event.code), event.value)
