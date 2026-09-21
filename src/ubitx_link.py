from time import sleep
from timeit import default_timer as timer
import serial

MODES = ("DFT", "ERR", "LSB", "USB", "CWL", "CWU")

# How long a borrow-write-return step waits for its confirmation before the
# sequence is abandoned. Generous: the rig is effectively synchronous and
# answers in tens of milliseconds, so this only fires when something has
# genuinely gone wrong.
# Generous on purpose. Each step sits behind the throttle's blocking sleep,
# and a toggle makes the rig report several things -- the new primary's
# frequency and its mode -- before the confirmation being waited on. Waiting
# too long only delays clearing a failed sequence; waiting too little
# abandons one that was about to succeed.
TX_WRITE_TIMEOUT_MS = 2000

# How long to wait before starting a queued transmit write after the last one
# finished. Long enough for the rig's trailing reports -- the frequency and
# mode of the VFO it just switched back to -- to arrive and be attributed to
# the sequence they belong to.
FOLLOW_UP_DELAY_MS = 250

# How long to wait after a confirmation before sending the next command of a
# sequence.
#
# MCU_COMMAND_HEADROOM paces commands generally, but a VFO toggle is not a
# general command: the rig does real work and emits several reports, and a
# frequency write arriving in the middle of that is sometimes simply lost --
# no acknowledgement, no error, the sequence waits for a confirmation that
# never comes. Intermittently, which is what made it look like something
# other than timing.
STEP_SETTLE_MS = 150
# Seconds between commands sent to the rig. The laptop can outrun a Nano
# easily, and this is what stops it. 0.04 means a transmit write in split --
# toggle, frequency, toggle -- spends 120 ms behind the throttle, which is
# why TX_WRITE_TIMEOUT_MS below is generous.
MCU_COMMAND_HEADROOM = .04


class uBITX_Link:
    def __init__ (self, root, port, model, schedule):
        self.root = root
        self.port = port
        self._model = model
        self.schedule = schedule

        # THE COMMAND TABLE FIRST. It is static data, and everything that
        # sends anything needs it -- including a handler that fires while
        # the reader is still being constructed.
        self.toRadioCommandDict = {
            "TS_CMD_MODE": 1,
            "TS_CMD_FREQ": 2,
            "TS_CMD_BAND": 3,
            "TS_CMD_VFO": 4,
            "TS_CMD_SPLIT": 5,
            "TS_CMD_RIT": 6,
            "TS_CMD_TXSTOP": 7,
            "TS_CMD_SDR": 8,
            "TS_CMD_LOCK": 9,  # Dial Lock
            "TS_CMD_ATT": 10,  # ATT
            "TS_CMD_IFS": 11,  # IFS Enabled
            "TS_CMD_IFSVALUE": 12,  # IFS VALUE
            "TS_CMD_STARTADC": 13,
            "TS_CMD_STOPADC": 14,
            "TS_CMD_SPECTRUMOPT": 15,  # Option for Spectrum
            "TS_CMD_SPECTRUM": 16,  # Get Spectrum Value
            "TS_CMD_TUNESTEP": 17,  # Get Spectrum Value
            "TS_CMD_WPM": 18,  # Set WPM
            "TS_CMD_KEYTYPE": 19,  # Set KeyType
            "TS_CMD_SWTRIG": 21,  # SW Action Trigger for WSPR and more
            "TS_CMD_READMEM": 31,  # Read EEProm
            "TS_CMD_WRITEMEM": 32,  # Write EEProm
            "TS_CMD_LOOPBACK0": 74,  # Loopback1 (Response to Loopback Channgel)
            "TS_CMD_LOOPBACK1": 75,  # Loopback2 (Response to Loopback Channgel)
            "TS_CMD_LOOPBACK2": 76,  # Loopback3 (Response to Loopback Channgel)
            "TS_CMD_LOOPBACK3": 77,  # Loopback4 (Response to Loopback Channgel)
            "TS_CMD_LOOPBACK4": 78,  # Loopback5 (Response to Loopback Channgel)
            "TS_CMD_LOOPBACK5": 79,  # Loopback6 (Response to Loopback Channgel)
            "TS_CMD_FACTORYRESET": 85,  # Factory Reset
            "TS_CMD_UBITX_REBOOT": 95  # Reboot
        }

        # The borrow-write-return sequence for a transmit frequency in split.
        # See set_role_frequency: the rig can only write to the primary VFO,
        # so transmit has to borrow that slot and hand it back.
        #
        # SET BEFORE THE READER EXISTS. Constructing _input reads the rig's
        # startup dump and dispatches it immediately, so a handler runs
        # during this constructor -- before any line that follows the
        # assignment. Anything a handler touches has to be in place first.
        self._tx_write_state = None
        self._tx_write_hz = None
        self._tx_write_timer = None
        # The most recent thing the dial asked for while a write was running.
        self._tx_write_next = None
        self._tx_write_mode = None
        self._tx_write_next_mode = None

        # ALL OF THIS BEFORE THE READER.
        #
        # Constructing _input reads the rig's startup dump and dispatches it
        # immediately, so handlers run DURING this constructor -- before any
        # line that follows. Anything they touch, or that anything they
        # trigger touches, has to exist first: the memory queue a handler
        # appends to, and the framing and timing sendCommandToMCU needs.
        self.memoryQueue = []  # when a memory slot is requested, it later comes in without any indication of which
        # memory slot it belong to. Fortunately, all in order. So everytime a memory slot is
        # requested, the type of memory requested is added to the queue so when we take it
        # off the queue, we know where it goes.

        self.tx_to_mcu_preamble = b'\x59\x58\x68'  # all commands to MCU must start with these three bytes
        self.tx_to_mcu_postscript = b'\xff\xff\x73'  # all commands to MCU must end with these three numbers

        self.mcu_command_buffer = []  # buffer used to send bytes to MCU
        self.time_of_last_sent = timer()  # used to avoid overloading MCU

        self._ubitx_reader = self._input(self)

        # THE FINEST PRESET, ONCE, AND LEFT THERE.
        #
        # AFTER the reader, not inside it. _read_all_values runs from
        # _input's constructor, which is called before toRadioCommandDict
        # exists -- so sending a command from there fails on an attribute
        # that has not been assigned yet. Commands belong out here anyway;
        # the reader reads.
        #
        # The rig rounds every frequency it is given to the active tuning
        # preset -- a dial-step setting with a side effect on frequency
        # entry. At 100 Hz a 10 Hz tuning step simply vanishes: the digit
        # turns, the rig rounds it away, and nothing moves.
        #
        # channels.py worked around this per operation, forcing the preset
        # to its finest value and restoring it afterwards, with a comment
        # explaining that a channel recalled at 7.032.100 came back as
        # 7.032.000 otherwise. Doing it once at connect costs two fewer
        # commands on every write and removes the workaround from everywhere
        # that would otherwise need it.
        #
        # What it changes: the rig's OWN knob now steps at the finest rate
        # too. For a desktop controller that is the right trade -- and the
        # operator can still change it on the rig, which reports it and this
        # model follows, so the rounding tolerance stays correct either way.
        self.Set_Tuning_Preset(1)


    @property
    def reader_process_id(self):
        """The VFO that transmits: B in split, otherwise the active one."""
        return self._ubitx_reader.id

    #
    #   Decoding command buffers sent from MCU to Nextion screens
    #
    #   Command format is "pm.xx.val=nn..n" terminated by 3 0xff
    #   Command starts in position 3(0,1,2,3)
    #   Value starts in position 10, and ends before the 3 0xff
    #   All"values" are ascii characters  (i.e., frequency might be
    #   pm.xx.val=7500000ffffff  for 7.5mhz and a 14m frequency might be
    #   pm.xx.val=14032000ffffff
    #
    class _input:
        def __init__(self, radio_link):
            self._radio_link = radio_link
            self._port = radio_link.port
            self._model = radio_link._model
            self._schedule = radio_link.schedule
            print("inner class init", self._port, self._model, self._schedule)

            self._read_all_values()

            self.id = self._radio_link.root.after(self._schedule, self._reader)

        def _read_all_values(self):
            print ("read_all_values")

            #
            #   Read and process all the values sent at startup of radio
            #

            ffCount = 0
            buffer = []
            commandCount = 0
            timeStarted = timer()  # need time on entry to check for timeout

            while commandCount < 26:
                #
                #   Check for timeout situation
                #
                RADIOTIMEOUT=5          # give the operator 5 seconds to remember to turn on the radio.
                if timer() - timeStarted > RADIOTIMEOUT:
                    #
                    #   If we hit the RADIOTIMEOUT limit, then something has gone wrong...
                    #
                    response = messagebox.askyesno(message="No Response from the Radio!",
                                                   detail="Did you forget to turn it on or connect it?\n\n" +
                                                          "If so, you can turn it on now and click the 'Yes' button.\n\n" +
                                                          "Otherwise click 'No' for more options.",
                                                   icon="error")
                    if response == True:
                        timeStarted = timer()  # Reset timer
                    else:
                        response = messagebox.askyesno(message="Wrong Serial Port?",
                                                       detail="The next most likely cause of this error  is that the application is trying to open the wrong serial port.\n\n" +
                                                              "The best option here is to clear the serial port in the configuration file and restart the program.\n\n" +
                                                              "On restart, you can select a different serial port.\n\n" +
                                                              "Click the Yes button to proceed to clear the selected serial port or the 'No' button if you want to try something else.\n\n" +
                                                              "In both cases the application will terminate.",
                                                       icon="error")
                        pass
                        # if response == True:
                        #     gv.config.setRadioPort(
                        #         "")  # This clears out out the entry for the serial port name in the configuration file
                        #     # On restart, the user will have opportinity tp select a new port.
                        exit(99)
                else:

                    # Read a line from the serial port (until a newline character is received)
                    # Decode the bytes to a string (e.g., 'utf-8') and remove leading/trailing whitespace

                    in_byte = self._port.read(1)

                    if in_byte:
                        #
                        #   Looking for the first line with a "p" in the first character
                        #   CEC sends a zero to start, just ignore it
                        #
                        if ((len(buffer) == 0) and (in_byte.decode(errors='ignore') != 'p')):
                            pass
                        else:

                            buffer.append(in_byte)

                            if in_byte.hex() == 'ff':
                                ffCount += 1
                                if ffCount == 3:
                                    #
                                    #   decode the characters into ascii
                                    #
                                    decoded_buffer_char = [item.decode(errors='ignore') for item in buffer]

                                    # if self.debugCommandDecoding:
                                    #     for item in decoded_buffer_char:
                                    #         print(f"{item:<{4}}", end="")
                                    #     print("")

                                    # decoded_buffer_hex = [item.hex() for item in buffer]
                                    # for item in decoded_buffer_hex:
                                    #     print(f"{item:<{4}}", end="")
                                    # print("")

                                    # decoded_buffer_ord = [ord(item) for item in buffer]
                                    # for item in decoded_buffer_ord:
                                    #     print(f"{item:<{4}}", end="")
                                    # print("")
                                    #
                                    #   since we saw 3 0xff's in a row, we can call the getter to
                                    #   set the value in the UX
                                    #
                                    self._process_radio_command(decoded_buffer_char)
                                    #
                                    #   reset counters (and add one to total processed)
                                    #
                                    ffCount = 0
                                    buffer = buffer[:0]
                                    commandCount += 1
                                    print("commandCount:", commandCount)

                            #
                            #   Sometimes the Emulator can outrun the MCU's ability to deliver data. If we were reading valid data
                            #   and we get a zero waiting situation, wait for a little to see if more data appears
                            #
                            if self._port.in_waiting == 0:
                                MCU_Read_Wait_Period = .04
                                sleep(float(MCU_Read_Wait_Period))
            print("read all values done")
        def _reader(self):
            # print ("read")
            ffCount = 0
            buffer = []
            while self._port.in_waiting > 0:
                #
                #   Get command
                #
                in_byte = self._port.read(1)

                if in_byte:
                    #
                    #   Looking for the first line with a "p" in the first character
                    #   CEC sends a zero to start, just ignore it
                    #
                    if ((len(buffer) == 0) and (in_byte.decode(errors='ignore') != 'p')):
                        if in_byte != b'\xff':
                            print("skipping prior byte:", in_byte)
                        pass
                    else:

                        buffer.append(in_byte)

                        if in_byte.hex() == 'ff':
                            ffCount += 1
                            if ffCount == 3:
                                if buffer[3] == 's' and buffer[4] == 'h':
                                    print("found a sh", buffer)
                                #
                                #   decode the characters into ascii
                                #
                                # decoded_buffer_char = [item.decode(errors='ignore') for item in buffer]
                                # print("decoded:", decoded_buffer_char)
                                #
                                #   since we saw 3 0xff's in a row, we can call the getter to
                                #   set the value in the UX
                                #
                                self._process_radio_command([item.decode(errors='ignore') for item in buffer])
                                #
                                #   reset counters (and add one to total processed)
                                #
                                ffCount = 0
                                # buffer = buffer[:0]
                                buffer.clear()
                        #
                        #   Sometimes the Emulator can outrun the MCU's ability to deliver data. If we were reading valid data
                        #   and we get a zero waiting situation, wait for a little to see if more data appears
                        #
                        if self._port.in_waiting == 0:
                            # sleep(float(gv.config.get_MCU_Read_Wait_Period()))
                            MCU_Read_Wait_Period = .04
                            sleep(float(MCU_Read_Wait_Period))


            try:
                self.id=self._radio_link.root.after(self._schedule, self._reader)
            except tk.TclError:
                # Catch-all safety net for mid-execution destruction
                return

        def _process_radio_command(self, buffer):
            command = buffer[3] + buffer[4]
            self._delegate_command_processing(command, buffer)

            # THE VIEW IS TOLD HERE, and nowhere else.
            #
            # Handlers write the model; none of them notifies. Without this
            # the rig reported, the model updated, and the interface went on
            # showing whatever it had -- which looked like individual features
            # not working rather than the display never redrawing at all.
            #
            # Once per command is fine: changed() coalesces a burst into a
            # single redraw on the next idle pass.
            self._model.changed()

        ################################################################################
        #   Format of command sent by radio:
        #   1. Prelog
        #   2. command type: characters 0-2, format "xx." Where "xx" is mostly "pm"
        #   3. subcommand type: characters 3,4  The translation between these characters
        #   and the code that implements them is in the dictionary above "MCU_Command_To_CB_Dict"
        #   4. value: This is the 4 bytes between 10-13. Mostly these are characters. But
        #   in some cases the might represent hex bytes that need to be recoded into an int
        ################################################################################

        def _extract_value(self, buffer, start, end):
            returnBuffer = ""
            i = start
            while i < end:
                returnBuffer = returnBuffer + buffer[i]
                i += 1
            return returnBuffer.replace('"', '')

        ######################################################################################
        #   This looks up the command processing routing to be called via a dictionary
        #   based on the command type (characters 3,4 in the buffer after prelogue stripped
        ######################################################################################

        def _validate_key(self, command, buffer):
            validate_flag = False
            if len(command) != 2:
                print("invalid command", command)
            elif len(buffer) == 0:
                print("empty buffer", buffer)
            elif command.isalnum() == False:
                print("invalid command", command)
            elif buffer[0] != 'p' or buffer[1] != 'm':
                print("invalid command - doesnt start pm", command)
            elif buffer[2] != '.' or buffer[5] != '.':
                print("invalid command - periods in wrong place ")
            elif ((buffer[6] != 'v') or (buffer[7] != 'a') or (buffer[8] != 'l')) and (
                    (buffer[6] != 't') or (buffer[7] != 'x') or (buffer[8] != 't')):
                print("invalid command - not txt or val")
            elif buffer[9] != '=':
                print("invalid command format, no =")
            elif len(self._extract_value(buffer, 10, len(buffer) - 3)) < 1:
                print("invalid value format, empty")
            elif 'val' in self._extract_value(buffer, 10, len(buffer) - 3):
                print("invalid value format, looks like val")
            else:
                validate_flag = True
            #
            #   Need to figure out how to recover from this type of bad data
            #
            # if validate_flag == False:
            #     self.connection.rebootRadio()

            return validate_flag

        def _delegate_command_processing(self, command, buffer):
            # print(command, buffer)

            if self._validate_key(command, buffer) == False:
                print(buffer)
                return
            match command:
                case "v1":
                    self.v1_UX_Set_Tuning_Preset_1(buffer)
                case "v2":
                    self.v2_UX_Set_Tuning_Preset_2(buffer)
                case "v3":
                    self.v3_UX_Set_Tuning_Preset_3(buffer)
                case "v4":
                    self.v4_UX_Set_Tuning_Preset_4(buffer)
                case "v5":
                    self.v5_UX_Set_Tuning_Preset_5(buffer)
                case "cn":
                    self.cn_UX_Set_Active_Tuning_Preset(buffer)
                case "ch":
                    self.ch_UX_Set_CW_TX_OFFSET(buffer)
                case "vh":
                    self.vh_UX_Set_CW_Tweak(buffer)
                case "vo":
                    self.voGet(buffer)
                case "vp":
                    self.vpGet(buffer)
                case "vq":
                    self.vqGet(buffer)
                case "sv":
                    self.sv_UX_Set_SW_Version(buffer)
                case "sc":
                    self.sc_UX_Set_User_Callsign(buffer)
                case "cm":
                    self.cm_UX_Display_Callsign_Version_Flag(buffer)
                case "c0":
                    self.c0_UX_Toggle_Classic_uBITX_Control(buffer)
                case "vc":
                    self.vc_UX_Set_Primary_VFO_Frequency(buffer)
                case "cc":
                    self.cc_UX_Set_Primary_Mode(buffer)
                case "va":
                    self.va_UX_Set_VFO_A_Frequency(buffer)
                case "ca":
                    self.ca_UX_Set_VFO_A_Mode(buffer)
                case "vb":
                    self.vb_UX_Set_VFO_B_Frequency(buffer)
                case "cb":
                    self.cb_UX_Set_VFO_B_Mode(buffer)
                case "vt":
                    self.vt_UX_SET_CW_Tone(buffer)
                case "ck":
                    self.ck_UX_Set_CW_Key_Type(buffer)
                case "vs":
                    self.vs_UX_Set_CW_Speed(buffer)
                case "vy":
                    self.vy_UX_Set_CW_Delay_Returning_to_RX(buffer)
                case "ve":
                    self.ve_UX_Set_CW_Delay_Starting_TX(buffer)
                case "cv":
                    self.cv_UX_VFO_Toggle(buffer)  # sets active VFO, A=0, B=1
                case "s0":
                    self.s0_UX_Greenbox_Line1(buffer)
                case "s1":
                    self.s1_UX_Greenbox_Line2(buffer)
                case "sh":
                    self.sh_UX_Get_Memory(buffer)
                case "vn":
                    self.vn_UX_ACK_Memory_Write(buffer)
                case "cl":
                    self.cl_UX_Lock_Screen(buffer)
                case "cj":
                    self.cj_UX_Speaker_Toggle(buffer)
                case "cs":
                    self.cs_UX_SPLIT_Toggle(buffer)
                case "vr":
                    self.vr_UX_Update_RIT_Freq(buffer)
                case "cr":
                    self.cr_UX_RIT_Toggle(buffer)
                case "vf":
                    self.vf_UX_ATT_Level(buffer)
                case "vi":
                    self.vi_UX_IFS_Level(buffer)
                case "vm":
                    self.vm_UX_PW_SWR_Level(buffer)
                case "ci":
                    self.ci_UX_IFS_State_Set(buffer)
                case "cx":
                    self.cx_UX_TX_Stop_Toggle(buffer)
                case "cp":
                    self.cp_UX_S_Meter_Value(buffer)  # Related to S meter. search CMD_SMETER
                case "ct":
                    self.ct_UX_RX_TX_Mode(buffer)
                case "al":
                    self.al_UX_S_Meter_Value(buffer)
                case "vv":
                    self.vv_UX_Command_Data(buffer)
                case "vg":
                    self.vg_UX_DSP_Flag(buffer)
                case "sb":
                    self.sb_UX_CW_Decoded_Characters(buffer)
                case "sp":
                    self.sp_UX_DSP_Spectrum_Values(buffer)
                case "xt":
                    self.sp_UX_DSP_Spectrum_Values(buffer)
                case _:
                    print("Command not recognized=", buffer, "*")
                    print("command:", command, "*", sep="*")

        #   MCU Commands
        #########################################################################################
        ####    Start of command processing sent by Radio(MCU) to Screen
        #########################################################################################

        #
        #   The "v1" command is used for smallest tuning rate
        #

        def v1_UX_Set_Tuning_Preset_1(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Tuning Preset 1: ", value)
            self._model.tuning_presets[0] = int(value)
            # self.theVFO_Object.setTuningPreset(1, value)

        #
        #   The "v2" command is used for smallest tuning rate
        #
        def v2_UX_Set_Tuning_Preset_2(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Tuning Preset 2: ", value)
            self._model.tuning_presets[1] = int(value)
            # self.theVFO_Object.setTuningPreset(2, value)

        #
        #   The "v3" command 1s used for the third (middle) tuning rate
        #
        def v3_UX_Set_Tuning_Preset_3(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Tuning Preset 3: ", value)
            self._model.tuning_presets[2] = int(value)
            # self.theVFO_Object.setTuningPreset(3, value)

        #
        #   The "v4" command 1s used for the next largest tuning rate
        #
        def v4_UX_Set_Tuning_Preset_4(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Tuning Preset 4: ", value)
            self._model.tuning_presets[3] = int(value)
            # self.theVFO_Object.setTuningPreset(4, value)

        #
        #   The "v5" command 1s used for the largest tuning rate
        #
        def v5_UX_Set_Tuning_Preset_5(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Tuning Preset 5: ", value)
            self._model.tuning_presets[4] = int(value)
            # self.theVFO_Object.setTuningPreset(5, value)

        #
        #   The "cn" command indicates which tuning step is active (1(smallest) - 5(largest)
        #
        def cn_UX_Set_Active_Tuning_Preset(self, buffer):

            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Active Tuning Preset: ", value)
            # Decides the rounding granularity, so anything comparing a
            # confirmation against a request needs it.
            self._model.active_tuning_preset = int(value)
            # self.theVFO_Object.set_Active_Tuning_Preset(value)

        #
        #   The "ch" command originates from the EEPROM and is added to the frequency to shift it
        #
        def ch_UX_Set_CW_TX_OFFSET(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("CW TX OFFSET: ", value)
            #
            #   The following provides the ability to override the EEPROM value as a setting config
            #
            # if self.cwTX_OffsetFlagOverride != None:
            #     self.cwTX_OffsetFlag = self.cwTX_OffsetFlagOverride
            #     return
            #
            # if value == 0:  # turn off CW TX offset mode
            #     self.cwTX_OffsetFlag = False
            # else:  # turn on CW TX offset - only effects CWL and CWU modes
            #     self.cwTX_OffsetFlag = True

        #
        #   The "vh" command originates from the EEPROM and is added to the frequency to shift it
        #
        def vh_UX_Set_CW_Tweak(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("CW Tweak: ", value)
            # self.cwTX_Tweak = int(value)

        #
        #   The "vo" if 1, then turn on IFS and use initial value
        #
        def voGet(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("v0Get: ", value)

        def cp_UX_S_Meter_Value(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("S_Meter_Value: ", value)
            # self.s_meter_Progressbar_VAR.set(int(value))

        #
        #   This is a hack fix for a bug in CEC (at least v2.0, perhaps in 1.x too)
        #   Command for S-meter is ill formed and we  get "p.val=x" instead of "pm.cp.val=x'
        #   Just got tired of seeing this error flagged...
        #
        def al_UX_S_Meter_Value(self, buffer):
            value = self._extract_value(buffer, 6, len(buffer) - 3)
            print("al_UX_S_Meter_Value: ", value)
            # if value.isnumeric():
            #     print("correcting for mal formed s-meter commend", buffer, "setting s-meter to", value)
            #     self.s_meter_Progressbar_VAR.set(int(value))
            # else:
            #     print("another weird malformed command, buffer =", buffer)

        #
        #   This command provides Nextion with the Power and SWR levels
        #   PWR is sent first, followed by the SWR second
        #
        def vm_UX_PW_SWR_Level(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vm_UX_PW_SWR_Level: ", value)
            # if gv.config.get_PWR_SWR_Switch() == "True":
            #     value = self._extract_value(buffer, 10, len(buffer) - 3)
            #     adjustedValue = int(value) / 100
            #
            #     if self.lastPWRSWR_Reading == None or self.lastPWRSWR_Reading == "SWR":
            #         self.lastPWRSWR_Reading = "PWR"
            #         factorPWR = round(adjustedValue / float(gv.config.get_PWR_Factor()), 1)  # 3.91
            #         self.PWR_Value_VAR.set(str(factorPWR).replace(".", gv.config.get_NUMBER_DELIMITER()))
            #     else:
            #         self.lastPWRSWR_Reading = "SWR"
            #         factorSWR = round(adjustedValue / float(gv.config.get_SWR_Factor()), 1)  # 2,95
            #         if factorSWR < 1.0 or factorSWR > 2.9:
            #             self.SWR_Label.configure(style="Heading3bRed.TLabel")
            #             self.SWR_Value.configure(style="Heading3bRed.TLabel")
            #         else:
            #             self.SWR_Label.configure(style="Heading3b.TLabel")
            #             self.SWR_Value.configure(style="Heading3b.TLabel")
            #
            #         self.SWR_Value_VAR.set(str(factorSWR).replace(".", gv.config.get_NUMBER_DELIMITER()))

        def vv_UX_Command_Data(self, buffer):

            #
            # saving this data because dont know what to do with it until next command
            # could be retrieving EEPROM DSP settings to screen dimming or ?
            #

            self.vv_Command_Buffer = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Received VV data", self.vv_Command_Buffer, "len=", len(self.vv_Command_Buffer))

        def vg_UX_DSP_Flag(self, buffer):
            commandType = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vg_UX_DSP_Flag Received:", commandType)
            #
            #   Dsp data is weird. You get a "vv" command with the data followed by a "vg" with
            #   the command to send the "vv" buffer that you received previously.
            #
            # self.process_DSP_EEPROM_Data(self.vv_Command_Buffer)

        def sb_UX_CW_Decoded_Characters(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("Decoded CW Characters", buffer)
            # self.consumerDSPdata.process_CWDecoded_Data(value)

        def sp_UX_DSP_Spectrum_Values(self, buffer):
            value = self._extract_value(buffer, 6, len(buffer) - 3)
            print("sp_UX_DSP_Spectrum_Values: ", value)
            # if buffer[3] == "x" and buffer[4] == "t":  # error catch for malformed spectrum responses
            #     value = self._extract_value(buffer, 6, len(buffer) - 3)
            #     # print("fixing malformed p., value =", value)
            # else:
            #     value = self._extract_value(buffer, 10, len(buffer) - 3)
            # print("buffer=", buffer)
            # print("value=", value)
            # if self.consumerDSPdata
            self.consumerDSPdata.process_Spectrum_Data(value)

        # def highlightCWorSpectrumBoxes(self, flag):
        #     self.mainScreenCW_logger.clearLog()
        #     self.mainScreenPlotter.clearCanvas()
        #
        #     if flag:
        #         if self.frequencySpectrumMode == "FreqScan":
        #             self.spectrumCanvas.configure(
        #                 highlightbackground="white",
        #                 highlightcolor="white")
        #             self.decodedCWText.configure(
        #                 highlightbackground="gray",
        #                 highlightcolor="gray")
        #             # self.mainScreenCW_logger.clearLog()
        #             return
        #         elif self.frequencySpectrumMode == "CWDecode":
        #             self.spectrumCanvas.configure(
        #                 highlightbackground="gray",
        #                 highlightcolor="gray")
        #             self.decodedCWText.configure(
        #                 highlightbackground="white",
        #                 highlightcolor="white")
        #             # self.mainScreenPlotter.clearCanvas()
        #             return
        #
        #     self.decodedCWText.configure(
        #         highlightbackground="gray",
        #         highlightcolor="gray")
        #     self.spectrumCanvas.configure(
        #         highlightbackground="gray",
        #         highlightcolor="gray")
            # self.mainScreenCW_logger.clearLog()
            # self.mainScreenPlotter.clearCanvas()

        # def process_Spectrum_Data(self, buffer):
        #     #
        #     #   If the DSP had been previously enabled, it can be generating data before
        #     #   the "consumer" in the mainscreen has been started. This just throws this data
        #     #   away until it is ready
        #     #
        #     # print("mainscreen Processing Spectrum Data", buffer)
        #     if self.mainScreenPlotter != None:
        #         self.mainScreenPlotter.process_Data(buffer)
        #
        # def process_CWDecoded_Data(self, buffer):
        #     print("Processing CW Data for main window", buffer)
        #     #
        #     #   If the DSP had been previously enabled, it can be generating data before
        #     #   the "consumer" in the mainscreen has been started. This just throws this data
        #     #   away until it is ready
        #     #
        #
        #     if self.mainScreenCW_logger != None:
        #         self.mainScreenCW_logger.process_CWDecoded_Data(buffer)
        #
        # def process_DSP_EEPROM_Data(self, buffer):
        #     # print("Processing DSP Data for main window", buffer)
        #     byteList = int(buffer).to_bytes(4, 'little')
        #     # print("process_DSP_Data", byteList)
        #
        #     if int(buffer) < 0xffffff:  # only a 3 hex byte number
        #         self.DSPFound = True
        #
        #         # print("main window eeprom values returned")
        #         # print(hex(int(buffer)))
        #         # print("main window decodescale*10=", byteList[0])
        #         # print("main window useDSPFlag=", byteList[1])
        #
        #         self.frequencyDecodeScale = int(byteList[0] / 10)
        #
        #         if byteList[
        #             1] == 1 and gv.config.get_DSP_Switch() == "False":  # configuration file/option says no, DSP says yes...
        #             messagebox.showwarning(message="Configuration Mismatch!",
        #                                    detail="Configuration file disables DSP while DSP believes it is active.\n\n" +
        #                                           "Updating configuration file to Enable DSP. You can change this in Machine Settings.",
        #                                    parent=self)
        #             gv.config.set_DSP_Switch("True")
        #         elif byteList[
        #             1] == 0 and gv.config.get_DSP_Switch() == "True":  # configuration file says yes, DSP says no
        #             messagebox.showwarning(message="Configuration Mismatch!",
        #                                    detail="Configuration file enables DSP while DSP is inactive.\n\n" +
        #                                           "Updating configuration file to Disable DSP. You can change this in Machine Settings.",
        #                                    parent=self)
        #             gv.config.set_DSP_Switch("False")
        #         else:
        #             pass  # configuration file and DSP agree, do nothing
        #
        #         if byteList[2] == 95:
        #             self.frequencySpectrumMode = "FreqScan"
        #         elif byteList[2] >= 100 and byteList[2] < 146:  # in CW mode
        #             self.frequencyPlotcwToneScale = int(byteList[2] - 100)
        #             self.frequencyPlotcwToneValue = ((byteList[2] - 100) * 50) + 300
        #             self.frequencySpectrumMode = "CWDecode"
        #
        #         #
        #         #   Now that we know which mode we are in, set white boundaries around the cw or spectrum areas
        #         #   appropriately and clear the areas to start fresh
        #         #
        #         self.highlightCWorSpectrumBoxes(True)
        #
        #         # print("eeprom fetch:", hex(int(buffer)))
        #
        # def request_DSP_EEPROM_Data(self):
        #     #
        #     # Request DSP data stored in EEPROM
        #     self.connection.Req_DSP_EEPROM_Settings()

        #
        #   Indicates a switching of RX/TX mode. 1=TX, 0=RX
        #
        def ct_UX_RX_TX_Mode(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("ct_UX_RX_TX_Mode: ", value)
            # Carries its state, unlike the toggles above: the code this
            # replaces tested `value == "1"` rather than flipping a flag.
            self._model.transmitting = (str(value).strip() == "1")
            # if value == "1":  # going into transmit mode
            #     self.theVFO_Object.setTXButtonState()
            #     #
            #     #   Stop SDR if it exists
            #     #
            #     if self.theSDR is not None:
            #         self.theSDR.stop_scan()
            #         self.theSDR.stopSDR()
            #
            #     if gv.config.get_PWR_SWR_Switch() == "True":  # If PWR/SWR Switch is off display nothing
            #         self.SWR_PWR_Frame.grid()
            #
            # else:
            #     self.theVFO_Object.setRXButtonState()
            #     #
            #     #   Start SDR if it exists
            #     #
            #     if self.theSDR is not None:
            #         self.theSDR.startSDR()
            #     #
            #     #   the self.master.state('normal') is a little magic that is needed on macos to make sure the
            #     #   frame really disappears. Only need to schedule this if PWR/SWR switch is on.
            #     #
            #     if gv.config.get_PWR_SWR_Switch() == "True":
            #         self.master.after(2000, lambda: [self.SWR_PWR_Frame.grid_remove(), self.master.state('normal')])

        #
        #   The "vp" command originates from the EEPROM and is added to the frequency to shift it
        #
        def vpGet(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vp get called:", "buffer =", buffer)

        #
        #   The "vq" command is referred to as display option 2 in EEPROM
        #
        def vqGet(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vq get called: buffer=", buffer)

        #
        #   The "sv" command is stores the text of the firmware version
        #
        def sv_UX_Set_SW_Version(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("sv_UX_Set_SW_Version: ", value)
            self._model.set_firmware(str(value).strip())
            # self.theVFO_Object.setFirmwareVersion(value)

        #
        #   The "sc" command is stores the text of the operators callsign
        #
        def sc_UX_Set_User_Callsign(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("sc_UX_Set_User_Callsign: ", value)
            self._model.set_callsign(str(value).strip())
            # self.theVFO_Object.setCallsign(value)

        #
        #   The "cm" command determines whether call sign and firmware versions are displayed
        #
        def cm_UX_Display_Callsign_Version_Flag(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("cm_UX_Display_Callsign_Version_Flag: ", value)
            # if value == "0":
            #     self.theVFO_Object.setFirmwareVersion("")
            #     self.theVFO_Object.setCallsign("")

        #
        #   The "c0" command determines whether we are in text (yellow box) or graphics mode
        #
        def c0_UX_Toggle_Classic_uBITX_Control(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("c0_UX_Toggle_Classic_uBITX_Control: ", value)
            # if value == "0":
            #     if self.classic_uBITX_ControlWindowObj != None:
            #         self.classic_uBITX_ControlWindowObj.pack_forget()
            #         self.classic_uBITX_ControlWindowObj = None
            #     if self.classic_uBITX_ControlWindow != None:
            #         self.classic_uBITX_ControlWindow.destroy()
            #         self.classic_uBITX_ControlWindow = None
            #
            # else:
            #     self.displayClassic_uBITXControlWindow()

        #
        # The purpose of this command is a little puzzling
        # code talks about this being used to eliminate duplicate data
        # Only sent on the first attempt to lock the screen
        # Also contains the text for the speaker button
        #
        def s0_UX_Greenbox_Line1(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("s0_UX_Greenbox_Line1: ", value)
            # self.displayLine1Classic_uBITX_Control(value)

        def s1_UX_Greenbox_Line2(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("s1_UX_Greenbox_Line2: ", value)
            # self.displayLine2Classic_uBITX_Control(value)

        def sh_UX_Get_Memory(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("sh_UX_Get_Memory", self.connection.lenMemoryQueue())
            # try:
            #     value = self._extract_value(buffer, 10, len(buffer) - 3)
            #     # print("sh_UX_Get_Memory", self.connection.lenMemoryQueue())
            #     if self.connection.lenMemoryQueue() == 0:  # make sure something in queue, otherwise fatal error
            #         messagebox.showerror("Application Error",
            #                              "Memory Queue is empty, yet memory value delivered by MCU")
            #         sys.exit("A fatal internal error occurred")
            #
            #     memoryCategory = self.connection.popMemoryQueue()
            #
            #     match memoryCategory:
            #
            #         case "Freq":  # Got a channel frequency request
            #             freq = int(value, 16) & 0x1FFFFFFF
            #             mode = (int(value, 16) >> 29) & 0x7
            #             self.channelsWindow.EEPROM_SetChanneFreqMode(
            #                 self.EEPROM_Current_Slot_Freq,
            #                 freq,
            #                 mode)
            #             self.EEPROM_Current_Slot_Freq += 1
            #             if (self.EEPROM_Current_Slot_Freq ==
            #                     EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.totalSlots]):
            #                 self.EEPROM_Current_Slot_Freq = 0
            #
            #         case "Label":  # have a label for a memory channel
            #             self.channelsWindow.EEPROM_SetChannelLabel(
            #                 self.EEPROM_Current_Slot_Label,
            #                 value)
            #             # if self.EEPROM_Current_Slot_Label == 9:
            #             #         print("label slot=", self.EEPROM_Current_Slot_Label, "value=", value, sep='*', end='*')
            #             self.EEPROM_Current_Slot_Label += 1
            #             if (self.EEPROM_Current_Slot_Label ==
            #                     EEPROM.Mem_Address["channel_Label"][EEPROM.totalSlots]):
            #                 self.EEPROM_Current_Slot_Label = 0
            #
            #         case "ShowLabel":  # Reading switch on whether to show or not show the label
            #             if (ord(value) == 0):
            #                 self.channelsWindow.EEPROM_SetChannelShowLabel(
            #                     self.EEPROM_Current_Slot_ShowLabel,
            #                     "No")
            #
            #             else:
            #                 self.channelsWindow.EEPROM_SetChannelShowLabel(
            #                     self.EEPROM_Current_Slot_ShowLabel,
            #                     "Yes")
            #
            #             self.EEPROM_Current_Slot_ShowLabel += 1
            #             if (self.EEPROM_Current_Slot_ShowLabel ==
            #                     EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.totalSlots]):
            #                 self.EEPROM_Current_Slot_ShowLabel = 0
            #
            #         case "MasterCal":  # Got a master cal value
            #             self.connection.Master_Cal_Setter(str(int(value, 16)))
            #
            #         case "SSB_BFO":  # Got a SSB BFO value
            #             self.connection.SSB_BFO_Setter(str(int(value, 16)))
            #
            #         case "CW_BFO":  # Got a CW BFO Value
            #             self.connection.CW_BFO_Setter(str(int(value, 16)))
            #
            #         case "Factory_MasterCal":  # Got a Factory_MasterCal memory value
            #             self.connection.Factory_Master_Cal_Setter(str(int(value, 16)))
            #
            #         case "Factory_SSB_BFO":  # Got a Factory SSB BFO memory value
            #             self.connection.Factory_SSB_BFO_Setter(str(int(value, 16)))
            #
            #         case "Factory_CW_Speed":  # Got a CW Speed memory value
            #             if int(value, 16) != 0:
            #                 cw_speed = str(round(1200 / int(value, 16)))
            #             else:
            #                 cw_speed = "0"
            #
            #             self.connection.Factory_CW_Speed_Setter(cw_speed)
            #
            #         case "Factory_CW_Sidetone":
            #             self.connection.Factory_CW_Sidetone_Setter(str(int(value, 16)))
            #
            #         case "Spectrum_Scan":
            #             # print("Spectrum_Scan", self.connection.lenMemoryQueue(), buffer)
            #             self.consumerSpectrumdata.process_Spectrum_Data(value)
            #
            #         case _:
            #             # print("case=",memoryCategory)
            #             messagebox.showerror("Application Error", "Unknown Memory Request")
            #             sys.exit("A fatal internal error occurred")
            # except TypeError:
            #     print("type error")
            #     print("memory category =", memoryCategory)
            #     print(" freq slot =", self.EEPROM_Current_Slot_Freq)
            #     print(" label slot =", self.EEPROM_Current_Slot_Label)
            #     print(" show slot =", self.EEPROM_Current_Slot_ShowLabel)
            #
            #     print("buffer =", buffer)
            #     message = messagebox.showerror("Application Error", "Unknown Memory Request\nRestart application")
            #     sys.exit("A fatal internal error occurred")

        def vn_UX_ACK_Memory_Write(self, buffer):

            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vn_UX_ACK_Memory_Write: ", value)
            # if self.CurrentDebug:
            #     print("vn get called:", "buffer =", buffer)
            #     print("buffer=", buffer)
            #     if (int(value) == 358):
            #         print("write complete for keychange, mem=", int(value))
            #     elif (int(value) == 28):
            #         print("write complete for new WPM, mem=", int(value))
            #     elif (int(value) == 259):
            #         print("write complete for new RX->TX, mem=", int(value))
            #     elif (int(value) == 258):
            #         print("write complete for new TX->RX, mem=", int(value))
            #     else:
            #         print("memory location write complete, mem=", int(value))

        def cl_UX_Lock_Screen(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("cl_UX_Lock_Screen: ", value)
            self._model.locked = not self._model.locked

            # if (self.lock_Button_On):
            #     self.lock_Button_On = False
            #     self.lock_Button.configure(style='Button1bRaised.TButton')
            #     self.lock_Button['text'] = "LOCK"
            #     self.unlockUX()
            # else:
            #     self.lock_Button_On = True
            #     self.lock_Button.configure(style='RedButton1bPressed.TButton')
            #     self.lock_Button['text'] = "LOCKED"
            #     self.lockUX()

        #
        #   Disable all of the control widgets when a LOCK action is requested
        #
        # def lockUX(self):
        #     self.settings_Button.configure(state="disabled")
        #     self.vfo_Button.configure(state="disabled")
        #     self.mode_Button.configure(state="disabled")
        #     self.band_up_Button.configure(state="disabled")
        #     self.band_down_Button.configure(state="disabled")
        #     self.speaker_Button.configure(state="disabled")
        #     self.split_Button.configure(state="disabled")
        #     self.rit_Button.configure(state="disabled")
        #     self.channels_Button.configure(state="disabled")
        #     # self.ATT_Jogwheel.setStateDisabled()
        #     # self.IFS_Jogwheel.setStateDisabled()
        #     self.downButton_Canvas.configure(state="disabled")
        #     self.downButton_Canvas.itemconfig(self.downButton, image=self.arrow_down_disabled)
        #
        #     self.upButton_Canvas.configure(state="disabled")
        #     self.upButton_Canvas.itemconfig(self.upButton, image=self.arrow_up_disabled)
        #
        #     self.theVFO_Object.setVFOUXState("disabled")
        #     self.cwDecode_Button.configure(state="disabled")
        #     self.spectrumScan_Button.configure(state="disabled")
        #     self.bandScan_Button.configure(state="disabled")
        #
        #     self.logQSO_Button.configure(state="disabled")
        #
        # #
        # #   Reset all widgets to their "normal" state after the  unlock happens
        # #
        # def unlockUX(self):
        #     self.settings_Button.configure(state="normal")
        #     self.vfo_Button.configure(state="normal")
        #     self.mode_Button.configure(state="normal")
        #     self.band_up_Button.configure(state="normal")
        #     self.band_down_Button.configure(state="normal")
        #     self.speaker_Button.configure(state="normal")
        #     self.split_Button.configure(state="normal")
        #     self.rit_Button.configure(state="normal")
        #     self.channels_Button.configure(state="normal")
        #     # if (self.ATT_Button_On == True):
        #     #     self.ATT_Jogwheel.setStateNormal()
        #     # if (self.IFS_Button_On == True):
        #     #     self.IFS_Jogwheel.setStateNormal()
        #
        #     self.downButton_Canvas.configure(state="normal")
        #     self.downButton_Canvas.itemconfig(self.downButton, image=self.arrow_down_normal)
        #     self.upButton_Canvas.configure(state="normal")
        #     self.upButton_Canvas.itemconfig(self.upButton, image=self.arrow_up_normal)
        #     self.theVFO_Object.setVFOUXState("normal")
        #     self.cwDecode_Button.configure(state="normal")
        #     self.spectrumScan_Button.configure(state="normal")
        #     self.bandScan_Button.configure(state="normal")
        #
        #     if gv.config.get_Logbook_Switch() == "True":
        #         self.logQSO_Button.configure(state="normal")

        def cj_UX_Speaker_Toggle(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("cj_UX_Speaker_Toggle: ", value)
            self._model.muted = not self._model.muted

            # if (self.speaker_Button_On):
            #     self.speaker_Button_On = False
            #     self.speaker_Button.configure(style='Button1bRaised.TButton')
            #     self.speaker_Button['text'] = "SPEAKER"
            #     if self.theSDR != None:
            #         self.theSDRWindow.on_close()  # close the sdrdashboard when going out of sdr mode
            #         self.theSDR.stopSDR()
            #         self.theSDR.disconnect()
            #         self.theSDR = None
            # else:
            #     self.speaker_Button_On = True
            #     self.speaker_Button.configure(style='RedButton1bPressed.TButton')  # , state="pressed")
            #     if gv.config.get_SDR_Switch() == "True":
            #         self.speaker_Button['text'] = "SDR"
            #         self.theSDRWindow = launch_sdr_popup(self)
            #         self.theSDR = self.theSDRWindow.get_app()
            #         if self.theSDR.connect(gv.config.get_sdr_server_ip(), gv.config.get_sdr_tcp_port()):
            #             # print("sdr connected")
            #             self.theSDR.startSDR()
            #             self.theSDR.set_frequency_hz(int(self.theVFO_Object.getIntPrimaryVFO()))
            #             self.theSDR.set_mode(self.mode_Button['text'].replace("CWL", "CW").replace("CWU", "CW"))
            #
            #             self.theSDR.on_frequency_change_primary = self.sdr_frequency_change_callback
            #             self.theSDR.on_mode_change_primary = self.sdr_mode_change_callback
            #
            #         else:
            #             messagebox.showerror("Error", "SDR++ Connection refused. Verify target host profiles.")
            #     else:
            #         self.speaker_Button['text'] = "MUTE"

        # def relaunch_SDRPanel_CB(self, event=None):
        #     if self.speaker_Button_On and self.speaker_Button['text'] == "SDR" and self.theSDRWindow is None:
        #         self.theSDRWindow = launch_sdr_popup(self)
        #         if self.theSDR.connect(gv.config.get_sdr_server_ip(), gv.config.get_sdr_tcp_port()):
        #             # print("sdr connected")
        #             self.theSDR.startSDR()
        #             self.theSDR.set_frequency_hz(int(self.theVFO_Object.getIntPrimaryVFO()))
        #             self.theSDR.set_mode(self.mode_Button['text'].replace("CWL", "CW").replace("CWU", "CW"))
        #             self.theSDR.on_frequency_change_primary = self.sdr_frequency_change_callback
        #             self.theSDR.on_mode_change_primary = self.sdr_mode_change_callback
        #
        #         else:
        #             messagebox.showerror("Error", "SDR++ Connection refused. Verify target host profiles.")

        def cs_UX_SPLIT_Toggle(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("cs_UX_SPLIT_Toggle: ", value)
            # A TOGGLE, not a state. The code this replaced flipped its own
            # flag and never read `value`, which is the behaviour that worked
            # against the real firmware.
            # Read, not toggled, for the same reason as cr_: the rig reports
            # 1 when split goes on, which is a state rather than a
            # notification. The code this replaced flipped its own flag, and
            # would have inverted permanently after a single missed report.
            self._model.split = str(value).strip() == "1"
            # if (self.split_Button_On):
            #     self.split_Button_On = False
            #     self.split_Button.configure(style='Button1bRaised.TButton')
            #     self.theVFO_Object.setSplitmode("OFF")
            # else:
            #     self.split_Button_On = True
            #     self.split_Button.configure(style='GreenButton1bPressed.TButton')
            #     self.theVFO_Object.setSplitmode("ON")

        #
        #   This appears to be a no-op command. If the last rit TX frequency does not equal
        #   the current frequency, this is called to set the VFO to the RIT TX frequency which happens to be
        #   the current vfo setting anyway.
        #
        def vr_UX_Update_RIT_Freq(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vr_UX_Update_RIT_Freq: ", value)
            # IGNORED, deliberately.
            #
            # It looks like the rig's record of the RIT base, and for a while
            # it was stored as one. It is not: it arrives immediately after
            # cr_ and reports a round 14.000.000 wherever the radio actually
            # is -- the same figure the original display showed as "RIT Base
            # RX Freq", so it is the firmware's value, not ours.
            #
            # Storing it overwrote the correct base, captured a moment
            # earlier in cr_ from the real receive frequency, and left the
            # transmit readout stuck on a number nobody had tuned to.
            #
            # The capture in cr_ is the reliable source. If this report ever
            # turns out to mean something useful, the place to find out is
            # the firmware source rather than here.

        def cr_UX_RIT_Toggle(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("cr_UX_RIT_Toggle: ", value)
            # THE VALUE IS THE STATE -- 1 on, 0 off -- so it is read, not
            # toggled. Confirmed on the rig: turning split on while RIT is
            # on produces
            #
            #     cr_UX_RIT_Toggle:  0
            #     cs_UX_SPLIT_Toggle:  1
            #
            # Toggling gave the right answer while every report arrived; one
            # missed report would have left RIT inverted for good. Reading
            # the value cannot drift, and only a genuine CHANGE acts -- so a
            # repeated report does not capture a new base or send receive
            # anywhere.
            was_on = self._model.rit
            now_on = str(value).strip() == "1"
            self._model.rit = now_on
            if now_on and not was_on:
                # Captured AT SWITCH-ON from the real receive frequency: this
                # is where transmit stays while receive is tuned away from
                # it. The rig's vr_ report is NOT used for this -- see there.
                self._model.rit_base_hz = self._model.frequency(
                    self._model.rx_vfo)
            elif was_on and not now_on:
                self._radio_link._leave_rit()
            # if (self.rit_Button_On):
            #     self.rit_Button_On = False
            #     self.rit_Button.configure(style='Button1bRaised.TButton')
            #     self.theVFO_Object.setRITmode("OFF")
            # else:
            #     self.rit_Button_On = True
            #     self.rit_Button.configure(style='GreenButton1bPressed.TButton')
            #     self.theVFO_Object.setRITmode("ON")

        def vf_UX_ATT_Level(self, buffer):
            value = int(self._extract_value(buffer, 10, len(buffer) - 3))
            print("vf_UX_ATT_Level: ", value)

            #
            #   Zero Value indicated Radio turning off the ATT
            #
            # if (value == 0):
            #     self.setATTScaleState('disabled')
            #     self.ATT_Toggle_Button.configure(text="ATT OFF", style='Button2bRaised.TButton')
            #     self.ATT_Button_On = False
            # else:
            #     self.setATTScaleState('normal')
            #     self.ATT_Toggle_Button.configure(text="ATT ON", style='RedButton2bPressed.TButton')
            #     self.ATT_Scale.set(value)
            #     self.ATT_Button_On = True
                # if self.ATT_Jogwheel.state == 'disabled':
                #     self.ATT_Jogwheel.setStateNormal()
                #     self.ATT_Status_VAR.set("ATT (ON)")
                #     self.ATT_Button_On = True
                #
                # mjh normally ux should be set to the value ack-ed by mcu. Problem with this
                # with jog wheels is that they jerk around too much because of all the callbacks
                # This can also cause oscillation where are reported and stored in jogwheel
                # much after and so when correcting generate more old traffic.
                # On balance the chance of a lost packet is pretty low, so best option is to not
                # repond to the ack-ed value from the MCU
                #
                # BUT...
                # In Classic mode, still need to update the jogwheel...
                #
                # if self.classic_uBITX_ControlWindow != None:
                #     self.ATT_Jogwheel.set(value)            # Set UX to value acked by MCU

        def ci_UX_IFS_State_Set(self, buffer):
            value = int(self._extract_value(buffer, 10, len(buffer) - 3))
            print("ci_UX_IFS_State_Set: ", value)
            # if (value == 0):  # Zero value indicates IFS being turned off
            #     self.IFS_Jogwheel.setStateDisabled()
            #     self.IFS_Status_VAR.set("IFS (OFF)")
            #     self.IFS_Button_On = False
            # else:
            #     self.IFS_Jogwheel.setStateNormal()
            #     self.IFS_Status_VAR.set("IFS (ON)")
            #     self.IFS_Button_On = True

        def vi_UX_IFS_Level(self, buffer):  # verification by MCU of new value
            value = int(self._extract_value(buffer, 10, len(buffer) - 3))
            print("vi_UX_IFS_Level: ", value)
            # Note that if a "personalized" IF level is set in the EEPROM, then the radio comes
            # Up with IFS enabled. If value here is 0, just disable the jogwheel
            # if (value == 0):
            #     self.IFS_Jogwheel.setStateDisabled()

            # mjh normally ux should be set to the value ack-ed by mcu. Problem with this
            # with jog wheels is that they jerk around too much because of all the callbacks
            # This can also cause oscillation where are reported and stored in jogwheel
            # much after and so when correcting generate more old traffic.
            # On balance the chance of a lost packet is pretty low, so best option is to not
            # repond to the ack-ed value from the MCU
            #
            # BUT.....
            # Need to respond when in Classic UX Mode. Can use a check for null to figure out whether we update or not
            #

            # if self.classic_uBITX_ControlWindow != None:
            #     self.IFS_Jogwheel.set(value)
            #
            # if self.IFS_On_Boot_Flag:  # A little hack. Generally will not respond to MCU IFS requests for efficiency
            #     # On boot, the default setting is passed to the UX.
            #     self.IFS_Jogwheel.set(value)
            #     self.IFS_On_Boot_Flag = False

        def cx_UX_TX_Stop_Toggle(self, buffer):
            value = int(self._extract_value(buffer, 10, len(buffer) - 3))
            print("cx_UX_TX_Stop_Toggle: ", value)
            self._model.tx_inhibit = not self._model.tx_inhibit
            # self.theVFO_Object.toggleStopButtonState()

        #
        #   The "vc" command indicates a new frequency for the Primary
        #
        def vc_UX_Set_Primary_VFO_Frequency(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            self._model.set_frequency("p", int(value))
            print("vc_UX_Set_Primary_VFO_Frequency: ", value)

            # NOT fed to the transmit sequence any more. Nothing waits for
            # a write to be acknowledged -- see _advance_tx_write -- so this
            # is just another report, and the model has already taken it.
            # self.theVFO_Object.setPrimaryVFO(value)
            #
            # if self.theSDR != None:
            #     self.theSDR.set_frequency_hz(int(value))
            #
            # if self.channelsWindow != None:  # Only update frequency if the channel window has been created once
            #     self.channelsWindow.update_Current_Frequency(self.theVFO_Object.getFormattedPrimaryVFO())
                # self.channelsWindow.update_Current_Frequency(gv.formatFrequency(self.primary_VFO_VAR.get()))

        #
        #   The "cc" command indicates a change to a new mode for primary (e.g. USB, LSB, etc.)
        #
        def cc_UX_Set_Primary_Mode(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            self._model.set_mode("p", MODES[int(value)])
            print("cc_UX_Set_Primary_Mode: ", value, MODES[int(value)])

            # if value == '':
            #     print("cc_UX_Set_Primary_Mode key error, buffer=", buffer)
            # self.mode_Button['text'] = EEPROM.modeNum_To_TextDict[value]
            # if self.cwTX_OffsetFlag and (
            #         EEPROM.modeNum_To_TextDict[value] == "CWL" or EEPROM.modeNum_To_TextDict[value] == "CWU"):
            #     #
            #     #   We are showing the TX frequency on the VFO so need to offset it
            #     #
            #     self.theVFO_Object.set_CW_OffsetforTX("ON")
            # else:
            #     self.theVFO_Object.set_CW_OffsetforTX("OFF")
            #
            # if self.theSDR != None:
            #     self.theSDR.set_mode(self.mode_Button['text'].replace("CWL", "CW").replace("CWU", "CW"))
            #
            # if self.channelsWindow != None:
            #     # Only update frequency if the channel window has been created once
            #     self.channelsWindow.update_Current_Mode(self.mode_Button['text'])

        #
        #   The "va" command indicates assignment of vfoA to new frequency
        #
        def va_UX_Set_VFO_A_Frequency(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            self._model.set_frequency("a", int(value))
            print("va_UX_Set_VFO_A_Frequency: ", value)
            # if (self.channelsWindow != None) and (self.channelsWindow.scanRunning):
            #     # print("***Ignoring va command as we're scanning***")
            #     return  # ignore the VFO A command during scanning as it can be out of order
            #
            # value = self._extract_value(buffer, 10, len(buffer) - 3)

            # if (self.vfo_VAR.get()== self.VFO_A):       #update displayed frequency
            # if (self.vfo_Button['text'] == self.VFO_A):  # update displayed frequency
            #     self.theVFO_Object.setPrimaryVFO(value)  # MJH dont we need to update vfoa and vfob directly
            #
            # else:
            #     self.theVFO_Object.setSecondaryVFO(value)

        #
        #   The "ca" command indicates assignment of a new mode to vfoA
        #
        def ca_UX_Set_VFO_A_Mode(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            self._model.set_mode("a", MODES[int(value)])
            print("ca_UX_Set_VFO_A_Mode: ", value, MODES[int(value)])
            # if (self.channelsWindow != None) and (self.channelsWindow.scanRunning):
            #     # print("***Ignoring ca command as we're scanning***")
            #     return  # ignore the VFO A command during scanning  as it can be out of order
            #
            # value = self._extract_value(buffer, 10, len(buffer) - 3)
            #
            # if value == '4pm.vb.val=100980':
            #     print("ca_UX_Set_VFO_A_Mode error 4pm.vb.val=100980, buffer:", buffer)
            #
            # if (self.vfo_Button['text'] == self.VFO_A):
            #
            #     self.mode_Button['text'] = EEPROM.modeNum_To_TextDict[value]
            # else:
            #     self.theVFO_Object.setSecondaryMode(EEPROM.modeNum_To_TextDict[value])

        #
        #   The "vb" command indicates assignment of vfoB to new frequency
        #
        def vb_UX_Set_VFO_B_Frequency(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            self._model.set_frequency("b", int(value))
            print("vb_UX_Set_VFO_B_Frequency: ", value)
            #
            # if (self.channelsWindow != None) and (self.channelsWindow.scanRunning):
            #     return  # ignore the VFO B command during scanning as it can be out of order
            #
            # value = self._extract_value(buffer, 10, len(buffer) - 3)
            #
            # if (self.vfo_Button['text'] == self.VFO_B):  # update displayed frequency
            #     self.theVFO_Object.setPrimaryVFO(value)
            # else:
            #     self.theVFO_Object.setSecondaryVFO(value)  # need formatted here too

        #
        #   This sets VFO B to a new mode
        #
        def cb_UX_Set_VFO_B_Mode(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            self._model.set_mode("b", MODES[int(value)])
            print("cb_UX_Set_VFO_B_Mode: ", value, MODES[int(value)])
            #
            # if (self.channelsWindow != None) and (self.channelsWindow.scanRunning):
            #     return  # ignore the VFO B command during scanning as it can be out of order
            #
            # value = self._extract_value(buffer, 10, len(buffer) - 3)
            #
            # if (self.vfo_Button['text'] == self.VFO_B):  # update displayed frequency
            #     self.mode_Button['text'] = EEPROM.modeNum_To_TextDict[value]
            # else:
            #     self.theVFO_Object.secondary_Mode_Label['text'] = EEPROM.modeNum_To_TextDict[value]

        #
        #   The "vt" command stores the CW tone
        #
        def vt_UX_SET_CW_Tone(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vt_UX_SET_CW_Tone: ", value)
            # The transmit frequency in a CW mode is displayed offset by this,
            # so the model needs it -- without this the offset used whatever
            # RadioModel defaulted to rather than what the rig reported.
            self._model.cw_tone = int(value)

        #
        #   The "ck" command stores which cw key is being used
        #
        def ck_UX_Set_CW_Key_Type(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("ck_UX_Set_CW_Key_Type: ", value)
            # if value == '':
            #     print("ck_UX_Set_CW_Key_Type error, buffer:", buffer)
            # self.key_type_value_Label['text'] = gv.CW_KeyType[value]

        #
        #   The "vs" command stores words/minute
        #
        def vs_UX_Set_CW_Speed(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vs_UX_Set_CW_Speed: ", value)
            # self.key_speed_value_Label['text'] = str(int(1200 / int(value)))

        #
        #   The "vy" command stores delay returning after last cw character
        #
        def vy_UX_Set_CW_Delay_Returning_to_RX(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("vy_UX_Set_CW_Delay_Returning_to_RX: ", value)
            # self.delay_returning_to_rx_value_Label['text'] = str(int(value) * 10)

        #
        #   The "ve" command stores delay prior to TX 1st cw character
        #
        def ve_UX_Set_CW_Delay_Starting_TX(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("ve_UX_Set_CW_Delay_Starting_TX: ", value)
            # self.delay_starting_tx_value_Label['text'] = str(int(value) * 2)

        #
        #   Returns active VFO, VFO-A=0, VFO-B=1
        #
        def cv_UX_VFO_Toggle(self, buffer):
            value = self._extract_value(buffer, 10, len(buffer) - 3)
            print("cv_UX_VFO_Toggle: ", value)
            # WHICH IS PRIMARY, not an instruction to exchange the two.
            # 0 is A, 1 is B.
            self._model.set_active("a" if int(value) == 0 else "b")

            # A transmit write borrows the primary slot; this is the step
            # that tells us the borrow happened. See set_role_frequency.
            #
            # Through _radio_link: these handlers live in the inner reader
            # class, so `self` here is the reader, not the link that owns the
            # sequence.
            if self._radio_link._tx_write_state:
                self._radio_link._advance_tx_write("cv")
                return
            # self.theVFO_Object.toggleVFO()
            # self.vfo_Button['text'] = self.Text_To_VFO[value]  # Update Label on button

        ########################################################################################
        #   End processing of commands sent by MCU to Screen
        ########################################################################################


    #   Radio Commands
    ########################################################################################
    #   These routines are called to tell the MCU that an action has happened in the UX.
    #   Typically these should be used by the UX Callbacks
    ########################################################################################
    #
    #   This command sends a request via loopback to retrieve any stored settings for
    #   DSP
    #
    def req_DSP_EEPROM_settings(self):
        print("req_DSP_EEPROM_settings")

        # nMyAddr = random.randint(5,255)
        nMyAddr = 69
        command = [self.toRadioCommandDict["TS_"
                                           "CMD_LOOPBACK0"],
                   nMyAddr,  # Random number, probably no reason at moment
                   2,  # Command 2 is to retrieve all the EEPROM
                   0x6a,  # Indicates that this is for DSP
                   (nMyAddr + 2 + 0x6a) % 256  # Checksum
                   ]

        self.sendCommandToMCU(bytes(command))

    def Req_Channel_Freqs(self):
        print("Req_Channel_Freqs")
        #
        # base = EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.lsb]
        #
        # for i in range(EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.totalSlots]):
        #     command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #                base,
        #                EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.msb],
        #                EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.memLength],
        #                EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.charFlag]
        #                ]
        #     self.memoryQueue.append("Freq")  # Add  it to queue to be processed when MCU responds
        #     self.sendCommandToMCU(bytes(command))
        #     base += EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.memOffset]
        #
        # base = EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.lsb]

    def Req_Channel_Labels(self):
        print("Req_Channel_Labels")
        # base = EEPROM.Mem_Address["channel_Label"][EEPROM.lsb]
        # for i in range(EEPROM.Mem_Address["channel_Label"][EEPROM.totalSlots]):
        #     command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #                base,
        #                EEPROM.Mem_Address["channel_Label"][EEPROM.msb],
        #                EEPROM.Mem_Address["channel_Label"][EEPROM.memLength],
        #                EEPROM.Mem_Address["channel_Label"][EEPROM.charFlag]
        #                ]
        #     self.memoryQueue.append("Label")
        #     self.sendCommandToMCU(bytes(command))
        #     base += EEPROM.Mem_Address["channel_Label"][EEPROM.memOffset]
        #
        # base = EEPROM.Mem_Address["channel_Label"][EEPROM.lsb]

    def Req_Channel_Show_Labels(self):
        print("Req_Channel_Show_Labels")
        # base = EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.lsb]
        # for i in range(EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.totalSlots]):
        #     command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #                base,
        #                EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.msb],
        #                EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.memLength],
        #                EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.charFlag]
        #                ]
        #     self.memoryQueue.append("ShowLabel")
        #     self.sendCommandToMCU(bytes(command))
        #     base += EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.memOffset]
        #
        # base = EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.lsb]

    def Req_Master_Cal(self, setter_CB):
        print("Req_Master_CAL")

        # self.Master_Cal_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.lsb],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.msb],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.memLength],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.charFlag]
        #            ]
        #
        # self.memoryQueue.append("MasterCal")  # tell the command that receives the data what is it for
        #
        # self.sendCommandToMCU(bytes(command))

    def Req_SSB_BFO(self, setter_CB):
        print("Req_SSB_BFO")

        # self.SSB_BFO_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.lsb],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.msb],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.memLength],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.charFlag]
        #            ]
        # self.memoryQueue.append("SSB_BFO")
        # self.sendCommandToMCU(bytes(command))

    def Req_CW_BFO(self, setter_CB):
        print("Req_CW_BFO")

        # self.CW_BFO_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.memLength],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.charFlag]
        #            ]
        #
        # self.memoryQueue.append("CW_BFO")
        # self.sendCommandToMCU(bytes(command))

    def Req_Factory_Master_Cal(self, setter_CB):
        print("Req_Factory_Master_Cal")

        # self.Factory_Master_Cal_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["factory_master_cal"][EEPROM.lsb],
        #            EEPROM.Mem_Address["factory_master_cal"][EEPROM.msb],
        #            EEPROM.Mem_Address["factory_master_cal"][EEPROM.memLength],
        #            EEPROM.Mem_Address["factory_master_cal"][EEPROM.charFlag]
        #            ]
        #
        # self.memoryQueue.append("Factory_MasterCal")  # tell the command that receives the data what is it for
        #
        # self.sendCommandToMCU(bytes(command))

    def Req_Factory_SSB_BFO(self, setter_CB):
        print("Req_Factory_SSB_BFO")

        # self.Factory_SSB_BFO_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["factory_ssb_bfo"][EEPROM.lsb],
        #            EEPROM.Mem_Address["factory_ssb_bfo"][EEPROM.msb],
        #            EEPROM.Mem_Address["factory_ssb_bfo"][EEPROM.memLength],
        #            EEPROM.Mem_Address["factory_ssb_bfo"][EEPROM.charFlag]
        #            ]
        #
        # self.memoryQueue.append("Factory_SSB_BFO")
        # self.sendCommandToMCU(bytes(command))

    def Req_Factory_CW_Speed(self, setter_CB):
        print("Req_Factory_CW_Speed")

        # self.Factory_CW_Speed_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["factory_cw_wpm"][EEPROM.lsb],
        #            EEPROM.Mem_Address["factory_cw_wpm"][EEPROM.msb],
        #            EEPROM.Mem_Address["factory_cw_wpm"][EEPROM.memLength],
        #            EEPROM.Mem_Address["factory_cw_wpm"][EEPROM.charFlag]
        #            ]
        #
        # self.memoryQueue.append("Factory_CW_Speed")
        # self.sendCommandToMCU(bytes(command))

    def Req_Factory_CW_Sidetone(self, setter_CB):
        print("Req_Factory_CW_Sidetone")

        # self.Factory_CW_Sidetone_Setter = setter_CB
        #
        # command = [self.toRadioCommandDict["TS_CMD_READMEM"],
        #            EEPROM.Mem_Address["factory_cw_sidetone"][EEPROM.lsb],
        #            EEPROM.Mem_Address["factory_cw_sidetone"][EEPROM.msb],
        #            EEPROM.Mem_Address["factory_cw_sidetone"][EEPROM.memLength],
        #            EEPROM.Mem_Address["factory_cw_sidetone"][EEPROM.charFlag]
        #            ]
        #
        # self.memoryQueue.append("Factory_CW_Sidetone")
        # self.sendCommandToMCU(bytes(command))

    def Freq_Encode(self, freq):
        print("freq_Encode")

        encodedBytes = bytearray()
        intFreq = int(freq)
        encodedBytes.append(intFreq & 0xff)

        intFreq = (intFreq >> 8)
        encodedBytes.append(intFreq & 0xff)

        intFreq = (intFreq >> 8)
        encodedBytes.append(intFreq & 0xff)

        intFreq = (intFreq >> 8)
        encodedBytes.append(intFreq & 0xff)

        return encodedBytes

    def Set_Master_Cal(self, cal):
        print("Set_Master_Cal")

        #
        #   Now have to write it to EEPROM as this is not one of the values that are automatically saved to EEPROM
        #   This requires reboot to take effect
        #

        # checksum = (EEPROM.Mem_Address["master_cal"][EEPROM.lsb] + EEPROM.Mem_Address["master_cal"][EEPROM.msb]
        #             + EEPROM.Mem_Address["master_cal"][EEPROM.memLength]) % 256
        #
        # fourBytes = self.Freq_Encode(str(cal))
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.lsb],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.msb],
        #            EEPROM.Mem_Address["master_cal"][EEPROM.memLength],
        #            checksum,
        #            fourBytes[0],
        #            fourBytes[1],
        #            fourBytes[2],
        #            fourBytes[3]
        #            ]
        # self.sendCommandToMCU(bytes(command))

    def Set_SSB_BFO(self, cal):
        print("Set_SSB_BFO")

        #
        #   Now have to write it to EEPROM as this is not one of the values that are automatically saved to EEPROM
        #   This requires reboot to take effect
        #

        # checksum = (EEPROM.Mem_Address["ssb_bfo"][EEPROM.lsb] + EEPROM.Mem_Address["ssb_bfo"][EEPROM.msb]
        #             + EEPROM.Mem_Address["ssb_bfo"][EEPROM.memLength]) % 256
        #
        # fourBytes = self.Freq_Encode(str(cal))
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.lsb],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.msb],
        #            EEPROM.Mem_Address["ssb_bfo"][EEPROM.memLength],
        #            checksum,
        #            fourBytes[0],
        #            fourBytes[1],
        #            fourBytes[2],
        #            fourBytes[3]
        #            ]
        # self.sendCommandToMCU(bytes(command))

    def Set_CW_BFO(self, cal):
        print("setting the CW BFO in the radio")

        #
        #   Now have to write it to EEPROM as this is not one of the values that are automatically saved to EEPROM
        #   This requires reboot to take effect
        #
        # print("lsb=", hex(EEPROM.Mem_Address["cw_bfo"][EEPROM.lsb]), "msb=",
        #       hex(EEPROM.Mem_Address["cw_bfo"][EEPROM.msb]),
        #       "memlength=", EEPROM.Mem_Address["cw_bfo"][EEPROM.memLength])
        #
        # checksum = (EEPROM.Mem_Address["cw_bfo"][EEPROM.lsb] + EEPROM.Mem_Address["cw_bfo"][EEPROM.msb]
        #             + EEPROM.Mem_Address["cw_bfo"][EEPROM.memLength]) % 256
        #
        # fourBytes = self.Freq_Encode(str(cal))
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_bfo"][EEPROM.memLength],
        #            checksum,
        #            fourBytes[0],
        #            fourBytes[1],
        #            fourBytes[2],
        #            fourBytes[3]
        #            ]
        # self.sendCommandToMCU(bytes(command))

    def Set_Tuning_Preset(self, rate: bytes):
        print("Set_Tuning_Preset")
        command = [self.toRadioCommandDict["TS_CMD_TUNESTEP"], rate, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def set_role_frequency(self, role, hz):
        """
        Moves what a role is tuned to.

        RECEIVE is easy: the rig writes to whichever VFO is primary, and
        receive IS the primary one.

        TRANSMIT in split is not. The rig can only write to the primary VFO,
        and transmit is by definition the one that is not -- so the frequency
        has to be written while the other VFO is borrowed into the primary
        slot, then the slot handed back.

        ONE STEP AT A TIME, EACH WAITING FOR ITS CONFIRMATION. Sending
        toggle, frequency and toggle back-to-back is precisely the overrun
        the MCU headroom settings exist to prevent, and worse, the write can
        reach the rig before the toggle has taken effect -- putting the
        frequency on the wrong VFO. The sequence below sends the next command
        only when the rig has confirmed the last one.
        """
        # The caller hands us what the operator SEES. The rig wants what
        # goes in the VFO, and the two differ by the CW sidetone on transmit.
        # role_to_vfo_hz is the inverse of role_frequency -- without it a
        # 1 kHz step moved 400 Hz while the tone was 600.
        print("set_role_frequency", role, hz)
        hz = self._model.role_to_vfo_hz(role, hz)
        print("new hz =", hz, "rit offset", self._model.rit_offset)

        if role == "rx" or not self._model.split:
            print("link 1780", role, self._model.split)
            self.set_frequency(hz)
            return

        self._begin_tx_write(hz)

    def _leave_rit(self):
        """
        Puts receive back where RIT started, then forgets the base.

        TURNING RIT OFF MEANS ZERO OFFSET: receive and transmit on the same
        frequency again. Under the rig's model the VFO was what moved, so it
        has to be sent back to the base -- and the firmware does not do that
        by itself, which left receive stranded wherever it had been tuned.

        Called however RIT ends: from the RIT button, or as a side effect of
        turning split on, which the firmware reports as cr_ 0 just before
        cs_ 1.
        """
        base = self._model.rit_base_hz
        self._model.rit_base_hz = 0
        if base and base != self._model.frequency(self._model.rx_vfo):
            # Receive is the primary VFO, so an ordinary write lands on it.
            self.set_frequency(base)

    def set_mode_everywhere(self, mode):
        """
        Sets the mode on the active VFO, and in split on the other one too.

        THE RIG KEEPS A MODE PER VFO, and set_mode only reaches the primary.
        So in split, choosing USB changed receive and left transmit in CW --
        the transmit readout kept its sidetone offset because, as far as the
        rig was concerned, the transmit VFO really was still in CW.

        The mode picker sits between the two frequency panels because it
        acts on both, and that is what an operator means by it: split is a
        different FREQUENCY for transmit, not a different mode. Cross-mode
        split exists, but it is rare enough to be done deliberately from the
        rig rather than be what the everyday control does.

        Out of split the two VFOs are not in use together, so only the
        active one changes -- the standby VFO keeps whatever it had.
        """
        self.set_mode(mode)
        if self._model.split:
            # The non-primary VFO, written by borrowing the slot. Its
            # frequency is sent back unchanged: the borrow is there for the
            # mode, and re-sending the frequency it already has is harmless.
            other = self._model.tx_vfo
            self.root.after(
                STEP_SETTLE_MS,
                lambda: self._begin_borrowed_write(
                    self._model.frequency(other), mode=mode))

    def copy_active_to_other(self):
        """
        Copies the active VFO's frequency and mode to the other one.

        THE FIRMWARE HAS NO COMMAND FOR THIS, so it is done the only way the
        rig allows: the same borrow the transmit write uses. The rig writes
        only to whichever VFO is primary, so the other one has to be made
        primary for a moment.

        Worth noticing that "write to the VFO that is not primary" is the
        real operation here, and transmit-in-split was only its first use.
        """
        which = self._model.active
        self._begin_borrowed_write(self._model.frequency(which),
                                   mode=self._model.mode_of(which))

    def _begin_tx_write(self, vfo_hz):
        """Transmit's entry to the borrow. Carries no mode change."""
        self._begin_borrowed_write(vfo_hz)

    def _begin_borrowed_write(self, vfo_hz, mode=None):
        """
        Starts, or queues, a borrow-write-return against the non-primary VFO.

        TAKES A VFO VALUE, not a displayed one. set_role_frequency has
        already applied role_to_vfo_hz, and the follow-up path re-enters here
        rather than going back through that -- converting a second time would
        add the sidetone twice.

        `mode` is written alongside the frequency while the slot is borrowed,
        for callers that are copying a whole VFO rather than retuning one.
        """
        hz = vfo_hz

        if self._tx_write_state:
            # COALESCED, not dropped.
            #
            # The dial produces detents faster than a borrow-write-return can
            # complete, so a wheel spin arrives here many times over. Dropping
            # them meant the whole spin moved one step. Keeping only the
            # LATEST is right: the intermediate frequencies were never wanted,
            # only passed through on the way to this one.
            self._tx_write_next = int(hz)
            self._tx_write_next_mode = mode
            return

        self._tx_write_hz = int(hz)
        self._tx_write_mode = mode
        self._tx_write_state = "awaiting-borrow"

        # The borrow is a mechanism, not a state worth showing. Without this
        # the receive panel briefly displays the transmit frequency, because
        # the rig really does make the other VFO primary and really does say
        # so. Accurate, and confusing.
        self._model.suspend_notifications()

        self._arm_tx_write_timeout()
        self.toggle_vfo()

    def _advance_tx_write(self, confirmation, value=None):
        """
        Drives the borrow-write-return sequence, one confirmation at a time.

        CONFIRMS THE TOGGLES, FIRES THE WRITE AND MOVES ON.

        The two are not alike. A lost TOGGLE leaves the rig on the wrong VFO
        with the roles inverted -- receive showing transmit -- and it does
        not heal, because the next write goes to the wrong VFO as well. That
        has to be confirmed.

        A lost WRITE costs nothing. The rig reports the VFO's frequency
        afterwards whatever happened, so the model learns the truth either
        way; the worst case is a dial that did not move, which the operator
        sees and repeats.

        Waiting for the write's confirmation as well was where most of the
        difficulty came from -- a toggle makes the rig report the borrowed
        VFO's own frequency first, which looks exactly like an answer to the
        write, and the rig rounds what it stores to the tuning preset, so
        the value it reports need not be the value that was sent. Neither
        problem exists once nothing is waiting for it.
        """
        state = self._tx_write_state
        self._arm_tx_write_timeout()

        if state == "awaiting-borrow" and confirmation == "cv":
            # The other VFO is primary now. Write to it, then hand the slot
            # back -- both deferred, because a command arriving while the rig
            # is still reporting a VFO change is sometimes simply dropped.
            self._tx_write_state = "awaiting-return"
            self.root.after(
                STEP_SETTLE_MS,
                lambda hz=self._tx_write_hz: self._write_then_return(hz))

        elif state == "awaiting-return" and confirmation == "cv":
            self._tx_write_state = None
            self._tx_write_hz = None
            if self._tx_write_timer is not None:
                try:
                    self.root.after_cancel(self._tx_write_timer)
                except Exception:
                    pass
                self._tx_write_timer = None
            # The slot is back. One redraw now, showing the result.
            self._model.resume_notifications()

            # Anything the dial asked for while that was running goes next,
            # after the rig's trailing reports have settled -- starting it
            # inline means the new sequence consumes one of them as its own
            # confirmation and never sees the cv it is waiting for.
            if self._tx_write_next is not None:
                pending, self._tx_write_next = self._tx_write_next, None
                pending_mode = self._tx_write_next_mode
                self._tx_write_next_mode = None
                if pending != self._model.frequency(self._model.tx_vfo):
                    self.root.after(
                        FOLLOW_UP_DELAY_MS,
                        lambda hz=pending, m=pending_mode:
                            self._begin_borrowed_write(hz, mode=m))

    def _write_then_return(self, hz):
        """
        Sends the frequency, and the mode if one was asked for, then hands
        the primary slot back.

        Neither write is acknowledged and nothing waits for them. The toggle
        that follows is, which is what the sequence is really protecting.
        """
        print("link 1913", hz)
        self.set_frequency(hz)

        if self._tx_write_mode is not None:
            mode, self._tx_write_mode = self._tx_write_mode, None
            # After a settle of its own: two commands back to back while the
            # rig is mid-write is the same hazard as writing mid-toggle.
            self.root.after(STEP_SETTLE_MS,
                            lambda m=mode: self.set_mode(m))
            self.root.after(STEP_SETTLE_MS * 2, self.toggle_vfo)
            return

        self.root.after(STEP_SETTLE_MS, self.toggle_vfo)

    def _arm_tx_write_timeout(self):
        """
        Restarts the deadline for the next confirmation.

        THIS IS WHAT MAKES WAITING SAFER THAN NOT WAITING. A sequence that
        waits for confirmations is correct even when timing varies, and it
        never blocks the interface -- each command goes out on a different
        pass of the event loop rather than behind a sleep(). What it risks in
        exchange is a lost reply leaving the flag set, after which every
        later transmit write is silently dropped.

        A deadline closes that. The worst case becomes one write that does
        not happen, announced on the console, instead of a feature that stops
        working until the application is restarted.
        """
        if self._tx_write_timer is not None:
            try:
                self.root.after_cancel(self._tx_write_timer)
            except Exception:
                pass
        self._tx_write_timer = self.root.after(TX_WRITE_TIMEOUT_MS,
                                               self._abandon_tx_write)

    def _abandon_tx_write(self):
        """
        Gives up on a sequence that never finished.

        HANDS THE PRIMARY SLOT BACK if the borrow got that far.

        Leaving it was the earlier behaviour and it is wrong: after the first
        toggle the rig really is on the other VFO, so rx_vfo becomes that one
        and the RECEIVE panel starts showing the transmit frequency. It looks
        like the two VFOs are bleeding into each other, and it persists until
        something else toggles -- which is why the receive readout settles on
        one or two values rather than wandering.

        The model is left alone -- the rig is the authority on which VFO is
        primary and reports it -- but the borrow itself has to be undone,
        because nothing else will.
        """
        self._tx_write_timer = None
        if self._tx_write_state:
            print("tx write abandoned in state", self._tx_write_state,
                  "-- no confirmation within", TX_WRITE_TIMEOUT_MS, "ms")
            # Undo the borrow if it happened. awaiting-borrow means the
            # first toggle was sent but never confirmed, so the rig may or
            # may not have moved -- its own cv will tell us either way, and
            # toggling on a guess would be worse than leaving it.
            if self._tx_write_state == "awaiting-return":
                print("   handing the primary slot back")
                self.toggle_vfo()

            # Whatever went wrong, the view must not stay frozen: release the
            # suspend so the operator sees where the radio actually is, even
            # if that is mid-borrow.
            self._model.resume_notifications()
        self._tx_write_state = None
        self._tx_write_hz = None
        # Dropped too: a pending value fired against an abandoned sequence
        # would start a new one from a state we have just admitted we do not
        # trust. The next dial turn will ask again.
        self._tx_write_next = None

    def set_frequency(self, value):
        print("Set_New_Frequency",value)
        fourBytes = self.Freq_Encode(value)
        command = [self.toRadioCommandDict["TS_CMD_FREQ"], fourBytes[0], fourBytes[1], fourBytes[2], fourBytes[3]]
        self.sendCommandToMCU(bytes(command))

    #
    #   This function tells the Radio that a new mode has been selected for
    #   the primary (displayed) VFO. After receiving the new mode, the
    #   Radio will separately send back the mode to the UX
    #
    def set_mode(self, mode):
        print("Set_Mode")
        encode_mode = MODES.index(mode)
        command = [self.toRadioCommandDict["TS_CMD_MODE"], encode_mode, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    #
    #   This function tells the Radio that a button up or down has been pushed
    #   in the UX. After receiving this command the radio will send back a new frequency
    #   and mode for the displayed VOF
    #
    def Change_Band(self, direction):
        print("Change_Band")
        command = [self.toRadioCommandDict["TS_CMD_BAND"], direction, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Tuning_Rate(self, value: bytes):
        print("Tuning_Rate")
        command = [self.toRadioCommandDict["TS_CMD_TUNESTEP"], value, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def toggle_vfo(self):
        print("Toggle_VFO")
        command = [self.toRadioCommandDict["TS_CMD_VFO"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Toggle_Lock(self):
        print("Toggle_Lock")
        command = [self.toRadioCommandDict["TS_CMD_LOCK"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Toggle_Speaker(self):
        print("Toggle_Speaker")
        command = [self.toRadioCommandDict["TS_CMD_SDR"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Toggle_Stop(self):
        print("Toggle_Stop")
        command = [self.toRadioCommandDict["TS_CMD_TXSTOP"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Toggle_Split(self):
        print("Toggle_Split")
        command = [self.toRadioCommandDict["TS_CMD_SPLIT"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Toggle_RIT(self):
        print("Toggle_RIT")
        command = [self.toRadioCommandDict["TS_CMD_RIT"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Set_ATT(self, value: bytes):
        print("setting att, value =", value)
        command = [self.toRadioCommandDict["TS_CMD_ATT"], value, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Toggle_IFS(self):
        print("toggling IFS")
        command = [self.toRadioCommandDict["TS_CMD_IFS"], 0, 0, 0, 0]
        self.sendCommandToMCU(bytes(command))

    def Set_IFS_Level(self, level):
        print("setting IFS Level", level)
        encodedBytes = self.Freq_Encode(str(level))

        command = [self.toRadioCommandDict["TS_CMD_IFSVALUE"], encodedBytes[0], encodedBytes[1], encodedBytes[2], 0]
        self.sendCommandToMCU(bytes(command))

    def Set_CW_Tone(self, tone):
        print("setting CW_Tone")

        #
        #   Now have to write it to EEPROM as this is not one of the values that are automatically saved to EEPROM
        #   This requires reboot to take effect
        #

        # checksum = (EEPROM.Mem_Address["cw_sidetone"][EEPROM.lsb] + EEPROM.Mem_Address["cw_sidetone"][EEPROM.msb]
        #             + EEPROM.Mem_Address["cw_sidetone"][EEPROM.memLength]) % 256
        #
        # fourBytes = self.Freq_Encode(str(tone))
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["cw_sidetone"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_sidetone"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_sidetone"][EEPROM.memLength],
        #            checksum,
        #            fourBytes[0],
        #            fourBytes[1],
        #            fourBytes[2],
        #            fourBytes[3]
        #            ]
        # self.sendCommandToMCU(bytes(command))

    def Set_CW_Keytype(self, keyType):
        print("setting CW_Keytype")
        #
        #   first send command to officially change the keytype
        #
        # command = [self.toRadioCommandDict["TS_CMD_KEYTYPE"], gv.CW_KeyValue[keyType], 0, 0, 0]
        # self.sendCommandToMCU(bytes(command))
        #
        #   Now have to write it to EEPROM as this is not one of the values that are automatically saved to EEPROM
        #

        # checksum = (EEPROM.Mem_Address["cw_key_type"][EEPROM.lsb] + EEPROM.Mem_Address["cw_key_type"][EEPROM.msb]
        #             + EEPROM.Mem_Address["cw_key_type"][EEPROM.memLength]) % 256
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["cw_key_type"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_key_type"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_key_type"][EEPROM.memLength],
        #            checksum,
        #            gv.CW_KeyValue[keyType]
        #            ]
        # self.sendCommandToMCU(bytes(command))

    def Set_CW_Speed(self, keySpeed):
        print("setting CW_Speed")

        #
        #
        #   first send command to officially change the key speed
        #   wpm directly saved. It is the dot length which is 1200/wpm
        #

        dotLength_ms = int(1200 / int(keySpeed))
        command = [self.toRadioCommandDict["TS_CMD_WPM"], dotLength_ms, 0, 0]
        self.sendCommandToMCU(bytes(command))

        #
        #   Now have to write it to EEPROM as this is not one of the values that are automatically saved to EEPROM
        #

        # checksum = (EEPROM.Mem_Address["cw_wpm"][EEPROM.lsb] + EEPROM.Mem_Address["cw_wpm"][EEPROM.msb]
        #             + EEPROM.Mem_Address["cw_wpm"][EEPROM.memLength]) % 256
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["cw_wpm"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_wpm"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_wpm"][EEPROM.memLength],
        #            checksum,
        #            dotLength_ms,  # Eeprom allows up to two bytes for adjusted key,
        #            # but keychage without reboot only 1 byte
        #            0, 0, 0
        #            ]
        #
        # self.sendCommandToMCU(bytes(command))

    def Set_CW_Delay_Starting_TX(self, startTXDelay):
        print("setting CW_Delay_Starting_TX")
        #
        #   Requires reboot to take effect
        #
        #
        # adjust the wpm speed to format of EEPROM
        #
        # adjustedStartTXDelay = int(int(startTXDelay) / 2)

        #
        #   write it to EEPROM as will be picked up on next reboot
        #

        # checksum = (EEPROM.Mem_Address["cw_Delay_Starting_TX"][EEPROM.lsb] + EEPROM.Mem_Address["cw_Delay_Starting_TX"][
        #     EEPROM.msb]
        #             + EEPROM.Mem_Address["cw_Delay_Starting_TX"][EEPROM.memLength]) % 256
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["cw_Delay_Starting_TX"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_Delay_Starting_TX"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_Delay_Starting_TX"][EEPROM.memLength],
        #            checksum,
        #            adjustedStartTXDelay
        #            ]
        #
        # self.sendCommandToMCU(bytes(command))

    def Set_CW_Delay_Returning_To_RX(self, returnRXDelay):
        print("setting CW_Delay_Returning_To_RX")
        # value stored to eeprom needs to divided by 10
        #
        #   Requires reboot to take effect
        #
        #
        # adjust the wpm speed to format of EEPROM
        #
        # adjustedReturnToRXDelay = int(int(returnRXDelay) / 10)

        #
        #   write it to EEPROM as will be picked up on next reboot
        #

        # checksum = (EEPROM.Mem_Address["cw_Delay_Returning_to_RX"][EEPROM.lsb] +
        #             EEPROM.Mem_Address["cw_Delay_Returning_to_RX"][EEPROM.msb]
        #             + EEPROM.Mem_Address["cw_Delay_Returning_to_RX"][EEPROM.memLength]) % 256
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            EEPROM.Mem_Address["cw_Delay_Returning_to_RX"][EEPROM.lsb],
        #            EEPROM.Mem_Address["cw_Delay_Returning_to_RX"][EEPROM.msb],
        #            EEPROM.Mem_Address["cw_Delay_Returning_to_RX"][EEPROM.memLength],
        #            checksum,
        #            adjustedReturnToRXDelay
        #            ]
        #
        # self.sendCommandToMCU(bytes(command))

    def Write_EEPROM_Channel_FreqMode(self, channelNum, freq, mode):
        print("write EEPROM Channel FreqMode")

        # encoded_data = (int(freq) & 0x1FFFFFFF) + ((int(EEPROM.Text_To_ModeNum[mode]) & 0x7) << 29)
        #
        # encodedBytes = self.Freq_Encode(str(encoded_data))
        #
        # lsb = (channelNum * EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.memOffset]) + \
        #       EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.lsb]
        # msb = EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.msb]
        # totalBytes = EEPROM.Mem_Address["channel_freq_Mode"][EEPROM.memLength]
        #
        # checksum = (lsb + msb + totalBytes) % 256
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            lsb,
        #            msb,
        #            totalBytes,
        #            checksum,
        #            encodedBytes[0], encodedBytes[1], encodedBytes[2], encodedBytes[3]
        #            ]
        #
        # self.sendCommandToMCU(bytes(command))

    def Write_EEPROM_Channel_Label(self, channelNum, label):
        print("write EEPROM Channel Label")

        # if channelNum > EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.totalSlots]:
        #     return
        #
        # lsb = ((channelNum * EEPROM.Mem_Address["channel_Label"][EEPROM.memOffset]) +
        #        EEPROM.Mem_Address["channel_Label"][EEPROM.lsb])
        # msb = EEPROM.Mem_Address["channel_Label"][EEPROM.msb]
        # totalBytes = EEPROM.Mem_Address["channel_Label"][EEPROM.memLength]
        #
        # # strip blanks
        # noBlankLabel = label.strip()
        # labelBytes = bytes(noBlankLabel.ljust(totalBytes), 'utf-8')
        #
        # checksum = (lsb + msb + totalBytes) % 256
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            lsb,
        #            msb,
        #            totalBytes,
        #            checksum,
        #            labelBytes[0], labelBytes[1], labelBytes[2], labelBytes[3], labelBytes[4]
        #            ]
        #
        # self.sendCommandToMCU(bytes(command))

    def Write_EEPROM_Channel_ShowLabel(self, channelNum, showLabel):
        print("write EEPROM Channel ShowLabel")

        #
        #   Don't write to EEPROMs showLabels 10+
        #
        # if channelNum > EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.totalSlots]:
        #     return
        #
        # lsb = (channelNum * EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.memOffset]) + \
        #       EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.lsb]
        # msb = EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.msb]
        # totalBytes = EEPROM.Mem_Address["channel_ShowLabel"][EEPROM.memLength]
        #
        # checksum = (lsb + msb + totalBytes) % 256
        #
        # if showLabel == 'Yes':
        #     value = 0x3
        # else:
        #     value = 0x0
        #
        # command = [self.toRadioCommandDict["TS_CMD_WRITEMEM"],
        #            lsb,
        #            msb,
        #            totalBytes,
        #            checksum,
        #            value
        #            ]
        #
        # self.sendCommandToMCU(bytes(command))

        # print("Updated Spectrum Options", command)

    def startFrequencySpectrumScan(self, freq, count):
        print("startFrequencySpectrumScan")

        # print("Starting Frequency Spectrum Scan", freq, count)
        self.mainWindow.startingspectrum = True

        # for _ in range(count):
        #     self.memoryQueue.append("Spectrum_Scan")

        # print('queue lenght=',self.lenMemoryQueue())

        fourBytes = self.Freq_Encode(str(freq))

        command = [self.toRadioCommandDict["TS_CMD_SPECTRUM"], fourBytes[0], fourBytes[1], fourBytes[2], fourBytes[3]]
        self.sendCommandToMCU(bytes(command))
        # print("started spectrum", command)

        for _ in range(count):
            self.memoryQueue.append("Spectrum_Scan")

        # print('queue length=', self.lenMemoryQueue())

    def Set_Spectrum_Mode(self, value):
        print("setting Spectrum_Mode")

        # MyAddr = random.randint(5, 255)     # Not clear why a specific address is needed. Perhaps for future?
        # MyAddr = 66
        # DSPCode = 0x6A  # magic# indicating that this loop back result of DSP
        #
        # checksum = ((MyAddr + DSPCode + value) % 256)
        #
        # command = [self.toRadioCommandDict["TS_CMD_LOOPBACK0"], MyAddr, value, DSPCode, checksum]
        # # print("sending loopback command", "myaddr:", hex(MyAddr), "value passed:", hex(value), "dspcode:",hex(DSPCode), "checksum:", hex(checksum))
        #
        # self.sendCommandToMCU(bytes(command))

    def Set_Signal_Value(self, scale_value):
        print("setting Signal_Value, scale_value:", scale_value)
        # MyAddr = 55
        # DSPCode = 0x6A
        # value = int(scale_value) + 146
        #
        # checksum = ((MyAddr + DSPCode + value) % 256)
        # command = [self.toRadioCommandDict["TS_CMD_LOOPBACK0"], MyAddr, value, DSPCode, checksum]
        # # print("sending loopback command for signal", "myaddr:", hex(MyAddr), "value passed:", hex(int(scale_value)), "adjusted value", hex(value), "dspcode:", hex(DSPCode),
        # #       "checksum:", hex(checksum))
        # self.sendCommandToMCU(bytes(command))

    def Set_DSP_State(self, flag):
        print("setting DSP_State")

        # if flag == "True":  # Turn DSP On
        #     value = 51  # This turns the DSP on and sets it into Spectrum Mode
        #     self.mainWindow.frequencySpectrumMode == "FreqScan"
        #     gv.config.set_DSP_Switch(flag)
        #     # print("turning on DSP")
        #
        # else:
        #     value = 50  # This turns off the DSP
        #     # print("Turning off DSP")
        #     gv.config.set_DSP_Switch(flag)
        #     self.mainWindow.mainScreenPlotter.clearCanvas()
        #
        # # MyAddr = random.randint(5, 255)     # Not clear why a specific address is needed. Perhaps for future?
        # MyAddr = 88
        # DSPCode = 0x6A  # magic# indicating that this loop back result of DSP
        #
        # checksum = ((MyAddr + DSPCode + value) % 256)
        #
        # command = [self.toRadioCommandDict["TS_CMD_LOOPBACK0"], MyAddr, value, DSPCode, checksum]
        # # print("sending loopback command", "myaddr:", hex(MyAddr), "value passed:", hex(value), "dspcode:",hex(DSPCode), "checksum:", hex(checksum))
        #
        # self.sendCommandToMCU(bytes(command))

    #
    #   Send command to MCU
    #
    def sendCommandToMCU(self, commandList):
        currentTime = timer()
        timeDiff = currentTime - self.time_of_last_sent

        if (timeDiff < MCU_COMMAND_HEADROOM):
            sleep(MCU_COMMAND_HEADROOM - timeDiff)
        self.time_of_last_sent = timer()

        self.tx_to_mcu_preamble = b'\x59\x58\x68'  # all commands to MCU must start with these three bytes
        self.tx_to_mcu_postscript = b'\xff\xff\x73'  # all commands to MCU must end with these three numbers

        try:
            self.port.write(self.tx_to_mcu_preamble + commandList + self.tx_to_mcu_postscript)
        except:
            messagebox.showerror(title="ERROR Communicating with uBITX",
                                 message="Communication failed with uBITX.", parent=self,
                                 DETAILS="Did you select the right com port?\n" + "You selected: " + self.tty)
            sys.exit(-1)

    def popMemoryQueue(self):
        if len(self.memoryQueue) == 0:
            return None
        else:
            return self.memoryQueue.pop(0)

    def lenMemoryQueue(self):
        return len(self.memoryQueue)


