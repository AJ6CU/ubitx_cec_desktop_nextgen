
import json
import os
import platform
import threading
import tkinter as tk
from tkinter import messagebox
import globalvars as gv
from defaultubitx_cec_desktop import default_config_data




class ConfigurationManager:
    def __init__(self,Master=None):
        """
                Initializes the application configuration settings provider.
                Dynamically targets a hidden user-space config file in the user's home directory.
                """
        self.observers = {}
        # Targets: /home/username/.ubitx_cec_desktop.ini safely across Linux, Windows, and Mac
        self.configuration_file = os.path.expanduser(os.path.join("~", ".ubitx_cec_desktop.ini"))
        self.config_data = {}
        self.lock = threading.Lock()  # Thread-safe wrapper preventing race conditions
        self.loadConfig()



    def loadConfig(self):
        """Loads configuration from disk, falling back to Python dictionary defaults if missing/corrupt."""
        if os.path.exists(self.configuration_file):
            try:
                with open(self.configuration_file, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[-] Config parse error: {e}. Falling back to baseline defaults.")
                self.config_data = default_config_data.copy()
        else:
            print(f"[+] Creating fresh configuration profile at: {self.configuration_file}")
            self.config_data = default_config_data.copy()
            self.saveConfig()

    def saveConfig(self):
        """Thread-safely serializes and flushes data pool to disk via JSON formatting."""
        with self.lock:
            try:
                with open(self.configuration_file, 'w', encoding='utf-8') as config_file:
                    json.dump(self.config_data, config_file, indent=4, sort_keys=True)
            except IOError as e:
                print(f"[-] Critical Error writing configuration profile to disk: {e}")

    def register_observer(self, configParameter, observerMethod):
        if self.observers.get(configParameter) is not None:

            self.observers[configParameter].extend([observerMethod])
        else:
            self.observers[configParameter] = [observerMethod]


    def unregister_observer(self, configParameter, observerMethod):
        if self.observers.get(configParameter) is not None:
            if observerMethod in self.observers[configParameter]:
                self.observers[configParameter].remove(observerMethod)


    def _notify_observers(self, configParameter,value):
        if configParameter in self.observers:
            for observerMethod in self.observers[configParameter]:
                observerMethod(value)
    #
    # def distributeConfigData(self):
    #     gv.NUMBER_DELIMITER = self.get_NUMBER_DELIMITER()
    #     print("delimiter number is in distri", gv.NUMBER_DELIMITER)
    #     self.register_observer("NUMBER DELIMITER", gv.updateNUMBER_DELIMITER)

    def getValueOrDefault(self, configParameter):
        if configParameter in self.config_data:
            return self.config_data[configParameter]
        else:
            self.config_data[configParameter] = default_config_data[configParameter]
            self.saveConfig()
            return self.config_data[configParameter]

    # ------------------------------------------------------------------
    # The rig's connection
    # ------------------------------------------------------------------
    def get_rig_port(self) -> str:
        """
        Where the rig is: a serial device -- "/dev/cu.usbserial-A5069RR4",
        "COM3" -- or a network rig as "socket://host:port". One setting, since
        one of them is in use and the prefix says which.
        """
        return str(self.getValueOrDefault("Rig Port"))

    def set_rig_port(self, port: str):
        self.config_data["Rig Port"] = str(port).strip()
        self.saveConfig()
        self._notify_observers("Rig Port", port)

    def get_rig_baud(self) -> int:
        """The rig's serial speed. 57600 is what KD8CEC firmware uses."""
        return int(self.getValueOrDefault("Rig Baud"))

    def set_rig_baud(self, baud: int):
        self.config_data["Rig Baud"] = int(baud)
        self.saveConfig()

    def get_MCU_Command_Headroom(self):
        return self.getValueOrDefault("MCU Command Headroom")

    def set_MCU_Command_Headroom(self, value):
        self.config_data["MCU Command Headroom"] = value
        self._notify_observers("MCU Command Headroom", value)
        self.saveConfig()

    def get_MCU_Update_Period(self):
        return self.getValueOrDefault("MCU Update Period")

    def set_MCU_Update_Period(self, value):
        self.config_data["MCU Update Period"] = value
        self._notify_observers("MCU Update Period", value)
        self.saveConfig()

    def get_MCU_Read_Wait_Period(self):
        return self.getValueOrDefault("MCU Read Wait Period")

    def set_MCU_Read_Wait_Period(self, value):
        self.config_data["MCU Read Wait Period"] = value
        self.saveConfig()

    def get_PWR_SWR_Switch(self):
        return self.getValueOrDefault("PWR SWR")

    def set_PWR_SWR_Switch(self, value):
        self.config_data["PWR SWR"] = value
        self.saveConfig()


    def get_SWR_Factor(self):
        return self.getValueOrDefault("SWR Factor")

    def set_SWR_Factor(self, value):
        self.config_data["SWR Factor"] = value
        self.saveConfig()



    def get_PWR_Factor(self):
        return self.getValueOrDefault("PWR Factor")

    def set_PWR_Factor(self, value):
        self.config_data["PWR Factor"] = value
        self.saveConfig()


    def get_NUMBER_DELIMITER(self):
        return self.getValueOrDefault("NUMBER DELIMITER")

    def set_NUMBER_DELIMITER(self, value):
        self.config_data["NUMBER DELIMITER"] = value
        self._notify_observers("NUMBER DELIMITER", value)
        self.saveConfig()

    def get_VFO_Touch_Optimized(self):
        return self.getValueOrDefault("VFO Touch Optimized")

    def set_VFO_Touch_Optimized(self, value):
        self.config_data["VFO Touch Optimized"] = value
        self._notify_observers("VFO Touch Optimized", value)
        self.saveConfig()


    def get_Master_Cal(self):
        return self.getValueOrDefault("Master Cal")

    def set_Master_Cal(self,value):
        self.config_data ["Master Cal"] = value
        self.saveConfig()

    def get_SSB_BFO(self):
        return self.getValueOrDefault("SSB BFO")

    def set_SSB_BFO(self, value):
        self.config_data["SSB BFO"] = value
        self.saveConfig()

    def get_CW_BFO(self):
        return self.getValueOrDefault("CW BFO")

    def set_CW_BFO(self, value):
        self.config_data["CW BFO"] = value
        self.saveConfig()


    def get_CW_Tone(self):
        return self.getValueOrDefault("CW Tone")

    def set_CW_Tone(self, value):
        self.config_data["CW Tone"] = value
        self.saveConfig()


    def get_CW_Speed(self):
        return self.config_data["CW Speed"]

    def set_CW_Speed(self, value):
        self.config_data["CW Speed"] = value
        self.saveConfig()

    def get_VFOA_Copy(self):
        return self.getValueOrDefault("CW Copy VFOA to VFOB on Split")

    def set_VFOA_Copy(self, value):
        self.config_data["CW Copy VFOA to VFOB on Split"] = value
        self.saveConfig()


    def get_Keytype(self):
        return self.getValueOrDefault("CW Key Type")

    def set_Keytype(self, value):
        self.config_data["CW Key Type"] = value
        self.saveConfig()


    def get_CW_Delay_Before_TX(self):
        return self.getValueOrDefault("CW Delay Before TX")

    def set_CW_Delay_Before_TX(self, value):
        self.config_data["CW Delay Before TX"] = value
        self.saveConfig()


    def get_CW_Delay_Returning_to_RX(self):
        return self.getValueOrDefault("CW Delay Returning to RX")

    def set_CW_Delay_Returning_to_RX(self, value):
        self.config_data["CW Delay Returning to RX"] = value
        self.saveConfig()

    def get_Virtual_Keyboard_Switch(self):
        return self.getValueOrDefault("Virtual Keyboard Switch")

    def set_Virtual_Keyboard_Switch(self, value):
        self.config_data["Virtual Keyboard Switch"] = value
        self.saveConfig()

    def get_DSP_Switch(self):
        return self.getValueOrDefault("DSP")

    def set_DSP_Switch(self, value):
        self.config_data["DSP"] = value
        self.saveConfig()

    # ------------------------------------------------------------------
    # The SDR
    # ------------------------------------------------------------------
    def get_sdr_software(self) -> str:
        """
        Which SDR program: "sdr++", "gqrx", "rigctld" -- or "none".

        "none" is how the operator says there is no SDR, and the only way:
        the old separate "SDR" switch is gone, because a switch and a name
        can disagree about whether there is one.
        """
        return str(self.getValueOrDefault("SDR Software")).strip().lower()

    def set_sdr_software(self, sdr_software: str):
        self.config_data["SDR Software"] = str(sdr_software).strip().lower()
        self.saveConfig()
        self._notify_observers("SDR Software", sdr_software)

    def sdr_enabled(self) -> bool:
        """Whether an SDR is to be used at all."""
        return self.get_sdr_software() not in ("none", "")

    def get_sdr_path(self) -> str:
        """
        Where the SDR program is, when it is not where this expects.

        Empty means "look in the usual places" -- see sdr_launcher.py, which
        knows each program's normal home on each platform. This is for a
        program installed somewhere else, which on Windows is most of them.
        """
        return str(self.getValueOrDefault("SDR Path"))

    def set_sdr_path(self, path: str):
        self.config_data["SDR Path"] = str(path).strip()
        self.saveConfig()

    def get_SDR_Autostart(self) -> bool:
        """Fetches target system communication network socket connector port."""
        return self.getValueOrDefault("SDR Autostart")


    def set_SDR_Autostart(self, autostart: bool):
        """Sets target transceiver communications loop connector port and notifies observers."""
        self.config_data["SDR Autostart"] = autostart
        self.saveConfig()


    def get_Logbook_Switch(self):
        return self.getValueOrDefault("Logbook Switch")

    def set_Logbook_Switch(self, value):
        self.config_data["Logbook Switch"] = value
        self.saveConfig()


    def get_Logbook_Type(self):
        return self.getValueOrDefault("Logbook Type")

    def set_Logbook_Type(self, value):
        self.config_data["Logbook Type"] = value
        self.saveConfig()

    def get_Logbook_Backup_Interval(self):
        return self.getValueOrDefault("Logbook Backup Interval")

    def set_Logbook_Backup_Interval(self, value):
        self.config_data["Logbook Backup Interval"] = value
        self.saveConfig()


    def get_Logbook_Location(self):
        return self.getValueOrDefault("Logbook Location")

    def set_Logbook_Location(self, value):
        self.config_data["Logbook Location"] = value
        self.saveConfig()


    def get_Logbook_Name(self):
        return self.getValueOrDefault("Logbook Name")

    def set_Logbook_Name(self, value):
        self.config_data["Logbook Name"] = value
        self.saveConfig()

    def get_sdr_host(self) -> str:
        """The SDR's address -- usually 127.0.0.1, the same computer."""
        return str(self.getValueOrDefault("SDR Host"))

    def set_sdr_host(self, host: str):
        self.config_data["SDR Host"] = str(host).strip()
        self.saveConfig()
        self._notify_observers("SDR Host", host)

    def get_sdr_port(self) -> int:
        """
        The SDR's port. Each program has its own default -- 4532 for SDR++,
        7356 for Gqrx, 8091 for SDRangel -- see sdr_profiles.
        """
        return int(self.getValueOrDefault("SDR Port"))

    def set_sdr_port(self, port_val: int):
        self.config_data["SDR Port"] = int(port_val)
        self.saveConfig()
        self._notify_observers("SDR Port", port_val)

    def get_last_active_frequency(self) -> int:
        """Fetches the previous successful runtime operational base tracking frequency."""
        return int(self.getValueOrDefault("Last Active Frequency"))

    def set_last_active_frequency(self, freq_hz: int):
        """Saves current dial frequency parameter coordinates across sessions."""
        self.config_data["Last Active Frequency"] = int(freq_hz)
        self.saveConfig()
        self._notify_observers("Last Active Frequency", freq_hz)

    def get_sdr_filter_width_hz(self) -> int:
        """Pulls stored bandwidth configuration specifications."""
        return int(self.getValueOrDefault("SDR Filter Width HZ"))

    def set_sdr_filter_width_hz(self, width_hz: int):
        """Commits software intermediate-frequency bandwidth limits to memory."""
        self.config_data["SDR Filter Width HZ"] = int(width_hz)
        self.saveConfig()
        self._notify_observers("SDR Filter Width HZ", width_hz)

    def get_sdr_cw_filter_default_hz(self):
        return int(self.getValueOrDefault("SDR CW Width HZ"))

    def set_sdr_cw_filter_default_hz(self, width_hz: int):
        """Commits software intermediate-frequency bandwidth limits to memory."""
        self.config_data["SDR CW Width HZ"] = int(width_hz)
        self.saveConfig()

    def get_sdr_ssb_filter_default_hz(self):
        return int(self.getValueOrDefault("SDR SSB Width HZ"))

    def set_sdr_ssb_filter_default_hz(self, width_hz: int):
        """Commits software intermediate-frequency bandwidth limits to memory."""
        self.config_data["SDR SSB Width HZ"] = int(width_hz)
        self.saveConfig()

    def get_sdr_current_mode(self) -> str:
        """Fetches current modulation footprint identifier selection tag."""
        return str(self.getValueOrDefault("SDR Current Mode"))

    def set_sdr_current_mode(self, mode_str: str):
        """Updates internal modulation type selection mapping criteria profiles."""
        self.config_data["SDR Current Mode"] = str(mode_str).strip()
        self.saveConfig()
        self._notify_observers("SDR Current Mode", mode_str)

    def get_audio_gain_level(self) -> int:
        """Pulls audio mixer output coefficient level bounds attributes."""
        return int(self.getValueOrDefault("Audio Gain Volume Level"))

    def set_audio_gain_level(self, gain_val: int):
        """Saves operational software volume level settings constraints."""
        self.config_data["Audio Gain Volume Level"] = int(gain_val)
        self.saveConfig()
        self._notify_observers("Audio Gain Volume Level", gain_val)