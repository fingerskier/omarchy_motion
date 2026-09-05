"""Small native settings window. Tk is only imported when settings are opened."""
import copy
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import config, service


def launch():
    root = tk.Tk()
    root.title("Omarchy Motion")
    root.geometry("850x720")
    c = config.read()
    results = queue.Queue()
    status = tk.StringVar(value="Checking service…")

    def background(fn):
        def work():
            try:
                fn()
            except Exception as e:
                results.put(str(e))
        threading.Thread(target=work, daemon=True).start()

    def poll_state():
        try:
            current = service.state()
            results.put(("state", current))
        except Exception as e:
            results.put(("state", str(e)))

    def tick():
        while not results.empty():
            item = results.get()
            if isinstance(item, tuple):
                status.set("Motion: " + item[1])
            else:
                messagebox.showerror("Omarchy Motion", item, parent=root)
        root.after(200, tick)

    def poll():
        background(poll_state)
        root.after(2000, poll)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    controls = ttk.Frame(frame)
    controls.pack(fill="x")
    ttk.Label(controls, textvariable=status, font=("", 14)).pack(side="left")
    ttk.Button(controls, text="Switch off", command=lambda: background(lambda: service.control("off"))).pack(side="right")
    ttk.Button(controls, text="Switch on", command=lambda: background(lambda: service.control("on"))).pack(side="right", padx=8)
    ttk.Label(frame, text="Offline hand and body tracking · Changes take effect when saved", padding=(0, 10)).pack(anchor="w")

    tree = ttk.Treeview(frame, columns=("enabled", "hand", "gesture", "action"), show="tree headings", height=8)
    tree.heading("#0", text="Mapping")
    tree.column("#0", width=210)
    for key in ("enabled", "hand", "gesture", "action"):
        tree.heading(key, text=key.title())
        tree.column(key, width=100)
    tree.pack(fill="x")

    def refresh():
        tree.delete(*tree.get_children())
        for i, b in enumerate(c["bindings"]):
            tree.insert("", "end", iid=str(i), text=b["name"], values=("On" if b["enabled"] else "Off", b["hand"], b["gesture"], b["action"]))

    def selected():
        return int(tree.selection()[0]) if tree.selection() else None

    def toggle():
        i = selected()
        if i is not None:
            c["bindings"][i]["enabled"] = not c["bindings"][i]["enabled"]
            refresh()

    def remove():
        i = selected()
        if i is not None:
            c["bindings"].pop(i)
            refresh()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=8)
    ttk.Button(buttons, text="Enable / disable selected", command=toggle).pack(side="left")
    ttk.Button(buttons, text="Remove selected", command=remove).pack(side="left", padx=8)

    builder = ttk.LabelFrame(frame, text="Build or edit a mapping", padding=10)
    builder.pack(fill="x", pady=5)
    variables = {key: tk.StringVar(value=value) for key, value in
                 (("name", "My gesture"), ("hand", "Left"), ("gesture", "hand_raised"), ("action", "toggle_floating"), ("cooldown", "0.8"))}
    for col, (key, var) in enumerate(variables.items()):
        ttk.Label(builder, text=key.title()).grid(row=0, column=col, sticky="w")
        choices = {"hand": ("Left", "Right"), "gesture": config.GESTURES, "action": config.ACTIONS}.get(key)
        widget = ttk.Combobox(builder, textvariable=var, values=choices, state="readonly", width=17) if choices else ttk.Entry(builder, textvariable=var, width=14)
        widget.grid(row=1, column=col, padx=(0, 6))

    def fill(_):
        i = selected()
        if i is not None:
            for key, var in variables.items():
                var.set(str(c["bindings"][i][key]))

    tree.bind("<<TreeviewSelect>>", fill)

    def add():
        try:
            b = {key: var.get() for key, var in variables.items()}
            b.update(cooldown=float(b["cooldown"]), enabled=True)
            candidate = copy.deepcopy(c)
            existing = next((x for x in candidate["bindings"] if x["name"] == b["name"]), None)
            if existing is not None:
                b["enabled"] = existing["enabled"]
                existing.update(b)
            else:
                candidate["bindings"].append(b)
            config.validate(candidate)
            c.update(candidate)
            refresh()
        except ValueError as e:
            messagebox.showerror("Invalid mapping", str(e), parent=root)

    ttk.Button(builder, text="Add / update by name", command=add).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

    tuning = ttk.LabelFrame(frame, text="Camera and gesture tuning", padding=10)
    tuning.pack(fill="x", pady=10)
    fields = {}
    keys = ("camera", "fps", "monitor", "confidence", "smoothing", "cursor_margin", "pinch_threshold", "pinch_release", "swipe_distance", "swipe_seconds")
    for i, key in enumerate(keys):
        fields[key] = tk.StringVar(value=str(c[key]))
        row, col = divmod(i, 2)
        ttk.Label(tuning, text=key.replace("_", " ").title()).grid(row=row, column=col * 2, sticky="w", padx=(0, 12))
        ttk.Entry(tuning, textvariable=fields[key], width=18).grid(row=row, column=col * 2 + 1, padx=(0, 24), pady=2)
    flags = {}
    for i, (key, label) in enumerate((("mirror", "Mirror camera"), ("swap_hands", "Swap hand labels"), ("preview", "Live preview"), ("dry_run", "Test mode (no desktop actions)"))):
        flags[key] = tk.BooleanVar(value=c[key])
        ttk.Checkbutton(tuning, text=label, variable=flags[key]).grid(row=5 + i // 2, column=(i % 2) * 2, columnspan=2, sticky="w")

    def save():
        try:
            candidate = copy.deepcopy(c)
            for key, var in fields.items():
                candidate[key] = config.parse_field(key, var.get())
            candidate.update({key: var.get() for key, var in flags.items()})
            config.save(candidate)
            c.update(candidate)
            background(lambda: service.control("restart") if service.state() == "active" else None)
        except (ValueError, OSError) as e:
            messagebox.showerror("Cannot save settings", str(e), parent=root)

    ttk.Button(frame, text="Save settings", command=save).pack(anchor="e")
    ttk.Label(frame, text="Point with index finger · Pinch middle finger to thumb · Swipe with an open palm\nHand names are your left/right. Enable test mode and preview to check calibration.", padding=(0, 10)).pack(anchor="w")
    refresh()
    poll()
    tick()
    root.mainloop()
