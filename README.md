# SpaceControl Virtual Device Bridge

`spacecontrol-bridge.py` is a Python script that acts as an intermediary between the SpaceControl 3D mouse (SpaceControl GmbH & Co. KG) daemon and the Linux input subsystem. It enables the use of SpaceControl devices as standard virtual input devices (3D mouse and/or gamepad) across a wider range of Linux applications.
## Features

   - Daemon Communication: Connects to the SpaceControl daemon (`sc_daemon`) to receive raw 6DoF motion data and button events.

   - Seamless `spacenavd` Integration (Virtual 3D Mouse Emulation): Creates a virtual 3D mouse device that is fully compatible with `spacenavd`, allowing direct and seamless integration with popular 3D applications like Blender, FreeCAD, and other CAD/3D software that rely on `spacenavd` for SpaceMouse support.

   - Virtual Gamepad Emulation: (Optional, experimental) Creates a generic virtual gamepad, mapping SpaceControl inputs to standard gamepad axes and buttons for use in games or other applications.

   - Background Service: Designed to run as a systemd service for persistent operation.

## Requirements

   - SpaceControl Driver/Daemon: The official SpaceControl Linux driver (sc_daemon) must be installed and running. This script communicates with it via its native library.

   - Python 3

   - `evdev` Python Library: Used for creating and sending events to virtual input devices.

   - `uinput` Kernel Module: The uinput kernel module must be loaded.

   - Permissions: The user running the script must have write access to `/dev/uinput` (typically achieved by being in the `input` group).

   - spacenavd

## Installation (as part of `spacecontrol-driver` package)

This script is intended to be packaged and installed as part of the `spacecontrol-driver` Arch Linux package (or similar distribution package). When installed via the PKGBUILD, it will be placed at `/opt/spacecontrol-driver/python_bridge/spacecontrol-bridge.py` and managed by a systemd service.
Usage
As a Systemd Service (Recommended)

Once installed via the `spacecontrol-driver` package, enable and start the service:
```
sudo systemctl --user enable spacecontrol-bridge.service
sudo systemctl --user start spacecontrol-bridge.service
```
Check its status and logs:
```
systemctl status spacecontrol-bridge.service
journalctl -u spacecontrol-bridge.service -f
```
Manual Execution (for Testing/Debugging)

To run the script manually for testing (ensure the sc_daemon is running first):
```
/opt/spacecontrol-driver/python_bridge/spacecontrol-bridge.py
```
Press `Ctrl+C` in the terminal to stop the script.
## Configuration

   - `SC_LIB_PATH`: Modify this variable in the script if your `libspc_ctrl.so` library is located at a different path than /opt/SpaceControl/lib/libspc_ctrl.so. (Note: The PKGBUILD handles this by installing it to `/usr/lib/` and setting LD_LIBRARY_PATH for the daemon wrapper).

   - `ENABLE_3DMOUSE_VIRTUAL_DEVICE`: Set to `True` or `False` to enable/disable the virtual 3D mouse.

   - `ENABLE_GAMEPAD_VIRTUAL_DEVICE`: Set to `True` or `False` to enable/disable the virtual gamepad.

   - `AXIS_SCALE`: Adjust the sensitivity of the virtual device axes.

   - `LOGLEVEL`: Change to `logging.DEBUG` for verbose output during troubleshooting.

## Troubleshooting

   - "Could not establish connection with SpaceControl daemon.": Ensure `sc_daemon` is running.

   - "Failed to create uinput device":

       - Verify `uinput` module is loaded

       - Check permissions for `/dev/uinput`. Your user needs to be in the `input` group.

   - No input in applications:

       - Check journal for errors.

       - For 3D mouse, ensure `spacenavd` is running and configured correctly.

       - For gamepad, use `jstest /dev/input/jsX` (replace X with the correct number, usually 0 or 1) to verify input.

Development Notes

   - The script uses `ctypes` for FFI (Foreign Function Interface) to interact with the native `libspc_ctrl.so` library.

   - Axis values and button events are received from the daemon and mapped to `evdev` codes.

   - High-level events (like "Fit View") are handled separately from low-level button bitmasks.

   - The `collections` import is currently unused and can be removed if a leaner script is desired. The `GAMEPAD_BIT_TO_EVDEV_CODE` dictionary is present for potential future Xbox-style gamepad mapping.