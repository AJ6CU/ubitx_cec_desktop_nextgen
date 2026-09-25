# The settings this application starts from, and falls back to.
#
# Kept in ~/.ubitx_cec_desktop.ini as JSON. A key missing from that file is
# taken from here and written back, so the file fills in as it is used.
#
# THE NAMES SAY WHAT THEY HOLD. An earlier version stored the rig's port as
# "Serial Port" while "Radio IP" and "Radio Port" held the SDR's address --
# names one careless line away from wiring the rig's field to the SDR's
# setting. Those, and the separate "SDR" switch that could disagree with
# "SDR Software", are gone.
#
# So are the channel sets and the scan settings: they live in
# ~/.ubitx_cec_desktop_channels.json now -- see channel_sets.py -- because
# they are the operator's data rather than settings, and because a list of
# lists is poor fare for a settings file.

default_config_data = {
    # THE RIG. "Rig Port" holds a serial device ("/dev/cu.usbserial-A5069RR4",
    # "COM3") or a network rig ("socket://192.168.1.50:8080"); the prefix says
    # which, so no separate setting can disagree with the address. Empty means
    # not chosen yet -- the Setup tab asks.
    "Rig Port": "",
    "Rig Baud": 57600,

    # THE SDR. "none" means there is no SDR, and is how the operator says so;
    # there is no separate switch. Each program has its own usual port: 4532
    # SDR++, 7356 Gqrx, 8091 SDRangel.
    "SDR Software": "none",
    "SDR Host": "127.0.0.1",
    "SDR Port": 4532,
    # 1 to start the SDR program if it is not already running. An SDR that
    # was already running is left running when this application closes; one
    # this application started is closed with it.
    "SDR Autostart": 1,
    # Empty means "look where this program usually lives" -- see
    # sdr_launcher.py. Set it when yours is somewhere else.
    "SDR Path": "",
    "SDR CW Width HZ": 500,
    "SDR SSB Width HZ": 2600,

    # Timing of the conversation with the rig's Nano.
    "MCU Command Headroom": 0.09,
    "MCU Read Wait Period": 0.04,
    "MCU Update Period": 250,

    # The station.
    "Callsign": "",
    "NUMBER DELIMITER": ".",
    "Last Active Frequency": 14032000,
    "VFO Touch Optimized": "True",
    "Virtual Keyboard Switch": "True",

    # CW.
    "CW Tone": "600",
    "CW Speed": "10",
    "CW Key Type": "STRAIGHT",
    "CW Delay Before TX": "250",
    "CW Delay Returning to RX": "2000",
    "CW Copy VFOA to VFOB on Split": "True",
    "TXOffset": "EEPROM",

    # Calibration held in the radio, shown beside the file's copy.
    "Master Cal": "",
    "SSB BFO": "",
    "CW BFO": "",
    "PWR Factor": "1.00",
    "SWR Factor": "1.00",
    "PWR SWR": "False",
    "DSP": "False",

    # The logbook.
    "Logbook Switch": "False",
    "Logbook Type": "adi",
    "Logbook Name": "uBITX_Logbook",
    "Logbook Location": "~",
    "Logbook Backup Interval": "30",
}
