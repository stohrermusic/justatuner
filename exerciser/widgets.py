"""Custom vintage audio equipment widgets."""

import math
import tkinter as tk

class RoundScope(tk.Canvas):
    """Round CRT oscilloscope display with vintage bezel."""

    def __init__(self, parent, size=350, **kwargs):
        bg = kwargs.pop("bg", "#1a1a1a")
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, bg=bg)
        self._size = size
        self._bg = bg
        self._bezel_drawn = False

    def get_draw_area(self):
        """Return (center_x, center_y, usable_radius) for the CRT screen."""
        s = self._size
        cx, cy = s // 2, s // 2
        screen_r = s // 2 - 22
        return cx, cy, screen_r

    def draw_bezel(self):
        """Draw the CRT bezel frame (call once)."""
        self.delete("bezel")
        self.delete("bezel_ring")
        s = self._size
        cx, cy = s // 2, s // 2
        outer_r = s // 2 - 2

        # Screen area (dark green-black) — stays below traces
        screen_r = outer_r - 18
        self.create_oval(cx - screen_r, cy - screen_r,
                         cx + screen_r, cy + screen_r,
                         fill="#060d06", outline="#1a1a1a", width=1,
                         tags="bezel")

        # Outer bezel ring (dark metallic) — raised above traces to clip
        for dr, color in [
            (0, "#2a2a2a"), (2, "#353535"), (4, "#404040"),
            (6, "#4a4a4a"), (8, "#454545"), (10, "#3a3a3a"),
            (12, "#303030"), (14, "#282828"), (16, "#222222"),
        ]:
            r = outer_r - dr
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                             outline=color, width=2, tags="bezel_ring")

        # Inner bezel highlight (subtle rim around screen)
        self.create_oval(cx - screen_r - 1, cy - screen_r - 1,
                         cx + screen_r + 1, cy + screen_r + 1,
                         outline="#333333", width=1, tags="bezel_ring")

        self._bezel_drawn = True

    def draw_graticule(self):
        """Draw the oscilloscope grid inside the round screen."""
        self.delete("graticule")
        cx, cy, r = self.get_draw_area()
        grid_color = "#0f1f0f"

        # Center cross
        self.create_line(cx - r, cy, cx + r, cy,
                         fill=grid_color, width=1, tags="graticule")
        self.create_line(cx, cy - r, cx, cy + r,
                         fill=grid_color, width=1, tags="graticule")

        # Grid divisions clipped to circle
        for i in range(1, 4):
            frac = i / 4.0
            offset = r * frac
            half = math.sqrt(max(0, r * r - offset * offset))
            # Vertical
            self.create_line(cx + offset, cy - half, cx + offset, cy + half,
                             fill=grid_color, width=1, dash=(2, 6),
                             tags="graticule")
            self.create_line(cx - offset, cy - half, cx - offset, cy + half,
                             fill=grid_color, width=1, dash=(2, 6),
                             tags="graticule")
            # Horizontal
            self.create_line(cx - half, cy + offset, cx + half, cy + offset,
                             fill=grid_color, width=1, dash=(2, 6),
                             tags="graticule")
            self.create_line(cx - half, cy - offset, cx + half, cy - offset,
                             fill=grid_color, width=1, dash=(2, 6),
                             tags="graticule")

    def draw_mask(self):
        """Ensure correct z-order: screen fill < graticule < trace < bezel ring."""
        self.tag_raise("graticule")
        self.tag_raise("trace")
        self.tag_raise("bezel_ring")
