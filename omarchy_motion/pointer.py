"""A persistent, output-mapped Wayland pointer for windows and layer surfaces."""
import errno
import math
import select
import time


class VirtualPointer:
    def __init__(self, output_name, width, height):
        # Dry-run and hardware-free engine tests do not import native bindings.
        from pywayland.client import Display
        from pywayland.protocol.wayland import WlOutput
        from .protocols.wlr_virtual_pointer_unstable_v1 import ZwlrVirtualPointerManagerV1

        self.display = Display()
        self.pointer = None
        self.manager = None
        self.outputs = {}
        self.names = {}
        self.failure = None
        self.target = None
        self.manager_id = None
        self.closed = False
        self.width, self.height = max(1, round(width)), max(1, round(height))
        try:
            self.display.connect()
            self.registry = self.display.get_registry()

            def added(registry, name, interface, version):
                # Exceptions in CFFI event callbacks are otherwise swallowed.
                try:
                    if interface == ZwlrVirtualPointerManagerV1.name and version >= 2:
                        self.manager = registry.bind(name, ZwlrVirtualPointerManagerV1, 2)
                        self.manager_id = name
                    elif interface == WlOutput.name and version >= 4:
                        output = registry.bind(name, WlOutput, 4)
                        self.outputs[name] = output
                        output.dispatcher["name"] = lambda proxy, label: self.names.update({label: name})
                except Exception as e:
                    self.failure = f"Cannot bind Wayland global: {e}"

            def removed(registry, name):
                if name in (self.target, self.manager_id):
                    self.failure = "Pointer output or protocol removed; restart Motion after display changes"

            self.registry.dispatcher["global"] = added
            self.registry.dispatcher["global_remove"] = removed
            self._sync()
            self._sync()
            if self.manager is None:
                raise RuntimeError("Compositor needs zwlr_virtual_pointer_manager_v1 version 2 for pointer control")
            self.target = self.names.get(output_name)
            if self.target is None:
                raise RuntimeError(f"Wayland output {output_name!r} not found (wl_output version 4 required)")
            self.pointer = self.manager.create_virtual_pointer_with_output(None, self.outputs[self.target])
            self._sync()
        except BaseException:
            self.close()
            raise

    def _flush(self, deadline):
        from pywayland import ffi
        while self.display.flush() < 0:
            if ffi.errno != errno.EAGAIN:
                raise OSError(ffi.errno, "Cannot send virtual-pointer events")
            if not select.select([], [self.display.get_fd()], [], max(0, deadline - time.monotonic()))[1]:
                raise TimeoutError("Wayland output stalled")

    def _sync(self):
        """Bounded roundtrip: observe protocol errors, removals and backpressure."""
        done = False
        callback = self.display.sync()

        def completed(proxy, serial):
            nonlocal done
            done = True

        callback.dispatcher["done"] = completed
        deadline = time.monotonic() + 3
        try:
            self._flush(deadline)
            while not done:
                self.display.dispatch(block=False)
                if done:
                    break
                if not select.select([self.display.get_fd()], [], [], max(0, deadline - time.monotonic()))[0]:
                    raise TimeoutError("Wayland compositor did not acknowledge pointer events")
                self.display.dispatch(block=True)
            if self.failure:
                raise RuntimeError(self.failure)
        finally:
            callback.destroy()

    @staticmethod
    def timestamp():
        return int(time.monotonic() * 1000) & 0xFFFFFFFF

    def move(self, position):
        if self.closed:
            raise RuntimeError("Virtual pointer is closed")
        if not all(math.isfinite(v) for v in position):
            raise ValueError("Pointer coordinates must be finite")
        x, y = (max(0, min(1, v)) for v in position)
        self.pointer.motion_absolute(self.timestamp(), round(x * (self.width - 1)),
                                     round(y * (self.height - 1)), self.width, self.height)
        self.pointer.frame()
        self._sync()

    def click(self):
        if self.closed:
            raise RuntimeError("Virtual pointer is closed")
        # Queue both states before flushing, each with its own frame. Shutdown
        # during the roundtrip cannot strand a held button on a live device.
        timestamp = self.timestamp()
        self.pointer.button(timestamp, 272, 1)
        self.pointer.frame()
        self.pointer.button(timestamp, 272, 0)
        self.pointer.frame()
        self._sync()

    def close(self):
        if not self.closed:
            self.closed = True
            self.display.disconnect()
