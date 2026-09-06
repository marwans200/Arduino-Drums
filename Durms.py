import json
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import serial
import mido
from serial.tools import list_ports

mido.set_backend("mido.backends.rtmidi")


APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "settings.json"


PAD_NAMES = [
    "Kick",
    "Snare",
    "Hi-hat",
    "Tom 1",
    "Tom 2",
    "Floor tom",
    "Crash",
    "Ride",
]

PAD_NOTES = [
    36,
    38,
    42,
    48,
    45,
    41,
    49,
    51,
]


class NanoDrumUI(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("Nano Drum MIDI")
        self.geometry("1000x850")
        self.minsize(900, 700)

        self.ser = None
        self.midi = None
        self.reader_thread = None
        self.running = False

        self.msg_queue = queue.Queue()

        self.hit_count = 0
        self.last_hit_time = 0.0

        # -------------------------------------------------
        # General settings
        # -------------------------------------------------

        self.vars = {
            "serial_port": tk.StringVar(value=""),
            "baud": tk.IntVar(value=115200),

            "midi_port": tk.StringVar(value=""),

            "channel": tk.IntVar(value=1),
            "note": tk.IntVar(value=38),
            "use_incoming_note": tk.BooleanVar(value=True),

            "note_off_ms": tk.IntVar(value=10),

            "vel_min": tk.IntVar(value=1),
            "vel_max": tk.IntVar(value=127),
            "vel_scale": tk.DoubleVar(value=1.0),
            "vel_curve": tk.DoubleVar(value=1.0),

            "transpose": tk.IntVar(value=0),
        }

        # -------------------------------------------------
        # Per-pad trigger thresholds
        # -------------------------------------------------

        self.hit_thresholds = [
            tk.IntVar(value=40)
            for _ in range(8)
        ]

        self.reset_thresholds = [
            tk.IntVar(value=20)
            for _ in range(8)
        ]

        # -------------------------------------------------
        # Live ADC values
        # -------------------------------------------------

        self.raw_values = [
            tk.IntVar(value=0)
            for _ in range(8)
        ]

        self.raw_bars = []
        self.raw_labels = []

        # -------------------------------------------------
        # Status
        # -------------------------------------------------

        self.status_var = tk.StringVar(
            value="Disconnected"
        )

        self.last_var = tk.StringVar(
            value="No hits yet"
        )

        self.count_var = tk.StringVar(
            value="0"
        )

        self.activity_var = tk.StringVar(
            value="Waiting"
        )

        # -------------------------------------------------
        # Load/build
        # -------------------------------------------------

        self.load_settings()
        self.build_ui()
        self.refresh_ports()

        self.after(30, self.process_queue)

        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        root = ttk.Frame(
            self,
            padding=14
        )

        root.pack(
            fill="both",
            expand=True
        )

        # -------------------------------------------------
        # Title
        # -------------------------------------------------

        title = ttk.Label(
            root,
            text="NANO DRUM MIDI",
            font=("Segoe UI", 20, "bold")
        )

        title.pack(
            anchor="w"
        )

        subtitle = ttk.Label(
            root,
            text="Arduino Nano serial drum triggers → virtual MIDI → Ableton",
            font=("Segoe UI", 10)
        )

        subtitle.pack(
            anchor="w",
            pady=(0, 12)
        )

        # =================================================
        # CONNECTION
        # =================================================

        conn = ttk.LabelFrame(
            root,
            text="Connection",
            padding=10
        )

        conn.pack(
            fill="x",
            pady=(0, 10)
        )

        ttk.Label(
            conn,
            text="Nano COM port"
        ).grid(
            row=0,
            column=0,
            sticky="w"
        )

        self.combo_serial = ttk.Combobox(
            conn,
            textvariable=self.vars["serial_port"],
            state="readonly",
            width=22
        )

        self.combo_serial.grid(
            row=1,
            column=0,
            padx=(0, 8),
            sticky="ew"
        )

        ttk.Label(
            conn,
            text="Baud"
        ).grid(
            row=0,
            column=1,
            sticky="w"
        )

        ttk.Entry(
            conn,
            textvariable=self.vars["baud"],
            width=12
        ).grid(
            row=1,
            column=1,
            padx=(0, 8),
            sticky="w"
        )

        ttk.Label(
            conn,
            text="MIDI output"
        ).grid(
            row=0,
            column=2,
            sticky="w"
        )

        self.combo_midi = ttk.Combobox(
            conn,
            textvariable=self.vars["midi_port"],
            state="readonly",
            width=28
        )

        self.combo_midi.grid(
            row=1,
            column=2,
            padx=(0, 8),
            sticky="ew"
        )

        ttk.Button(
            conn,
            text="Refresh",
            command=self.refresh_ports
        ).grid(
            row=1,
            column=3,
            padx=4
        )

        self.connect_btn = ttk.Button(
            conn,
            text="Connect",
            command=self.toggle_connection
        )

        self.connect_btn.grid(
            row=1,
            column=4,
            padx=4
        )

        for c in range(5):
            conn.columnconfigure(
                c,
                weight=1 if c in (0, 2) else 0
            )

        # =================================================
        # MIDI SETTINGS
        # =================================================

        settings = ttk.LabelFrame(
            root,
            text="MIDI settings",
            padding=10
        )

        settings.pack(
            fill="x",
            pady=(0, 10)
        )

        ttk.Label(
            settings,
            text="Channel"
        ).grid(
            row=0,
            column=0,
            sticky="w"
        )

        ttk.Spinbox(
            settings,
            from_=1,
            to=16,
            textvariable=self.vars["channel"],
            width=8
        ).grid(
            row=1,
            column=0,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Label(
            settings,
            text="MIDI note"
        ).grid(
            row=0,
            column=1,
            sticky="w"
        )

        ttk.Spinbox(
            settings,
            from_=0,
            to=127,
            textvariable=self.vars["note"],
            width=8
        ).grid(
            row=1,
            column=1,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Checkbutton(
            settings,
            text="Use note from Nano",
            variable=self.vars["use_incoming_note"]
        ).grid(
            row=1,
            column=2,
            padx=(0, 18),
            sticky="w"
        )

        ttk.Label(
            settings,
            text="Transpose"
        ).grid(
            row=0,
            column=3,
            sticky="w"
        )

        ttk.Spinbox(
            settings,
            from_=-48,
            to=48,
            textvariable=self.vars["transpose"],
            width=8
        ).grid(
            row=1,
            column=3,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Label(
            settings,
            text="Note-off (ms)"
        ).grid(
            row=0,
            column=4,
            sticky="w"
        )

        ttk.Spinbox(
            settings,
            from_=1,
            to=2000,
            textvariable=self.vars["note_off_ms"],
            width=10
        ).grid(
            row=1,
            column=4,
            padx=(0, 12),
            sticky="w"
        )

        # =================================================
        # VELOCITY
        # =================================================

        vel = ttk.LabelFrame(
            root,
            text="Velocity processing",
            padding=10
        )

        vel.pack(
            fill="x",
            pady=(0, 10)
        )

        ttk.Label(
            vel,
            text="Minimum"
        ).grid(
            row=0,
            column=0,
            sticky="w"
        )

        ttk.Spinbox(
            vel,
            from_=1,
            to=127,
            textvariable=self.vars["vel_min"],
            width=8
        ).grid(
            row=1,
            column=0,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Label(
            vel,
            text="Maximum"
        ).grid(
            row=0,
            column=1,
            sticky="w"
        )

        ttk.Spinbox(
            vel,
            from_=1,
            to=127,
            textvariable=self.vars["vel_max"],
            width=8
        ).grid(
            row=1,
            column=1,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Label(
            vel,
            text="Scale"
        ).grid(
            row=0,
            column=2,
            sticky="w"
        )

        ttk.Spinbox(
            vel,
            from_=0.1,
            to=3.0,
            increment=0.05,
            textvariable=self.vars["vel_scale"],
            width=8
        ).grid(
            row=1,
            column=2,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Label(
            vel,
            text="Curve"
        ).grid(
            row=0,
            column=3,
            sticky="w"
        )

        ttk.Spinbox(
            vel,
            from_=0.25,
            to=4.0,
            increment=0.05,
            textvariable=self.vars["vel_curve"],
            width=8
        ).grid(
            row=1,
            column=3,
            padx=(0, 12),
            sticky="w"
        )

        ttk.Label(
            vel,
            text="Curve 1.0 = linear • >1 = softer • <1 = harder"
        ).grid(
            row=0,
            column=4,
            rowspan=2,
            padx=(12, 0),
            sticky="w"
        )

        # =================================================
        # DRUM TRIGGER THRESHOLDS
        # =================================================

        trigger = ttk.LabelFrame(
            root,
            text="Drum trigger thresholds",
            padding=10
        )

        trigger.pack(
            fill="x",
            pady=(0, 10)
        )

        headers = [
            "Input",
            "Pad",
            "MIDI",
            "Hit threshold",
            "Reset threshold",
            "Raw ADC"
        ]

        for col, text in enumerate(headers):
            ttk.Label(
                trigger,
                text=text,
                font=("Segoe UI", 9, "bold")
            ).grid(
                row=0,
                column=col,
                padx=5,
                pady=(0, 5),
                sticky="w"
            )

        for i in range(8):

            ttk.Label(
                trigger,
                text=f"A{i}"
            ).grid(
                row=i + 1,
                column=0,
                padx=5,
                sticky="w"
            )

            ttk.Label(
                trigger,
                text=PAD_NAMES[i]
            ).grid(
                row=i + 1,
                column=1,
                padx=5,
                sticky="w"
            )

            ttk.Label(
                trigger,
                text=str(PAD_NOTES[i])
            ).grid(
                row=i + 1,
                column=2,
                padx=5,
                sticky="w"
            )

            ttk.Spinbox(
                trigger,
                from_=0,
                to=1023,
                textvariable=self.hit_thresholds[i],
                width=10
            ).grid(
                row=i + 1,
                column=3,
                padx=5
            )

            ttk.Spinbox(
                trigger,
                from_=0,
                to=1023,
                textvariable=self.reset_thresholds[i],
                width=10
            ).grid(
                row=i + 1,
                column=4,
                padx=5
            )

            raw_label = ttk.Label(
                trigger,
                textvariable=self.raw_values[i],
                width=6
            )

            raw_label.grid(
                row=i + 1,
                column=5,
                padx=5
            )

            self.raw_labels.append(raw_label)

        ttk.Button(
            trigger,
            text="Apply thresholds",
            command=self.send_all_thresholds
        ).grid(
            row=9,
            column=0,
            columnspan=6,
            pady=(10, 0)
        )

        # =================================================
        # LIVE MONITOR
        # =================================================

        monitor = ttk.LabelFrame(
            root,
            text="Live monitor",
            padding=10
        )

        monitor.pack(
            fill="both",
            expand=True
        )

        top = ttk.Frame(
            monitor
        )

        top.pack(
            fill="x"
        )

        self.status_label = ttk.Label(
            top,
            textvariable=self.status_var,
            font=("Segoe UI", 11, "bold")
        )

        self.status_label.pack(
            side="left"
        )

        ttk.Label(
            top,
            text="Hits:"
        ).pack(
            side="right",
            padx=(20, 4)
        )

        ttk.Label(
            top,
            textvariable=self.count_var
        ).pack(
            side="right"
        )

        ttk.Label(
            monitor,
            textvariable=self.last_var
        ).pack(
            anchor="w",
            pady=(8, 4)
        )

        self.activity = ttk.Progressbar(
            monitor,
            orient="horizontal",
            mode="determinate",
            maximum=127
        )

        self.activity.pack(
            fill="x",
            pady=(0, 8)
        )

        # -------------------------------------------------
        # Raw ADC meters
        # -------------------------------------------------

        raw_frame = ttk.LabelFrame(
            monitor,
            text="Raw ADC peaks",
            padding=8
        )

        raw_frame.pack(
            fill="x",
            pady=(0, 8)
        )

        for i in range(8):

            row = ttk.Frame(
                raw_frame
            )

            row.pack(
                fill="x",
                pady=1
            )

            ttk.Label(
                row,
                text=f"A{i} {PAD_NAMES[i]}",
                width=18
            ).pack(
                side="left"
            )

            bar = ttk.Progressbar(
                row,
                orient="horizontal",
                mode="determinate",
                maximum=1023
            )

            bar.pack(
                side="left",
                fill="x",
                expand=True,
                padx=5
            )

            self.raw_bars.append(bar)

            ttk.Label(
                row,
                textvariable=self.raw_values[i],
                width=6
            ).pack(
                side="right"
            )

        # -------------------------------------------------
        # Log
        # -------------------------------------------------

        self.log = tk.Text(
            monitor,
            height=10,
            wrap="none",
            font=("Consolas", 10),
            state="disabled"
        )

        self.log.pack(
            fill="both",
            expand=True
        )

        # =================================================
        # Bottom buttons
        # =================================================

        bottom = ttk.Frame(
            root
        )

        bottom.pack(
            fill="x",
            pady=(10, 0)
        )

        ttk.Button(
            bottom,
            text="Save settings",
            command=self.save_settings
        ).pack(
            side="left"
        )

        ttk.Button(
            bottom,
            text="Clear log",
            command=self.clear_log
        ).pack(
            side="left",
            padx=8
        )

        ttk.Label(
            bottom,
            text="Ableton: enable Track for the virtual MIDI input."
        ).pack(
            side="right"
        )

    # =====================================================
    # PORT HANDLING
    # =====================================================

    def refresh_ports(self):

        current_com = self.vars["serial_port"].get()

        ports = [
            p.device
            for p in list_ports.comports()
        ]

        self.combo_serial["values"] = ports

        if current_com in ports:
            self.vars["serial_port"].set(current_com)

        elif ports:
            self.vars["serial_port"].set(ports[0])

        else:
            self.vars["serial_port"].set("")

        current_midi = self.vars["midi_port"].get()

        try:
            midi_ports = mido.get_output_names()

        except Exception as e:

            midi_ports = []

            self.log_message(
                f"MIDI scan error: {e}"
            )

        self.combo_midi["values"] = midi_ports

        if current_midi in midi_ports:

            self.vars["midi_port"].set(
                current_midi
            )

        else:

            preferred = next(
                (
                    p for p in midi_ports
                    if "Nano Drums" in p
                ),
                midi_ports[0]
                if midi_ports
                else ""
            )

            self.vars["midi_port"].set(
                preferred
            )

    # =====================================================
    # CONNECTION
    # =====================================================

    def toggle_connection(self):

        if self.running:
            self.disconnect()

        else:
            self.connect()

    def connect(self):

        port = self.vars["serial_port"].get().strip()
        midi_port = self.vars["midi_port"].get().strip()

        if not port:

            messagebox.showerror(
                "No COM port",
                "Select the Arduino Nano COM port."
            )

            return

        if not midi_port:

            messagebox.showerror(
                "No MIDI port",
                "Create a loopMIDI port first, or select another MIDI output."
            )

            return

        try:

            baud = int(
                self.vars["baud"].get()
            )

            self.ser = serial.Serial(
                port,
                baud,
                timeout=0.1
            )

            # Classic Nano resets when serial opens.
            time.sleep(1.8)

            self.ser.reset_input_buffer()

            self.midi = mido.open_output(
                midi_port
            )

        except Exception as e:

            if self.ser:

                try:
                    self.ser.close()
                except Exception:
                    pass

            self.ser = None
            self.midi = None

            messagebox.showerror(
                "Connection error",
                str(e)
            )

            return

        self.running = True

        self.connect_btn.configure(
            text="Disconnect"
        )

        self.status_var.set(
            f"CONNECTED • {port} → {midi_port}"
        )

        self.activity_var.set(
            "Listening"
        )

        self.reader_thread = threading.Thread(
            target=self.serial_reader,
            daemon=True
        )

        self.reader_thread.start()

        self.log_message(
            "Connected."
        )

        self.log_message(
            "Waiting for NOTE,n,v and RAW,pad,adc messages..."
        )

        # Send current threshold settings
        self.send_all_thresholds()

    def disconnect(self):

        self.running = False

        if self.ser:

            try:
                self.ser.close()
            except Exception:
                pass

        self.ser = None

        if self.midi:

            try:
                self.midi.close()
            except Exception:
                pass

        self.midi = None

        self.connect_btn.configure(
            text="Connect"
        )

        self.status_var.set(
            "Disconnected"
        )

        self.activity["value"] = 0

        self.log_message(
            "Disconnected."
        )

    # =====================================================
    # SEND COMMANDS TO ARDUINO
    # =====================================================

    def send_command(self, command):

        if not self.ser or not self.running:
            return False

        try:

            self.ser.write(
                (command + "\n").encode(
                    "utf-8"
                )
            )

            return True

        except Exception as e:

            self.log_message(
                f"Serial write error: {e}"
            )

            return False

    def send_all_thresholds(self):

        if not self.ser or not self.running:

            self.log_message(
                "Nano not connected — thresholds not sent."
            )

            return

        for i in range(8):

            try:

                hit = max(
                    0,
                    min(
                        1023,
                        int(
                            self.hit_thresholds[i].get()
                        )
                    )
                )

                reset = max(
                    0,
                    min(
                        1023,
                        int(
                            self.reset_thresholds[i].get()
                        )
                    )
                )

                # Hit threshold
                self.send_command(
                    f"SET,HIT,{i},{hit}"
                )

                # Reset threshold
                self.send_command(
                    f"SET,RESET,{i},{reset}"
                )

            except Exception as e:

                self.log_message(
                    f"Threshold error A{i}: {e}"
                )

        self.log_message(
            "Thresholds sent to Nano."
        )

    # =====================================================
    # SERIAL READER
    # =====================================================

    def serial_reader(self):

        while self.running and self.ser:

            try:

                raw = self.ser.readline()

                if not raw:
                    continue

                line = raw.decode(
                    "utf-8",
                    errors="replace"
                ).strip()

                if line:

                    self.msg_queue.put(
                        (
                            "serial",
                            line
                        )
                    )

            except (
                serial.SerialException,
                OSError
            ) as e:

                self.msg_queue.put(
                    (
                        "error",
                        f"Serial error: {e}"
                    )
                )

                break

            except Exception as e:

                self.msg_queue.put(
                    (
                        "error",
                        f"Reader error: {e}"
                    )
                )

                break

    # =====================================================
    # QUEUE
    # =====================================================

    def process_queue(self):

        try:

            while True:

                kind, value = (
                    self.msg_queue.get_nowait()
                )

                if kind == "serial":

                    self.handle_serial_line(
                        value
                    )

                elif kind == "error":

                    self.log_message(
                        value
                    )

                    self.after(
                        0,
                        self.disconnect
                    )

        except queue.Empty:
            pass

        self.after(
            30,
            self.process_queue
        )

    # =====================================================
    # SERIAL MESSAGE PARSER
    # =====================================================

    def handle_serial_line(self, line):

        parts = line.split(",")

        if not parts:
            return

        message_type = (
            parts[0]
            .strip()
            .upper()
        )

        # =================================================
        # RAW ADC
        #
        # Arduino sends:
        #
        # RAW,1,693
        #
        # meaning:
        # A1 peak = 693
        # =================================================

        if message_type == "RAW":

            if len(parts) != 3:

                self.log_message(
                    f"Bad RAW message: {line}"
                )

                return

            try:

                pad = int(
                    parts[1]
                )

                raw_adc = int(
                    parts[2]
                )

            except ValueError:

                self.log_message(
                    f"Bad RAW message: {line}"
                )

                return

            if not 0 <= pad < 8:
                return

            raw_adc = max(
                0,
                min(
                    1023,
                    raw_adc
                )
            )

            # Update displayed ADC
            self.raw_values[pad].set(
                raw_adc
            )

            # Update ADC bar
            if pad < len(self.raw_bars):

                self.raw_bars[pad]["value"] = (
                    raw_adc
                )

            # Log it
            self.log_message(
                f"RAW  A{pad} {PAD_NAMES[pad]:10s} = {raw_adc:4d}/1023"
            )

            return

        # =================================================
        # MIDI NOTE
        #
        # Arduino sends:
        #
        # NOTE,38,87
        # =================================================

        if message_type != "NOTE":

            self.log_message(
                f"Nano: {line}"
            )

            return

        if len(parts) != 3:

            self.log_message(
                f"Bad NOTE message: {line}"
            )

            return

        try:

            incoming_note = int(
                parts[1]
            )

            incoming_velocity = int(
                parts[2]
            )

        except ValueError:

            self.log_message(
                f"Bad NOTE message: {line}"
            )

            return

        if not 0 <= incoming_note <= 127:
            return

        incoming_velocity = max(
            1,
            min(
                127,
                incoming_velocity
            )
        )

        # Process MIDI velocity
        velocity = self.process_velocity(
            incoming_velocity
        )

        # -------------------------------------------------
        # Determine MIDI note
        # -------------------------------------------------

        if self.vars[
            "use_incoming_note"
        ].get():

            note = incoming_note

        else:

            note = int(
                self.vars["note"].get()
            )

        note += int(
            self.vars["transpose"].get()
        )

        note = max(
            0,
            min(
                127,
                note
            )
        )

        # -------------------------------------------------
        # MIDI channel
        # -------------------------------------------------

        channel = max(
            1,
            min(
                16,
                int(
                    self.vars["channel"].get()
                )
            )
        ) - 1

        note_off_ms = max(
            1,
            int(
                self.vars["note_off_ms"].get()
            )
        )

        # -------------------------------------------------
        # MIDI output
        # -------------------------------------------------

        if not self.midi:
            return

        try:

            self.midi.send(
                mido.Message(
                    "note_on",
                    note=note,
                    velocity=velocity,
                    channel=channel
                )
            )

            # Note-off in separate thread
            threading.Thread(
                target=self.send_note_off,
                args=(
                    note,
                    channel,
                    note_off_ms
                ),
                daemon=True
            ).start()

            # -------------------------------------------------
            # Update UI
            # -------------------------------------------------

            self.hit_count += 1

            self.last_hit_time = (
                time.time()
            )

            self.count_var.set(
                str(self.hit_count)
            )

            self.last_var.set(
                f"Note {note} • "
                f"Velocity {velocity} • "
                f"Raw velocity {incoming_velocity}"
            )

            self.activity["value"] = (
                velocity
            )

            self.log_message(
                f"HIT  note={note:3d}  "
                f"velocity={velocity:3d}  "
                f"raw velocity={incoming_velocity:3d}"
            )

        except Exception as e:

            self.log_message(
                f"MIDI error: {e}"
            )

    # =====================================================
    # NOTE OFF
    # =====================================================

    def send_note_off(
        self,
        note,
        channel,
        delay_ms
    ):

        time.sleep(
            delay_ms / 1000.0
        )

        if self.midi:

            try:

                self.midi.send(
                    mido.Message(
                        "note_off",
                        note=note,
                        velocity=0,
                        channel=channel
                    )
                )

            except Exception:
                pass

    # =====================================================
    # VELOCITY PROCESSING
    # =====================================================

    def process_velocity(self, raw):

        raw = max(
            1,
            min(
                127,
                int(raw)
            )
        )

        lo = max(
            1,
            min(
                127,
                int(
                    self.vars["vel_min"].get()
                )
            )
        )

        hi = max(
            lo,
            min(
                127,
                int(
                    self.vars["vel_max"].get()
                )
            )
        )

        scale = max(
            0.01,
            float(
                self.vars["vel_scale"].get()
            )
        )

        curve = max(
            0.05,
            float(
                self.vars["vel_curve"].get()
            )
        )

        # Normalize 1-127 to 0-1
        x = (
            raw - 1
        ) / 126.0

        # Apply scale
        x = max(
            0.0,
            min(
                1.0,
                x * scale
            )
        )

        # Apply curve
        x = x ** curve

        result = round(
            lo + x * (hi - lo)
        )

        return max(
            1,
            min(
                127,
                result
            )
        )

    # =====================================================
    # SETTINGS
    # =====================================================

    def save_settings(self):

        data = {
            k: v.get()
            for k, v in self.vars.items()
        }

        data["hit_thresholds"] = [
            v.get()
            for v in self.hit_thresholds
        ]

        data["reset_thresholds"] = [
            v.get()
            for v in self.reset_thresholds
        ]

        try:

            CONFIG_FILE.write_text(
                json.dumps(
                    data,
                    indent=2
                ),
                encoding="utf-8"
            )

            self.log_message(
                f"Settings saved to {CONFIG_FILE.name}"
            )

        except Exception as e:

            messagebox.showerror(
                "Save error",
                str(e)
            )

    def load_settings(self):

        if not CONFIG_FILE.exists():
            return

        try:

            data = json.loads(
                CONFIG_FILE.read_text(
                    encoding="utf-8"
                )
            )

            # General settings
            for k, value in data.items():

                if k in self.vars:

                    self.vars[k].set(
                        value
                    )

            # Hit thresholds
            if "hit_thresholds" in data:

                values = data[
                    "hit_thresholds"
                ]

                for i in range(
                    min(
                        8,
                        len(values)
                    )
                ):

                    self.hit_thresholds[
                        i
                    ].set(
                        values[i]
                    )

            # Reset thresholds
            if "reset_thresholds" in data:

                values = data[
                    "reset_thresholds"
                ]

                for i in range(
                    min(
                        8,
                        len(values)
                    )
                ):

                    self.reset_thresholds[
                        i
                    ].set(
                        values[i]
                    )

        except Exception:
            pass

    # =====================================================
    # LOGGING
    # =====================================================

    def log_message(self, text):

        timestamp = time.strftime(
            "%H:%M:%S"
        )

        # UI updates should happen on main thread.
        try:

            self.log.configure(
                state="normal"
            )

            self.log.insert(
                "end",
                f"[{timestamp}] {text}\n"
            )

            self.log.see(
                "end"
            )

            self.log.configure(
                state="disabled"
            )

        except tk.TclError:
            pass

    def clear_log(self):

        self.log.configure(
            state="normal"
        )

        self.log.delete(
            "1.0",
            "end"
        )

        self.log.configure(
            state="disabled"
        )

    # =====================================================
    # CLOSE
    # =====================================================

    def on_close(self):

        self.save_settings()

        self.disconnect()

        self.destroy()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    app = NanoDrumUI()

    app.mainloop()