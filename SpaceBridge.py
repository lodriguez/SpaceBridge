import ctypes
import time
import threading
import sys
import os
import collections # For deque to store last axis values
from evdev import UInput, ecodes, AbsInfo # pip install evdev
import logging

# Logging levels used in this script: logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG
LOGLEVEL = logging.WARNING # Set to DEBUG for detailed output during troubleshooting

# --- Setup Logging ---
def setup_logging(level=LOGLEVEL):
    """Configures the standard Python logging module."""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        level=level
    )

logger = logging.getLogger("SpaceControl")

# --- Configuration ---
SC_LIB_PATH = "/opt/SpaceControl/lib/libspc_ctrl.so" # Verify this path

# --- Device Enablement Flags ---
# Set to True to enable the corresponding virtual device, False to disable.
ENABLE_3DMOUSE_VIRTUAL_DEVICE = True
ENABLE_GAMEPAD_VIRTUAL_DEVICE = False

# Configuration for the Virtual 3D Mouse (for spacenavd)
UINPUT_3DMOUSE_NAME = "SpaceController spacenavd" 
UINPUT_3DMOUSE_VENDOR_ID = 0x046d # 3Dconnexion
UINPUT_3DMOUSE_PRODUCT_ID = 0xc627 # SpaceMouse Enterprise (Well-known PID supported by spacenavd)

# Configuration for the Virtual Gamepad
UINPUT_GAMEPAD_NAME = "SpaceController Virtual Gamepad" 
UINPUT_GAMEPAD_VENDOR_ID = 0x1209 # Linux Foundation / Custom Development
UINPUT_GAMEPAD_PRODUCT_ID = 0x0001 # Custom Virtual Gamepad

# Axis scaling factors - apply to both devices
AXIS_SCALE = 20 

# Define a constant for the threshold of high-level events, used for numerical comparison.
HIGH_LEVEL_EVENT_THRESHOLD = 0x20000

# APPL_FUNC_START is explicitly defined as an event ID here, matching the original map entry.
APPL_FUNC_START = 0x20020 

# Comprehensive map of all SpaceControl event IDs and DLL status codes to their descriptive string names.
# This serves as the single source of truth for translating numeric event values.
EVENT_ID_TO_NAME = {
    # Special status/control events
    -1: "NOTHING_CHANGED", # Returned when no new motion data
    
    # DLL Status Codes (from ScDllWrapper.java's intToStatus method)
    0: "SC_OK",
    1: "SC_COMMUNICATION_ERROR",
    2: "SC_WRONG_DEVICE_INDEX",
    3: "SC_PARAMETER_OUT_OF_0RANGE",
    4: "SC_FILE_IO_ERROR",
    5: "SC_KEYSTROKE_ERROR",
    6: "SC_APPL_NOT_FOUND",
    7: "SC_REGISTRY_ERROR",
    8: "SC_NOT_SUPPORTED",
    9: "SC_EXEC_CMD_ERROR",
    10: "SC_THREAD_ERROR",
    11: "SC_WRONG_USER",

    # High-Level SpaceControl Device/Application Events
    0x20020: "APPL_FUNC_START",
    0x20000: "DEV_BASIC_SETTINGS_REQ",
    0x20001: "DEV_ADVANCED_SETTINGS_REQ",
    0x20002: "DEV_DEV_PARS_CHANGED",
    0x20003: "DEV_UNKNOWN_COMMAND_BYTE",
    0x20004: "DEV_PARAM_OUT_OF_RANGE",
    0x20005: "DEV_PARSE_ERROR",
    0x20006: "DEV_INTERNAL_DEVICE_ERROR",
    0x20007: "DEV_WRONG_TRANSCEIVER_ID",
    0x20008: "DEV_BUFFER_OVERFLOW",
    0x20009: "DEV_FRONT",
    0x2000A: "DEV_RIGHT",
    0x2000B: "DEV_TOP",
    0x2000C: "DEV_FIT",
    0x2000D: "DEV_WHEEL_LEFT",
    0x2000E: "DEV_WHEEL_RIGHT",
    0x2000F: "EVT_HNDL_SENS_DLG",
    0x20010: "EVT_HNDL_THRESH_DLG",
    0x20011: "EVT_HNDL_LCD_DLG",
    0x20012: "EVT_HNDL_LEDS_DLG",
    0x20013: "EVT_APPL_IN_FRGRND",
    0x20014: "EVT_HNDL_KBD_DLG",
    0x20015: "EVT_HNDL_WFL_DLG",
    0x20016: "DEV_BACK",
    0x20017: "DEV_LEFT",
    0x20018: "DEV_BOTTOM",
    0x20019: "DEV_CTRL",
}


# --- SpaceControl Data Structures (from C headers - spc_ctrlr.h) ---
class ScStdData(ctypes.Structure):
    _fields_ = [
        ("mX", ctypes.c_short), ("mY", ctypes.c_short), ("mZ", ctypes.c_short),
        ("mA", ctypes.c_short), ("mB", ctypes.c_short), ("mC", ctypes.c_short),
        ("mTraLmh", ctypes.c_int), ("mRotLmh", ctypes.c_int), ("event", ctypes.c_int),
        ("mTvSec", ctypes.c_long), ("mTvUsec", ctypes.c_long)
    ]

# --- Button and Event Mappings for evdev ---

# 3D Mouse specific button mappings (for spacenavd)
EVDEV_3DMOUSE_LOW_LEVEL_BUTTON_MAP = {
    "SC_KEY_1": ecodes.BTN_MISC + 0,    # Button 1
    "SC_KEY_2": ecodes.BTN_MISC + 1,    # Button 2
    "SC_KEY_3": ecodes.BTN_MISC + 2,
    "SC_KEY_4": ecodes.BTN_MISC + 3,
    "SC_KEY_5": ecodes.BTN_MISC + 4,
    "SC_KEY_6": ecodes.BTN_MISC + 5,
    "SC_KEY_CTRL": ecodes.BTN_MISC + 6,
    "SC_KEY_ALT": ecodes.BTN_MISC + 7,
    "SC_KEY_SHIFT": ecodes.BTN_MISC + 8,
    "SC_KEY_ESC": ecodes.BTN_MISC + 9,
    "SC_KEY_FRONT": ecodes.BTN_MISC + 10, 
    "SC_KEY_RIGHT": ecodes.BTN_MISC + 11, 
    "SC_KEY_TOP": ecodes.BTN_MISC + 12,   
    "SC_KEY_FIT": ecodes.BTN_MISC + 13,
    "SC_KEY_2D3D": ecodes.BTN_MISC + 14, # From GUI combobox string, not a direct high-level event
    # 'B' variants (Button-Press versions, typically for double-press or long-press, from vks.ini)
    "SC_KEY_1_B": ecodes.BTN_MISC + 17, "SC_KEY_2_B": ecodes.BTN_MISC + 18,
    "SC_KEY_3_B": ecodes.BTN_MISC + 19, "SC_KEY_4_B": ecodes.BTN_MISC + 20,
    "SC_KEY_5_B": ecodes.BTN_MISC + 21, "SC_KEY_6_B": ecodes.BTN_MISC + 22,
    "SC_KEY_CTRL_B": ecodes.BTN_MISC + 23, "SC_KEY_ALT_B": ecodes.BTN_MISC + 24,
    "SC_KEY_SHIFT_B": ecodes.BTN_MISC + 25, "SC_KEY_ESC_B": ecodes.BTN_MISC + 26,
    "SC_KEY_FRONT_B": ecodes.BTN_MISC + 27, "SC_KEY_RIGHT_B": ecodes.BTN_MISC + 28,
    "SC_KEY_TOP_B": ecodes.BTN_MISC + 29, "SC_KEY_FIT_B": ecodes.BTN_MISC + 30,
    "SC_KEY_2D3D_B": ecodes.BTN_MISC + 31, 
}


# Mapping of SpaceControl high-level event values to evdev button codes for 3D mouse.
HIGH_LEVEL_EVENT_MAP_FOR_UINPUT = {
    0x20009: ecodes.BTN_SIDE,    # DEV_FRONT
    0x2000A: ecodes.BTN_EXTRA,   # DEV_RIGHT
    0x2000B: ecodes.BTN_FORWARD,   # DEV_TOP
    0x2000C: ecodes.BTN_GEAR_UP,   # DEV_FIT
    0x20016: ecodes.BTN_SIDE + 1, # DEV_BACK
    0x20017: ecodes.BTN_EXTRA + 1, # DEV_LEFT
    0x20018: ecodes.BTN_FORWARD + 1, # DEV_BOTTOM

    0x2000D: ecodes.BTN_LEFT,  # DEV_WHEEL_LEFT
    0x2000E: ecodes.BTN_RIGHT, # DEV_WHEEL_RIGHT

    0x2000F: ecodes.BTN_MISC + 34, # EVT_HNDL_SENS_DLG
    0x20010: ecodes.BTN_MISC + 35, # EVT_HNDL_THRESH_DLG
    0x20011: ecodes.BTN_MISC + 36, # EVT_HNDL_LCD_DLG
    0x20012: ecodes.BTN_MISC + 37, # EVT_HNDL_LEDS_DLG
    0x20013: ecodes.BTN_MISC + 38, # EVT_APPL_IN_FRGRND
    0x20014: ecodes.BTN_MISC + 39, # EVT_HNDL_KBD_DLG
    0x20015: ecodes.BTN_MISC + 40, # EVT_HNDL_WFL_DLG
    0x20019: ecodes.BTN_MISC + 41, # DEV_CTRL

    # Error and basic settings events are not typically mapped to virtual device buttons.
}

# Combine all unique button codes for 3D Mouse UInput capabilities
ALL_3DMOUSE_UINPUT_BUTTONS = list(set(list(EVDEV_3DMOUSE_LOW_LEVEL_BUTTON_MAP.values()) + list(HIGH_LEVEL_EVENT_MAP_FOR_UINPUT.values())))


# Gamepad specific button mappings
EVDEV_GAMEPAD_BUTTON_MAP = {
    "SC_KEY_1": ecodes.BTN_A,
    "SC_KEY_2": ecodes.BTN_B,
    "SC_KEY_3": ecodes.BTN_X,
    "SC_KEY_4": ecodes.BTN_Y,
    "SC_KEY_5": ecodes.BTN_TL, # Left Shoulder
    "SC_KEY_6": ecodes.BTN_TR, # Right Shoulder
    "SC_KEY_CTRL": ecodes.BTN_SELECT,
    "SC_KEY_ALT": ecodes.BTN_START,
    "SC_KEY_SHIFT": ecodes.BTN_THUMBL, # Left Stick Click
    "SC_KEY_ESC": ecodes.BTN_THUMBR,  # Right Stick Click
    "SC_KEY_FRONT": ecodes.BTN_DPAD_UP, # D-pad up
    "SC_KEY_RIGHT": ecodes.BTN_DPAD_RIGHT, # D-pad right
    "SC_KEY_TOP": ecodes.BTN_DPAD_DOWN, # D-pad down (for consistency in mapping, top -> down is arbitrary)
    "SC_KEY_FIT": ecodes.BTN_DPAD_LEFT, # D-pad left
    "SC_KEY_2D3D": ecodes.BTN_TRIGGER_HAPPY1, # Generic additional button
    "SC_KEY_1_B": ecodes.BTN_TRIGGER_HAPPY4, # More generic buttons
    "SC_KEY_2_B": ecodes.BTN_TRIGGER_HAPPY5,
    "SC_KEY_3_B": ecodes.BTN_TRIGGER_HAPPY6,
    "SC_KEY_4_B": ecodes.BTN_TRIGGER_HAPPY7,
    "SC_KEY_5_B": ecodes.BTN_TRIGGER_HAPPY8,
    "SC_KEY_6_B": ecodes.BTN_TRIGGER_HAPPY9,
    "SC_KEY_CTRL_B": ecodes.BTN_TRIGGER_HAPPY10,
    "SC_KEY_ALT_B": ecodes.BTN_TRIGGER_HAPPY11,
    "SC_KEY_SHIFT_B": ecodes.BTN_TRIGGER_HAPPY12,
    "SC_KEY_ESC_B": ecodes.BTN_TRIGGER_HAPPY13,
    "SC_KEY_FRONT_B": ecodes.BTN_TRIGGER_HAPPY14,
    "SC_KEY_RIGHT_B": ecodes.BTN_TRIGGER_HAPPY15,
    "SC_KEY_TOP_B": ecodes.BTN_TRIGGER_HAPPY16,
    "SC_KEY_FIT_B": ecodes.BTN_TRIGGER_HAPPY17,
    "SC_KEY_2D3D_B": ecodes.BTN_TRIGGER_HAPPY18,

    # Mapping high-level DEV_WHEEL_LEFT/RIGHT to gamepad buttons
    "SC_DEV_WHEEL_LEFT": ecodes.BTN_TL2, # Left Trigger 2 (often for secondary actions)
    "SC_DEV_WHEEL_RIGHT": ecodes.BTN_TR2, # Right Trigger 2 (often for secondary actions)

    "SC_EVT_HNDL_SENS_DLG": ecodes.BTN_TRIGGER_HAPPY19,
    "SC_EVT_HNDL_THRESH_DLG": ecodes.BTN_TRIGGER_HAPPY20,
    "SC_EVT_HNDL_LCD_DLG": ecodes.BTN_TRIGGER_HAPPY21,
    "SC_EVT_HNDL_LEDS_DLG": ecodes.BTN_TRIGGER_HAPPY22,
    "SC_EVT_APPL_IN_FRGRND": ecodes.BTN_TRIGGER_HAPPY23,
    "SC_EVT_HNDL_KBD_DLG": ecodes.BTN_TRIGGER_HAPPY24,
    "SC_EVT_HNDL_WFL_DLG": ecodes.BTN_TRIGGER_HAPPY25,
    "SC_DEV_CTRL": ecodes.BTN_TRIGGER_HAPPY26,
}

ALL_GAMEPAD_UINPUT_BUTTONS = list(EVDEV_GAMEPAD_BUTTON_MAP.values())

# SpaceController button bit positions (for decoding 'event' field as bitmask)
# This mapping assumes a 1-to-1 correspondence with the bit position in the 'event' field.
# IMPORTANT: Panel and Menu buttons have fixed internal daemon functions and should not be
# attempted to be remapped by our script to avoid conflicts.
BUTTON_BIT_MAP = {
    0: "SC_KEY_1", 1: "SC_KEY_2", 2: "SC_KEY_3", 3: "SC_KEY_4", 4: "SC_KEY_5",
    5: "SC_KEY_6", 6: "SC_KEY_CTRL", 7: "SC_KEY_ALT", 8: "SC_KEY_SHIFT",
    9: "SC_KEY_ESC", 10: "SC_KEY_FRONT", 11: "SC_KEY_RIGHT", 12: "SC_KEY_TOP",
    13: "SC_KEY_FIT", 14: "SC_KEY_2D3D", 
    # 15: "SC_KEY_PANEL", # Removed as it is a high-level event used by the device
    # 16: "SC_KEY_MENU",  # Removed as it is a high-level event used by the device
    17: "SC_KEY_1_B", 18: "SC_KEY_2_B", 19: "SC_KEY_3_B", 20: "SC_KEY_4_B",
    21: "SC_KEY_5_B", 22: "SC_KEY_6_B", 23: "SC_KEY_CTRL_B", 24: "SC_KEY_ALT_B",
    25: "SC_KEY_SHIFT_B", 26: "SC_KEY_ESC_B", 27: "SC_KEY_FRONT_B",
    28: "SC_KEY_RIGHT_B", 29: "SC_KEY_TOP_B", 30: "SC_KEY_FIT_B",
    31: "SC_KEY_2D3D_B", 
}


# Helper function to decode event
def decode_event(event_value):
    # Check if the value is a known event ID in the consolidated map
    if event_value in EVENT_ID_TO_NAME:
        return EVENT_ID_TO_NAME[event_value]
    
    # Handle low-level button event bitmasks
    # These are typically positive integers less than the first high-level event (0x20000).
    # We use HIGH_LEVEL_EVENT_THRESHOLD as the upper bound for these bitmask events.
    if event_value > 0 and event_value < HIGH_LEVEL_EVENT_THRESHOLD: 
        pressed_buttons = []
        for bit_position, sc_button_name in BUTTON_BIT_MAP.items():
            if (event_value >> bit_position) & 1:
                pressed_buttons.append(sc_button_name)
        return f"Key event: {' + '.join(pressed_buttons)}" if pressed_buttons else f"Key event {event_value}"
    
    # Default case for unknown values
    return f"Unknown event {event_value}"


# --- Daemon Communication Class ---
class ScDaemonComm:
    def __init__(self, sc_dll):
        self.sc_dll = sc_dll
        self._is_connected = False
        self._dev_count = 0 
        self._used_dev_count = 0 
        self._max_dev_idx = 0 
        logger.info("Initializing daemon communication interface.")

        # Define function prototypes for ctypes
        # scConnect2 signature from ScDllWrapper.java: connect2(ScOneBoolean, ScOneString)
        self.sc_dll.scConnect2.argtypes = [
            ctypes.c_bool,      # isAlwaysReceivingData flag
            ctypes.c_char_p     # application name string (NULL for anonymous)
        ]
        self.sc_dll.scConnect2.restype = ctypes.c_int # Returns an int status
        self.sc_dll.scDisconnect.argtypes = []
        self.sc_dll.scDisconnect.restype = ctypes.c_int
        self.sc_dll.scGetDevNum.argtypes = [
            ctypes.POINTER(ctypes.c_int), 
            ctypes.POINTER(ctypes.c_int), 
            ctypes.POINTER(ctypes.c_int)  
        ]
        self.sc_dll.scGetDevNum.restype = ctypes.c_int
        self.sc_dll.scFetchStdData.argtypes = [
            ctypes.c_int,           # devIdx
            ctypes.POINTER(ctypes.c_short), # mX
            ctypes.POINTER(ctypes.c_short), # mY
            ctypes.POINTER(ctypes.c_short), # mZ
            ctypes.POINTER(ctypes.c_short), # mA
            ctypes.POINTER(ctypes.c_short), # mB
            ctypes.POINTER(ctypes.c_short), # mC
            ctypes.POINTER(ctypes.c_int),   # mTraLmh
            ctypes.POINTER(ctypes.c_int),   # mRotLmh
            ctypes.POINTER(ctypes.c_int),   # event
            ctypes.POINTER(ctypes.c_long),  # mTvSec
            ctypes.POINTER(ctypes.c_long)   # mTvUsec
        ]
        self.sc_dll.scFetchStdData.restype = ctypes.c_int
        logger.info("Function prototypes defined based on spc_ctrlr.h and ScDllWrapper.")

    def connect(self): 
        """
        Establishes the connection to the SpaceControl daemon using scConnect2.
        'applName' is passed as NULL for anonymous connection.
        'isAlwaysReceivingData' is hardcoded to True as it's typically required.
        """
        # Pass ctypes.c_char_p(None) to explicitly send a C NULL for the application name.
        # Hardcode is_always_receiving_data to True.
        logger.info(f"Connecting using scConnect2 with anonymous application name (NULL) and isAlwaysReceivingData=True.")
        
        sc_status = self.sc_dll.scConnect2(True, ctypes.c_char_p(None)) 
        
        if sc_status == 0:
            self._is_connected = True
            logger.info("Successfully connected to daemon via scConnect2.")
            
            dev_num_p = ctypes.c_int(0)
            used_dev_num_p = ctypes.c_int(0)
            max_dev_idx_p = ctypes.c_int(0)

            status_get_dev_num = self.sc_dll.scGetDevNum(
                ctypes.byref(dev_num_p), 
                ctypes.byref(used_dev_num_p), 
                ctypes.byref(max_dev_idx_p)
            )
            
            if status_get_dev_num == 0:
                self._dev_count = dev_num_p.value
                self._used_dev_count = used_dev_num_p.value
                self._max_dev_idx = max_dev_idx_p.value
                logger.info(f"Detected {self._dev_count} SpaceControl device(s). Used: {self._used_dev_count}, Max Index: {self._max_dev_idx}")
            else:
                logger.error(f"scGetDevNum() failed with status: {status_get_dev_num} ({decode_event(status_get_dev_num)})")
                self._is_connected = False # Disconnect if device count retrieval fails

            return self._is_connected
        else:
            self._is_connected = False
            logger.error(f"Failed to connect to daemon via scConnect2. Connection status: {sc_status} ({decode_event(sc_status)})")
            return False

    def disconnect(self):
        if self._is_connected:
            self.sc_dll.scDisconnect()
            self._is_connected = False
            logger.info("Disconnected from daemon.")

    def get_device_count(self):
        return self._dev_count

    def fetch_data(self, device_index):
        """Fetches data from the SpaceControl device."""
        if not self._is_connected:
            return None, 1 # Return error if not connected

        # Prepare ctypes variables for output
        x, y, z, a, b, c = (ctypes.c_short(0) for _ in range(6))
        traLmh, rotLmh, event = (ctypes.c_int(0) for _ in range(3))
        tvSec, tvUsec = (ctypes.c_long(0) for _ in range(2))

        start_time = time.perf_counter()
        sc_status = self.sc_dll.scFetchStdData(
            device_index, ctypes.byref(x), ctypes.byref(y), ctypes.byref(z),
            ctypes.byref(a), ctypes.byref(b), ctypes.byref(c),
            ctypes.byref(traLmh), ctypes.byref(rotLmh), ctypes.byref(event),
            ctypes.byref(tvSec), ctypes.byref(tvUsec)
        )
        end_time = time.perf_counter()
        # logger.debug(f"[DEBUG_TIMING] scFetchStdData took: {(end_time - start_time) * 1000:.3f} ms") # Uncomment for detailed timing logs of each fetch call


        if sc_status == 0:
            sc_data_result = {
                "x": x.value, "y": y.value, "z": z.value,
                "a": a.value, "b": b.value, "c": c.value,
                "traLmh": traLmh.value, "rotLmh": rotLmh.value,
                "event": event.value,
                "tvSec": tvSec.value, "tvUsec": tvUsec.value
            }
            return sc_data_result, 0
        else:
            return None, sc_status


# --- Shared Data Container for thread-safe access ---
class SharedSpaceControlData:
    """Thread-safe container to pass data from acquirer thread to main thread."""
    def __init__(self):
        self._data = None
        self._lock = threading.Lock()
        self._new_data_event = threading.Event()

    def set_data(self, data):
        """Sets new data and signals consumers."""
        with self._lock:
            self._data = data
            self._new_data_event.set() # Signal that new data is available

    def get_data(self, timeout=None):
        """Waits for and retrieves new data."""
        self._new_data_event.wait(timeout) # Wait for new data to be set
        with self._lock:
            data_copy = self._data.copy() if self._data else None
            self._new_data_event.clear() # Reset the event for the next data cycle
            return data_copy

# --- SpaceControl Data Acquisition Thread ---
class SpaceControlDataAcquirer(threading.Thread):
    """
    Dedicated thread to continuously acquire data from the SpaceControl daemon.
    This offloads the blocking `scFetchStdData` call from the main thread.
    """
    def __init__(self, daemon_comm, device_index, shared_data):
        super().__init__()
        self.daemon_comm = daemon_comm
        self.device_index = device_index
        self.shared_data = shared_data
        self._running = True # Flag to control thread's main loop
        logger.info("Data acquirer thread initialized.")

    def run(self):
        logger.info(f"DataAcquirer[{self.device_index}]: Starting data acquisition loop...")
        while self._running:
            data, status = self.daemon_comm.fetch_data(self.device_index)
            # Log the raw data and status for debugging purposes
            # Always log data if it's not None, regardless of status.
            if data:
                logger.debug(f"DataAcquirer[{self.device_index}]: Fetched data (raw): {data}, Status: {status} ({decode_event(status)})")
            else:
                logger.debug(f"DataAcquirer[{self.device_index}]: Fetched data: None, Status: {status} ({decode_event(status)})")

            if status == 0 and data:
                self.shared_data.set_data(data)
            # If status is not 0 (SC_OK) AND not a "NOTHING_CHANGED" event value (1 or -1), then it's an error.
            # We explicitly check for 1 and -1 here because decode_event maps them to "NOTHING_CHANGED".
            # Any other non-zero status is a genuine error.
            elif status != 0 and status != 1 and status != -1: 
                logger.error(f"DataAcquirer[{self.device_index}]: scFetchStdData() returned error status: {status} ({decode_event(status)})")
            # If status is 1 or -1, it's NOTHING_CHANGED, which is expected when no movement.
            elif status == 1 or status == -1:
                logger.debug(f"DataAcquirer[{self.device_index}]: No new data (NOTHING_CHANGED), as expected. Status: {status} ({decode_event(status)})")

        logger.info(f"DataAcquirer[{self.device_index}]: Data acquisition loop ended.")

    def stop(self):
        """Signals the thread to stop its execution."""
        self._running = False

# --- Base Virtual Controller Class ---
class BaseVirtualController:
    """
    Base class for creating virtual evdev input devices (3D mouse or gamepad).
    Handles common UInput setup and axis event generation.
    """
    def __init__(self, device_index, uinput_name, uinput_vendor_id, uinput_product_id, all_uinput_buttons):
        self.device_index = device_index
        self.uinput_device = None
        # Store last axis values to send events only on change
        self.last_axis_values = {
            "x": 0, "y": 0, "z": 0,
            "a": 0, "b": 0, "c": 0
        }
        self.log_source = self.__class__.__name__

        self._setup_uinput(uinput_name, uinput_vendor_id, uinput_product_id, all_uinput_buttons)

    def _setup_uinput(self, uinput_name, uinput_vendor_id, uinput_product_id, all_uinput_buttons):
        """Sets up the virtual UInput device capabilities."""
        capabilities = {
            ecodes.EV_ABS: [
                # Define 3 translational axes (X, Y, Z) and 3 rotational axes (RX, RY, RZ)
                # Max/min values cover the typical range of SpaceControl data
                (ecodes.ABS_X, AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Z, AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RX, AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)), 
                (ecodes.ABS_RY, AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)), 
                (ecodes.ABS_RZ, AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=0, resolution=0)), 
            ],
            ecodes.EV_KEY: all_uinput_buttons, # All possible buttons for this device
        }

        try:
            self.uinput_device = UInput(
                capabilities, 
                name=uinput_name,
                vendor=uinput_vendor_id,
                product=uinput_product_id,
                bustype=ecodes.BUS_USB
            )
            logger.info(f"{self.log_source}: Virtual device '{uinput_name}' created successfully with Vendor: {hex(uinput_vendor_id)}, Product: {hex(uinput_product_id)}.")
            return True
        except Exception as e:
            logger.error(f"{self.log_source}: Failed to create uinput device: {e}")
            logger.error(f"{self.log_source}: Error type: {type(e).__name__}, Message: {e}")
            logger.error(f"{self.log_source}: Ensure 'uinput' kernel module is loaded and you have permissions (e.g., in 'input' group).")
            return False

    def update(self, data):
        """
        Processes raw SpaceControl data and sends axis events via UInput.
        Returns whether motion occurred and the scaled axis values.
        """
        if not self.uinput_device:
            return False, {} # Indicate failure to update if device not ready

        # Direct mapping: We assume the SpaceControl driver has already applied any remapping
        # based on its loaded configuration file (e.g., FreeCAD.cfg.txt).
        # Our script simply forwards the values it receives from the driver.
        current_axis_values = {
            "x": int(data["x"] * AXIS_SCALE), 
            "y": int(data["y"] * AXIS_SCALE), 
            "z": int(data["z"] * AXIS_SCALE),
            "a": int(data["a"] * AXIS_SCALE), 
            "b": int(data["b"] * AXIS_SCALE), 
            "c": int(data["c"] * AXIS_SCALE)
        }

        motion_changed = False
        # Send axis events only if the value has changed from the last known value
        evdev_abs_map = {
            "x": ecodes.ABS_X, "y": ecodes.ABS_Y, "z": ecodes.ABS_Z,
            "a": ecodes.ABS_RX, "b": ecodes.ABS_RY, "c": ecodes.ABS_RZ
        }

        for axis, value in current_axis_values.items():
            if value != self.last_axis_values[axis]:
                self.uinput_device.write(ecodes.EV_ABS, evdev_abs_map[axis], value)
                motion_changed = True
        
        self.last_axis_values.update(current_axis_values)
        return motion_changed, current_axis_values

    def close(self):
        """Closes the virtual UInput device."""
        if self.uinput_device:
            self.uinput_device.close()
            logger.info(f"{self.log_source}: Virtual device closed.")


# --- Virtual 3D Mouse Controller ---
class Virtual3DMouseController(BaseVirtualController):
    """
    Manages the virtual 3D mouse device, handling both axis and button events.
    Prioritizes high-level events over low-level bitmask buttons if both are present.
    """
    def __init__(self, device_index):
        super().__init__(device_index, UINPUT_3DMOUSE_NAME, UINPUT_3DMOUSE_VENDOR_ID, UINPUT_3DMOUSE_PRODUCT_ID, ALL_3DMOUSE_UINPUT_BUTTONS)
        self.last_low_level_button_state = {} # To track state of bitmask buttons
        self.last_high_level_event_state = None # To track state of high-level events (only one can be active at a time)
        logger.info(f"{self.log_source}: 3D Mouse controller specific initialization complete.")

    def update(self, data):
        """
        Updates the 3D mouse virtual device with new data.
        Handles both axis motion and button presses (low-level bitmask and high-level events).
        """
        motion_changed, current_axis_values = super().update(data)
        if not self.uinput_device:
            return

        # Log motion if it changes and is not zero
        if motion_changed and any(val != 0 for val in current_axis_values.values()):
            logger.info(f"{self.log_source}: Sending Motion: X={current_axis_values['x']} Y={current_axis_values['y']} Z={current_axis_values['z']} | "
                       f"RX={current_axis_values['a']} RY={current_axis_values['b']} RZ={current_axis_values['c']}")

        current_event_value = data["event"]
        is_any_axis_moving = any(abs(val) > 0 for val in current_axis_values.values())

        # --- Handle High-Level (DEV_*) Events ---
        # These are special events sent by the daemon, typically triggered by specific button combinations
        # or special cap gestures (e.g., "Fit" view). They are mutually exclusive with low-level buttons
        # when a high-level event occurs.
        current_high_level_event = None
        # Only consider high-level events if no significant axis motion
        if current_event_value >= HIGH_LEVEL_EVENT_THRESHOLD and not is_any_axis_moving:
            current_high_level_event = current_event_value

        # Release the previous high-level event if it's no longer active
        if self.last_high_level_event_state is not None and \
           self.last_high_level_event_state != current_high_level_event and \
           self.last_high_level_event_state in HIGH_LEVEL_EVENT_MAP_FOR_UINPUT: 
            evdev_button_code_to_release = HIGH_LEVEL_EVENT_MAP_FOR_UINPUT.get(self.last_high_level_event_state)
            if evdev_button_code_to_release is not None:
                self.uinput_device.write(ecodes.EV_KEY, evdev_button_code_to_release, 0)
                logger.info(f"{self.log_source}: High-level event {decode_event(self.last_high_level_event_state)} (evdev {evdev_button_code_to_release}) RELEASED")
        
        # Press the current high-level event if it's new and active
        if current_high_level_event is not None and \
           current_high_level_event != self.last_high_level_event_state and \
           current_high_level_event in HIGH_LEVEL_EVENT_MAP_FOR_UINPUT:
            evdev_button_code = HIGH_LEVEL_EVENT_MAP_FOR_UINPUT.get(current_high_level_event)
            if evdev_button_code is not None:
                self.uinput_device.write(ecodes.EV_KEY, evdev_button_code, 1)
                logger.info(f"{self.log_source}: High-level event {decode_event(current_high_level_event)} (evdev {evdev_button_code}) PRESSED")
        
        self.last_high_level_event_state = current_high_level_event


        # --- Handle Low-Level (Bitmask) Buttons for 3D Mouse ---
        # These are the physical buttons on the device, represented by a bitmask in the event field.
        # They are only processed if no high-level event is active.
        current_low_level_button_names = set()
        # Process bitmask only if event value is within expected low-level range and no high-level event or motion
        if current_event_value > 0 and current_event_value < HIGH_LEVEL_EVENT_THRESHOLD and \
           current_high_level_event is None and not is_any_axis_moving:
            for bit_position, sc_button_name in BUTTON_BIT_MAP.items():
                if (current_event_value >> bit_position) & 1:
                    current_low_level_button_names.add(sc_button_name)

        # Iterate through all possible low-level buttons and update their state
        for sc_button_name in BUTTON_BIT_MAP.values():
            if sc_button_name in EVDEV_3DMOUSE_LOW_LEVEL_BUTTON_MAP:
                evdev_button_code = EVDEV_3DMOUSE_LOW_LEVEL_BUTTON_MAP[sc_button_name]
                
                is_currently_pressed = sc_button_name in current_low_level_button_names
                was_previously_pressed = self.last_low_level_button_state.get(sc_button_name, False)

                if is_currently_pressed and not was_previously_pressed:
                    self.uinput_device.write(ecodes.EV_KEY, evdev_button_code, 1)
                    logger.info(f"{self.log_source}: Low-level Button {sc_button_name} (evdev {evdev_button_code}) PRESSED")
                elif not is_currently_pressed and was_previously_pressed:
                    self.uinput_device.write(ecodes.EV_KEY, evdev_button_code, 0)
                    logger.info(f"{self.log_source}: Low-level Button {sc_button_name} (evdev {evdev_button_code}) RELEASED")
                
                self.last_low_level_button_state[sc_button_name] = is_currently_pressed
        
        self.uinput_device.syn() # Synchronize events

# --- Virtual Gamepad Controller ---
class VirtualGamepadController(BaseVirtualController):
    """
    Manages the virtual gamepad device, handling both axis and button events.
    Maps all SpaceControl buttons to standard gamepad buttons.
    """
    def __init__(self, device_index):
        super().__init__(device_index, UINPUT_GAMEPAD_NAME, UINPUT_GAMEPAD_VENDOR_ID, UINPUT_GAMEPAD_PRODUCT_ID, ALL_GAMEPAD_UINPUT_BUTTONS)
        self.last_button_state = {} # To track state of gamepad buttons
        self.last_high_level_event_state = None # Track high-level event for gamepad
        logger.info(f"{self.log_source}: Gamepad controller specific initialization complete.")

    def update(self, data):
        """
        Updates the gamepad virtual device with new data.
        Handles axis motion and all button presses (low-level bitmask and high-level events).
        """
        motion_changed, current_axis_values = super().update(data)
        if not self.uinput_device:
            return

        # Gamepad logging with custom axis names for clarity
        if motion_changed and any(val != 0 for val in current_axis_values.values()):
            logger.info(f"{self.log_source}: Sending Gamepad Motion: X-Trans={current_axis_values['x']} Y-Trans={current_axis_values['y']} Z-Trans={current_axis_values['z']} | "
                       f"Roll={current_axis_values['a']} Pitch={current_axis_values['b']} Yaw={current_axis_values['c']}") 

        current_event_value = data["event"]
        is_any_axis_moving = any(abs(val) > 0 for val in current_axis_values.values())

        # --- Handle High-Level (DEV_*) Events for Gamepad ---
        # Explicitly map DEV_WHEEL_LEFT/RIGHT to gamepad buttons
        current_high_level_event = None
        if current_event_value >= HIGH_LEVEL_EVENT_THRESHOLD and not is_any_axis_moving:
            current_high_level_event = current_event_value

        # Release the previous high-level event if no longer active
        if self.last_high_level_event_state is not None and \
           self.last_high_level_event_state != current_high_level_event:
            
            # Get the descriptive string from EVENT_ID_TO_NAME, then derive the gamepad map key.
            event_name_from_map = EVENT_ID_TO_NAME.get(self.last_high_level_event_state)
            gamepad_map_key = None
            if event_name_from_map == "DEV_WHEEL_LEFT":
                gamepad_map_key = "SC_DEV_WHEEL_LEFT"
            elif event_name_from_map == "DEV_WHEEL_RIGHT":
                gamepad_map_key = "SC_DEV_WHEEL_RIGHT"
            elif event_name_from_map == "DEV_CTRL":
                gamepad_map_key = "SC_DEV_CTRL"
            elif event_name_from_map in ["EVT_HNDL_SENS_DLG", "EVT_HNDL_THRESH_DLG", "EVT_HNDL_LCD_DLG", "EVT_HNDL_LEDS_DLG", "EVT_APPL_IN_FRGRND", "EVT_HNDL_KBD_DLG", "EVT_HNDL_WFL_DLG"]:
                gamepad_map_key = event_name_from_map
            
            if gamepad_map_key and gamepad_map_key in EVDEV_GAMEPAD_BUTTON_MAP:
                evdev_button_code_to_release = EVDEV_GAMEPAD_BUTTON_MAP[gamepad_map_key]
                self.uinput_device.write(ecodes.EV_KEY, evdev_button_code_to_release, 0)
                logger.info(f"{self.log_source}: High-level Event {decode_event(self.last_high_level_event_state)} (evdev {evdev_button_code_to_release}) RELEASED for Gamepad")
        
        # Press the current high-level event if it's new and active
        if current_high_level_event is not None and \
           current_high_level_event != self.last_high_level_event_state:
            
            event_name_from_map = EVENT_ID_TO_NAME.get(current_high_level_event)
            gamepad_map_key = None
            if event_name_from_map == "DEV_WHEEL_LEFT":
                gamepad_map_key = "SC_DEV_WHEEL_LEFT"
            elif event_name_from_map == "DEV_WHEEL_RIGHT":
                gamepad_map_key = "SC_DEV_WHEEL_RIGHT"
            elif event_name_from_map == "DEV_CTRL":
                gamepad_map_key = "SC_DEV_CTRL"
            elif event_name_from_map in ["EVT_HNDL_SENS_DLG", "EVT_HNDL_THRESH_DLG", "EVT_HNDL_LCD_DLG", "EVT_HNDL_LEDS_DLG", "EVT_APPL_IN_FRGRND", "EVT_HNDL_KBD_DLG", "EVT_HNDL_WFL_DLG"]:
                gamepad_map_key = event_name_from_map

            if gamepad_map_key and gamepad_map_key in EVDEV_GAMEPAD_BUTTON_MAP:
                evdev_button_code_to_press = EVDEV_GAMEPAD_BUTTON_MAP[gamepad_map_key]
                self.uinput_device.write(ecodes.EV_KEY, evdev_button_code_to_press, 1)
                logger.info(f"{self.log_source}: High-level Event {decode_event(current_high_level_event)} (evdev {evdev_button_code_to_press}) PRESSED for Gamepad")
        
        self.last_high_level_event_state = current_high_level_event


        current_pressed_bit_positions = set()
        
        # Process low-level bitmask buttons for Gamepad
        # Filter out high-level events (>= HIGH_LEVEL_EVENT_THRESHOLD) from this bitmask processing.
        if current_event_value > 0 and current_event_value < HIGH_LEVEL_EVENT_THRESHOLD and \
           current_high_level_event is None and not is_any_axis_moving:
            for bit_position, _ in BUTTON_BIT_MAP.items(): # Iterate over bit positions
                if (current_event_value >> bit_position) & 1:
                    current_pressed_bit_positions.add(bit_position)

        # Update state for all gamepad-relevant low-level buttons using the combined map
        for bit_position, evdev_button_code in GAMEPAD_BIT_TO_EVDEV_CODE.items():
            sc_button_name = BUTTON_BIT_MAP[bit_position] # Get the descriptive name for logging
                
            is_currently_pressed = bit_position in current_pressed_bit_positions
            was_previously_pressed = self.last_button_state.get(sc_button_name, False) # Track state by SC name

            if is_currently_pressed and not was_previously_pressed:
                self.uinput_device.write(ecodes.EV_KEY, evdev_button_code, 1)
                logger.info(f"{self.log_source}: Button {sc_button_name} (evdev {evdev_button_code}) PRESSED")
            elif not is_currently_pressed and was_previously_pressed:
                self.uinput_device.write(ecodes.EV_KEY, evdev_button_code, 0)
                logger.info(f"{self.log_source}: Button {sc_button_name} (evdev {evdev_button_code}) RELEASED")
            
            self.last_button_state[sc_button_name] = is_currently_pressed # Update state by SC name
        
        self.uinput_device.syn() # Synchronize events


# --- Main Execution Block ---
if __name__ == "__main__":
    setup_logging(LOGLEVEL)
    logger.info("--- SpaceControl Dual Virtual Device Bridge ---")
    logger.info("This script creates two virtual devices: a 3D mouse (for spacenavd) and a generic gamepad, using a single data acquisition thread.")
    logger.info("Ensure 'uinput' kernel module is loaded and you have permissions to /dev/uinput (e.g., in 'input' group).")
    logger.info("Also, ensure the SpaceControl daemon/driver is running in the background.")

    # Determine config file path from command line arguments
    config_to_load = None
    if len(sys.argv) > 1:
        config_to_load = sys.argv[1]
        if not os.path.exists(config_to_load):
            logger.warning(f"Warning: Specified config file '{config_to_load}' not found. Daemon will likely load its default.")
            config_to_load = None # Revert to None if file doesn't exist

    # Check if the SpaceControl library exists at the specified path
    if not os.path.exists(SC_LIB_PATH):
        logger.error(f"Error: SpaceControl shared library not found at {SC_LIB_PATH}")
        sys.exit(1)

    try:
        # Load the shared library
        sc_dll = ctypes.CDLL(SC_LIB_PATH)
        logger.info(f"Successfully loaded library: {SC_LIB_PATH}")

        daemon_comm = ScDaemonComm(sc_dll)

        if not daemon_comm.connect():
            logger.error("Could not establish connection with SpaceControl daemon.")
            logger.error("Please ensure the SpaceControl daemon/driver is running in the background.")
            sys.exit(1)

        # Check for connected devices
        if daemon_comm.get_device_count() == 0:
            logger.info("No SpaceControl devices detected by the daemon.")
            logger.info("Ensure your device is plugged in and recognized by the SpaceControl GUI/driver.")
            daemon_comm.disconnect()
            sys.exit(0) # Exit gracefully if no device is found

        shared_data_container = SharedSpaceControlData()

        # Start the single data acquisition thread for the first device (index 0)
        data_acquirer_thread = SpaceControlDataAcquirer(daemon_comm, 0, shared_data_container)
        data_acquirer_thread.start()
        logger.info("SpaceControl data acquisition thread started.")

        # Initialize virtual device controllers based on enablement flags
        mouse_controller = None
        gamepad_controller = None

        if ENABLE_3DMOUSE_VIRTUAL_DEVICE:
            mouse_controller = Virtual3DMouseController(0)
            logger.info("Virtual 3D Mouse controller initialized.")
        else:
            logger.info("Virtual 3D Mouse functionality is DISABLED by configuration.")

        if ENABLE_GAMEPAD_VIRTUAL_DEVICE:
            gamepad_controller = VirtualGamepadController(0)
            logger.info("Virtual Gamepad controller initialized.")
        else:
            logger.info("Virtual Gamepad functionality is DISABLED by configuration.")
        
        if not (ENABLE_3DMOUSE_VIRTUAL_DEVICE or ENABLE_GAMEPAD_VIRTUAL_DEVICE):
            logger.warning("WARNING: Both virtual devices are disabled. No input will be sent.")

        logger.info("Virtual device bridge running. Move SpaceController or press buttons.")
        logger.info("Test the 3D mouse in applications like Blender or FreeCAD (ensure spacenavd is running in debug mode).")
        logger.info("Test the gamepad with `jstest /dev/input/jsX` (replace X with the appropriate number) or in games.")
        logger.info("Press Ctrl+C to stop.")

        # Main loop to fetch new data from the acquirer thread and dispatch it
        try:
            while True:
                # Wait for new data from the acquirer thread with a timeout
                new_data = shared_data_container.get_data(timeout=0.5) 
                if new_data:
                    if mouse_controller:
                        mouse_controller.update(new_data)
                    if gamepad_controller:
                        gamepad_controller.update(new_data)
                else:
                    # If no new data in timeout, it means the acquirer might be stuck or device inactive.
                    # Continue the loop, but avoid excessive CPU usage by the `get_data` timeout.
                    pass 

        except KeyboardInterrupt:
            logger.info("Ctrl+C detected. Stopping all components.")
            # Clean up threads and devices
            data_acquirer_thread.stop()
            data_acquirer_thread.join() # Wait for the data acquisition thread to finish
            if mouse_controller:
                mouse_controller.close()
            if gamepad_controller:
                gamepad_controller.close()
            
            logger.info("Disconnecting from daemon.")
            daemon_comm.disconnect()
            logger.info("Script terminated.")

    except OSError as e:
        logger.error(f"OS Error loading library: {e}. Check library path and permissions (e.g., chmod 755).")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for debugging unexpected errors
        sys.exit(1)
