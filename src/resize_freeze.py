"""
Holds a window's content still while the window is being resized.

FIX (2026-11-12): RESIZING WAS NOT LIVE ON A SLOW MACHINE (Mark, ThinkPad X1
Carbon 2nd gen, Windows 11): drag the window's edge and nothing happened, then
it jumped to the new size when the drag stopped. Moving the window was fine,
and Brown's window resized live on the same machine, so it was not Windows'
"show window contents while dragging" setting.

WHY. The main window's content stretches with it (the notebook is packed
fill="both", expand=True, and the Operate page's columns are weighted), and
CustomTkinter draws every widget itself, on a canvas. So each step of a drag
resized, and redrew, every panel, meter, dial and button. On a fast machine
that keeps up; on a 2014 dual-core it did not, the steps queued behind each
other, and the window could only show the last one.

WHAT THIS DOES. The first size change takes the content out of the packer and
places it at exactly the size and position it already had: the same size, so
none of its widgets is told it changed and nothing redraws. The window's frame
follows the pointer at once, over the window's background where it grew, or
cutting the content off where it shrank. When the size has stopped changing
for `settle_ms`, the content goes back into the packer as it was, and lays out
once, at the final size.

Before `arm()` the window resizes as it always did, so the first layout at
start-up (and a restored geometry) is not held back.
"""


class ResizeFreeze:
    """
    One per window. Call `on_configure(event)` from the window's <Configure>
    handler, and `arm()` once the window has its first layout.

    window        the toplevel (CTk / sCTk / Toplevel)
    content       its one stretching child, packed in it
    pack_options  the options `content` is packed with, to pack it back
    settle_ms     how long the size has to stay put to count as finished
    """

    def __init__(self, window, content, pack_options, settle_ms=150):
        self._window = window
        self._content = content
        self._pack = dict(pack_options)
        self.settle_ms = settle_ms
        self._armed = False
        self._size = None
        self.frozen = False
        self._timer = None
        # After a thaw, the re-pack may change the window's size itself (a
        # window that follows its content's requested size). That change is
        # ours, not the operator's, and freezing for it would thaw into the
        # same change again: so size changes are only noted for a moment.
        self._quiet = False
        self._propagate = None

    def arm(self):
        """From now on, a resize holds the content still until it settles."""
        if not self._window.winfo_exists():
            return
        self._size = (self._window.winfo_width(), self._window.winfo_height())
        self._armed = True

    def on_configure(self, event):
        if event.widget is not self._window or not self._armed:
            return
        size = (event.width, event.height)
        if size == self._size:
            return              # moved, not resized
        self._size = size
        if self._quiet:
            return
        if not self.frozen:
            self._freeze()
        if self._timer is not None:
            try:
                self._window.after_cancel(self._timer)
            except Exception:
                pass
        self._timer = self._window.after(self.settle_ms, self._thaw)

    def _freeze(self):
        content = self._content
        x, y = content.winfo_x(), content.winfo_y()
        w, h = content.winfo_width(), content.winfo_height()
        # Without its only packed child the window would ask for a size of its
        # own; it keeps the one it has instead.
        self._propagate = self._window.pack_propagate()
        self._window.pack_propagate(False)
        content.pack_forget()
        # Tk's placer directly: CustomTkinter's place() refuses a width and a
        # height (it wants them given to the constructor, and scales them).
        # These are the widget's real pixel sizes, so no scaling is wanted.
        content.tk.call("place", "configure", content._w,
                        "-x", x, "-y", y, "-width", w, "-height", h)
        self.frozen = True

    def _thaw(self):
        self._timer = None
        if not self.frozen or not self._window.winfo_exists():
            return
        content = self._content
        content.tk.call("place", "forget", content._w)
        content.pack(**self._pack)
        if self._propagate is not None:
            self._window.pack_propagate(self._propagate)
        self.frozen = False
        self._quiet = True
        self._window.after(self.settle_ms, self._end_quiet)

    def _end_quiet(self):
        self._quiet = False
        if self._window.winfo_exists():
            self._size = (self._window.winfo_width(), self._window.winfo_height())
