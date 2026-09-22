"""StatusLamp: a small round indicator light for Tk panels.

Used for the MIC indicator on both tabs. Three ovals (halo, body,
specular highlight) fake a lit LED; each state is a palette of those
three colors. States:

- ``green``  good input
- ``amber``  warning (low-quality mic, or a mic that delivers silence)
- ``red``    reserved for hard failures where a dark lamp would hide the
             fact that something is wrong
- ``dark``   no mic input (stream closed or never opened)
"""

import tkinter as tk


class StatusLamp(tk.Canvas):
    PALETTES = {
        # (halo, body, specular)
        "green": ("#1d5a1d", "#33cc33", "#c8ffc8"),
        "amber": ("#5a3a10", "#ffb347", "#ffe9c4"),
        "red":   ("#5a1414", "#ff6060", "#ffd0d0"),
        "dark":  ("#1c1c1c", "#2e2e2e", "#3a3a3a"),
    }

    def __init__(self, parent, size=16, bg="#2A2A2A", state="dark", **kwargs):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, **kwargs)
        # Opt out of any app-wide theme walker that recolors canvases.
        self._skip_theme = True
        self._size = size
        s = size
        pad = max(1, s // 8)
        self._halo = self.create_oval(0, 0, s, s, outline="")
        self._body = self.create_oval(pad, pad, s - pad, s - pad, outline="")
        hi = max(2, s // 4)
        self._spec = self.create_oval(pad + hi // 2, pad + hi // 2,
                                      pad + hi // 2 + hi, pad + hi // 2 + hi,
                                      outline="")
        self._state = None
        self.set_state(state)

    @property
    def state(self):
        return self._state

    def set_state(self, state):
        """Switch the lamp color. No-op when already in that state."""
        if state == self._state:
            return
        halo, body, spec = self.PALETTES[state]
        self.itemconfigure(self._halo, fill=halo)
        self.itemconfigure(self._body, fill=body)
        self.itemconfigure(self._spec, fill=spec)
        self._state = state
