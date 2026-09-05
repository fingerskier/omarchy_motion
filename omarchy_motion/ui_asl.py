"""ASL command editor and local calibration controls for the settings notebook."""
import copy
import tkinter as tk
from tkinter import messagebox, ttk

from . import calibration, config, service
from .asl import COMMANDS, DIGITS, canonical_symbol


def build(parent, c, fields, flags, background):
    flags["chords_enabled"] = tk.BooleanVar(value=c["chords_enabled"])
    ttk.Checkbutton(parent, text="Enable two-hand ASL commands", variable=flags["chords_enabled"]).pack(anchor="w", pady=6)
    ttk.Label(parent, text="Right = W/M/F/T · Left = 0–9 or O (zero) · Hold both signs, then release\nW: workspace · M: move window · F: fullscreen · T: floating · 0/O means workspace 10").pack(anchor="w", pady=4)
    holder = ttk.Frame(parent)
    holder.pack(fill="x")
    tree = ttk.Treeview(holder, columns=("enabled", "right", "left", "action", "value"), show="tree headings", height=9)
    tree.heading("#0", text="Mapping")
    tree.column("#0", width=160)
    for key in ("enabled", "right", "left", "action", "value"):
        tree.heading(key, text=key.title())
        tree.column(key, width=120 if key == "action" else 65)
    scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    tree.pack(side="left", fill="x", expand=True)

    def refresh():
        tree.delete(*tree.get_children())
        for i, b in enumerate(c["chords"]):
            tree.insert("", "end", iid=str(i), text=b["name"], values=("On" if b["enabled"] else "Off", b["right"], b["left"], b["action"], b["value"]))

    def change(remove=False):
        if tree.selection():
            i = int(tree.selection()[0])
            if remove:
                c["chords"].pop(i)
            else:
                c["chords"][i]["enabled"] = not c["chords"][i]["enabled"]
            refresh()

    buttons = ttk.Frame(parent)
    buttons.pack(fill="x", pady=6)
    ttk.Button(buttons, text="Enable / disable selected", command=change).pack(side="left")
    ttk.Button(buttons, text="Remove selected", command=lambda: change(True)).pack(side="left", padx=6)
    builder = ttk.LabelFrame(parent, text="Build or edit a chord", padding=8)
    builder.pack(fill="x")
    variables = {key: tk.StringVar(value=value) for key, value in (("name", "W + 3"), ("right", "W"), ("left", "3"), ("action", "workspace"), ("value", "3"))}
    for i, (key, var) in enumerate(variables.items()):
        ttk.Label(builder, text=key.title()).grid(row=0, column=i, sticky="w")
        choices = {"right": COMMANDS, "left": DIGITS + ("O",), "action": config.CHORD_ACTIONS}.get(key)
        widget = ttk.Combobox(builder, textvariable=var, values=choices, state="readonly", width=15) if choices else ttk.Entry(builder, textvariable=var, width=14)
        widget.grid(row=1, column=i, padx=(0, 6))

    def fill(_):
        if tree.selection():
            for key, var in variables.items():
                var.set(str(c["chords"][int(tree.selection()[0])][key]))

    tree.bind("<<TreeviewSelect>>", fill)

    def add():
        try:
            b = {key: var.get() for key, var in variables.items()}
            b.update(value=int(b["value"]), enabled=True)
            candidate = copy.deepcopy(c)
            existing = next((x for x in candidate["chords"] if x["name"] == b["name"]), None)
            if existing is not None:
                b["enabled"] = existing["enabled"]
                existing.update(b)
            else:
                candidate["chords"].append(b)
            candidate = config.validate(candidate)
            c.update(candidate)
            refresh()
        except ValueError as e:
            messagebox.showerror("Invalid chord", str(e), parent=parent)

    ttk.Button(builder, text="Add / update by name", command=add).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
    ttk.Label(builder, text="Value: workspace 1–10, or 1=on / 0=off for fullscreen and floating").grid(row=3, column=0, columnspan=5, sticky="w")
    timing = ttk.Frame(parent)
    timing.pack(fill="x", pady=8)
    for key, label in (("chord_hold", "Hold seconds"), ("chord_release", "Release seconds")):
        fields[key] = tk.StringVar(value=str(c[key]))
        ttk.Label(timing, text=label).pack(side="left")
        ttk.Entry(timing, textvariable=fields[key], width=6).pack(side="left", padx=8)

    capture = ttk.LabelFrame(parent, text="Calibrate an unclear sign (especially M and T)", padding=8)
    capture.pack(fill="x")
    hand, symbol = tk.StringVar(value="Right"), tk.StringVar(value="M")
    row = ttk.Frame(capture)
    row.pack(fill="x")
    hand_box = ttk.Combobox(row, textvariable=hand, values=("Right", "Left"), state="readonly", width=7)
    hand_box.pack(side="left")
    symbol_box = ttk.Combobox(row, textvariable=symbol, values=COMMANDS, state="readonly", width=4)
    symbol_box.pack(side="left", padx=6)

    def choose(_):
        choices = COMMANDS if hand.get() == "Right" else DIGITS + ("O",)
        symbol_box.configure(values=choices)
        symbol.set(choices[0])

    hand_box.bind("<<ComboboxSelected>>", choose)

    def start():
        calibration.request(hand.get(), symbol.get())
        background(lambda: service.control("on"))

    def clear():
        latest = config.read()
        latest["asl_samples"].get(hand.get(), {}).pop(canonical_symbol(symbol.get()), None)
        config.save(latest)
        background(lambda: service.control("restart") if service.state() == "active" else None)

    def guarded(fn):
        try:
            fn()
        except (OSError, ValueError) as e:
            messagebox.showerror("Calibration", str(e), parent=parent)

    ttk.Button(row, text="Capture sample", command=lambda: guarded(start)).pack(side="left")
    ttk.Button(row, text="Clear samples", command=lambda: guarded(clear)).pack(side="left", padx=6)
    ttk.Label(capture, text="Watch the preview countdown, then hold still. Desktop actions pause during capture.\nSaves numeric handshape features locally; up to five samples per symbol.").pack(anchor="w", pady=4)
    state = tk.StringVar(value="No calibration requested")
    ttk.Label(capture, textvariable=state, wraplength=750).pack(anchor="w")

    def poll():
        state.set(calibration.status() or "No calibration requested")
        parent.after(500, poll)

    poll()
    refresh()
    return refresh
