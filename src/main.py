import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio

from .window import BackupWindow


class BackupApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='io.github.vpsbackup.VpsBackup',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = BackupWindow(application=self)
        win.present()


def main():
    app = BackupApplication()
    return app.run(sys.argv)
