# Virtual-pointer bindings

`wlr-virtual-pointer-unstable-v1.xml` comes from
https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-virtual-pointer-unstable-v1.xml
(retrieved 2026-09-05). The upstream MIT notice is retained in the XML and generated
Python module. PyWayland 0.4.19 generated the bindings; the only postprocessing
replaces `from .wayland import` with `from pywayland.protocol.wayland import` so
the extension shares PyWayland's core interface types.

Regenerate from the repository root using the project Python environment:

```python
from pathlib import Path
from pywayland.scanner import Protocol

folder = Path('omarchy_motion/protocols')
protocol = Protocol.parse_file(str(folder / 'wlr-virtual-pointer-unstable-v1.xml'))
imports = {'wl_seat': 'wayland', 'wl_output': 'wayland'}
imports.update({i.name: protocol.name for i in protocol.interface})
protocol.output(str(folder), imports)
output = folder / 'wlr_virtual_pointer_unstable_v1.py'
output.write_text(output.read_text().replace('from .wayland import', 'from pywayland.protocol.wayland import'))
```
