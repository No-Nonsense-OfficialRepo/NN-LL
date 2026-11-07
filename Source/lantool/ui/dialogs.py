"""Dispatch backend prompts through the active (Qt) UI.

The parent must provide ui_message / choose_file; without one the prompt is
logged and dropped rather than opening a Tk window (Tk is no longer shipped).
"""
import logging

log = logging.getLogger(__name__)


class Messages:
    def _show(self, kind, title, message, **kwargs):
        parent = kwargs.get("parent")
        detail = {k: kwargs.pop(k) for k in ("stage", "code", "hint") if k in kwargs}
        if hasattr(parent, "ui_message"):
            if detail:
                return parent.ui_message(kind, title, message, **detail)
            return parent.ui_message(kind, title, message)
        log.warning("No UI parent for %s %r: %s", kind, title, message)
        return None

    def showinfo(self, title, message, **kwargs):
        return self._show("showinfo", title, message, **kwargs)

    def showerror(self, title, message, **kwargs):
        return self._show("showerror", title, message, **kwargs)

    def showwarning(self, title, message, **kwargs):
        return self._show("showwarning", title, message, **kwargs)


class Files:
    def askopenfilename(self, **kwargs):
        parent = kwargs.get("parent")
        if hasattr(parent, "choose_file"):
            return parent.choose_file(kwargs.get("title", "Choose file"))
        log.warning("No UI parent to choose a file (%r)", kwargs.get("title", ""))
        return ""


messagebox = Messages()
filedialog = Files()
