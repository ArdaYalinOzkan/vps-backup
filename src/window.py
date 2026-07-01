import gi
import os
import stat
import threading
import time
from pathlib import Path

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib, Pango, Gdk

from .connection import SFTPConnection, load_config, save_config


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024**2):.1f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"


def icon_for_entry(entry):
    if entry['is_dir']:
        return 'folder'
    name = entry['name'].lower()
    if name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp')):
        return 'image-x-generic'
    elif name.endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
        return 'video-x-generic'
    elif name.endswith(('.mp3', '.ogg', '.flac', '.wav', '.opus')):
        return 'audio-x-generic'
    elif name.endswith(('.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar')):
        return 'package-x-generic'
    elif name.endswith(('.py', '.js', '.ts', '.c', '.h', '.rs', '.go', '.sh', '.json', '.xml', '.yaml', '.toml', '.html', '.css')):
        return 'text-x-script'
    elif name.endswith(('.txt', '.md', '.log', '.csv')):
        return 'text-x-generic'
    elif name.endswith(('.pdf',)):
        return 'x-office-document'
    elif name.endswith(('.conf', '.cfg', '.ini')):
        return 'application-x-executable'
    else:
        return 'text-x-generic'


class BackupWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("VPS Backup")
        self.set_default_size(800, 600)

        self.connection = SFTPConnection()
        self.selected_paths = []
        self.selected_display_names = {}
        self.download_dir = str(Path.home() / 'Downloads')
        self.current_remote_path = '/'
        self.downloads_in_progress = []
        self._size_cancel = False

        config = load_config()
        if config.get('selected_paths'):
            self.selected_paths = config['selected_paths']
        if config.get('selected_display_names'):
            self.selected_display_names = config['selected_display_names']
        if config.get('download_dir'):
            self.download_dir = config['download_dir']

        self._build_ui()

    def _build_ui(self):
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)

        self.header = Adw.HeaderBar()
        self.main_box.append(self.header)

        # Download indicator button (hidden until download starts)
        self.download_button = Gtk.MenuButton()
        self.download_button.set_icon_name('folder-download-symbolic')
        self.download_button.set_visible(False)
        self.download_popover = Gtk.Popover()
        self.download_popover.set_size_request(320, -1)
        self.download_pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.download_pop_box.set_margin_top(12)
        self.download_pop_box.set_margin_bottom(12)
        self.download_pop_box.set_margin_start(12)
        self.download_pop_box.set_margin_end(12)
        self.download_popover.set_child(self.download_pop_box)
        self.download_button.set_popover(self.download_popover)
        self.header.pack_end(self.download_button)

        # View stack with switcher in header
        self.view_stack = Adw.ViewStack()
        self.main_box.append(self.view_stack)

        self.switcher_title = Adw.ViewSwitcherTitle()
        self.switcher_title.set_stack(self.view_stack)
        self.header.set_title_widget(self.switcher_title)

        self.switcher_bar = Adw.ViewSwitcherBar()
        self.switcher_bar.set_stack(self.view_stack)
        self.switcher_title.connect('notify::title-visible', lambda *a: self.switcher_bar.set_reveal(self.switcher_title.get_title_visible()))
        self.main_box.append(self.switcher_bar)

        self._build_login_page()
        self._build_backup_page()
        self._build_browse_page()

        config = load_config()
        if not config.get('remember') or not config.get('host'):
            self.view_stack.set_visible_child_name('login')

    # ─── LOGIN ───────────────────────────────────────────────

    def _build_login_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_valign(Gtk.Align.CENTER)
        page.set_halign(Gtk.Align.CENTER)
        page.set_spacing(12)
        page.set_size_request(300, -1)
        page.set_margin_top(24)
        page.set_margin_bottom(24)

        icon = Gtk.Image.new_from_icon_name('network-server-symbolic')
        icon.set_pixel_size(48)
        icon.add_css_class('dim-label')
        page.append(icon)

        title = Gtk.Label(label="Connect to Server")
        title.add_css_class('title-3')
        page.append(title)

        group = Adw.PreferencesGroup()
        page.append(group)

        self.host_row = Adw.EntryRow(title="Host / IP")
        group.add(self.host_row)

        self.port_row = Adw.EntryRow(title="Port")
        self.port_row.set_text("22")
        group.add(self.port_row)

        self.user_row = Adw.EntryRow(title="Username")
        group.add(self.user_row)

        self.pass_row = Adw.PasswordEntryRow(title="Password")
        group.add(self.pass_row)

        self.remember_switch = Adw.SwitchRow(title="Remember Me")
        group.add(self.remember_switch)

        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.add_css_class('suggested-action')
        self.connect_button.add_css_class('pill')
        self.connect_button.set_halign(Gtk.Align.CENTER)
        self.connect_button.set_margin_top(4)
        self.connect_button.connect('clicked', self._on_connect)
        page.append(self.connect_button)

        self.login_status = Gtk.Label()
        self.login_status.add_css_class('error')
        self.login_status.set_visible(False)
        page.append(self.login_status)

        config = load_config()
        if config.get('remember'):
            self.host_row.set_text(config.get('host', ''))
            self.port_row.set_text(str(config.get('port', 22)))
            self.user_row.set_text(config.get('username', ''))
            self.pass_row.set_text(config.get('password', ''))
            self.remember_switch.set_active(True)

        self.view_stack.add_titled_with_icon(page, 'login', 'Login', 'network-server-symbolic')

    # ─── BACKUP ──────────────────────────────────────────────

    def _build_backup_page(self):
        self.backup_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Empty state
        self.backup_empty = Adw.StatusPage()
        self.backup_empty.set_title("No Paths Selected")
        self.backup_empty.set_description("Browse your server and select files or folders to back up.")
        self.backup_empty.set_icon_name("checkbox-checked-symbolic")
        browse_btn = Gtk.Button(label="Browse Server")
        browse_btn.add_css_class('suggested-action')
        browse_btn.add_css_class('pill')
        browse_btn.set_halign(Gtk.Align.CENTER)
        browse_btn.connect('clicked', lambda *a: self.view_stack.set_visible_child_name('browse'))
        self.backup_empty.set_child(browse_btn)
        self.backup_box.append(self.backup_empty)

        # Content state (hidden initially)
        self.backup_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.backup_content.set_visible(False)
        self.backup_box.append(self.backup_content)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_kinetic_scrolling(True)

        self.backup_list = Gtk.ListBox()
        self.backup_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.backup_list.add_css_class('boxed-list')
        self.backup_list.set_margin_top(16)
        self.backup_list.set_margin_bottom(8)
        self.backup_list.set_margin_start(16)
        self.backup_list.set_margin_end(16)
        scrolled.set_child(self.backup_list)
        self.backup_content.append(scrolled)

        # Bottom bar
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        bottom.set_margin_start(16)
        bottom.set_margin_end(16)
        bottom.set_margin_bottom(16)

        dir_row = Adw.ActionRow(title="Download Location")
        dir_row.set_subtitle(self.download_dir)
        dir_row.add_css_class('card')
        dir_btn = Gtk.Button(icon_name='folder-open-symbolic')
        dir_btn.set_valign(Gtk.Align.CENTER)
        dir_btn.connect('clicked', self._choose_download_dir)
        dir_row.add_suffix(dir_btn)
        self.dir_row = dir_row
        bottom.append(dir_row)

        self.size_label = Gtk.Label(label="")
        self.size_label.add_css_class('dim-label')
        self.size_label.set_halign(Gtk.Align.CENTER)
        self.size_label.set_margin_top(4)
        bottom.append(self.size_label)

        self.backup_button = Gtk.Button(label="Backup")
        self.backup_button.add_css_class('suggested-action')
        self.backup_button.add_css_class('pill')
        self.backup_button.set_halign(Gtk.Align.CENTER)
        self.backup_button.set_margin_top(4)
        self.backup_button.connect('clicked', self._on_backup)
        bottom.append(self.backup_button)

        self.backup_content.append(bottom)

        self.view_stack.add_titled_with_icon(self.backup_box, 'backup', 'Backup', 'drive-harddisk-symbolic')

    # ─── BROWSE ──────────────────────────────────────────────

    def _build_browse_page(self):
        browse_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Navigation bar
        nav_bar = Gtk.Box(spacing=6)
        nav_bar.set_margin_top(8)
        nav_bar.set_margin_bottom(8)
        nav_bar.set_margin_start(12)
        nav_bar.set_margin_end(12)

        back_btn = Gtk.Button(icon_name='go-previous-symbolic')
        back_btn.add_css_class('flat')
        back_btn.set_tooltip_text("Go back")
        back_btn.connect('clicked', self._on_browse_back)
        nav_bar.append(back_btn)

        home_btn = Gtk.Button(icon_name='go-home-symbolic')
        home_btn.add_css_class('flat')
        home_btn.set_tooltip_text("Home directory")
        home_btn.connect('clicked', self._on_browse_home)
        nav_bar.append(home_btn)

        self.path_label = Gtk.Label(label="/")
        self.path_label.set_hexpand(True)
        self.path_label.set_halign(Gtk.Align.START)
        self.path_label.set_ellipsize(Pango.EllipsizeMode.START)
        self.path_label.add_css_class('heading')
        self.path_label.set_margin_start(8)
        nav_bar.append(self.path_label)

        select_cur_btn = Gtk.Button(label="Select This Folder")
        select_cur_btn.add_css_class('flat')
        select_cur_btn.connect('clicked', self._on_select_current_folder)
        nav_bar.append(select_cur_btn)

        browse_box.append(nav_bar)
        browse_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Stack for file list vs spinner
        self.browse_stack = Gtk.Stack()
        self.browse_stack.set_vexpand(True)
        self.browse_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # File list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_kinetic_scrolling(True)

        self.file_list = Gtk.ListBox()
        self.file_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.file_list.set_margin_top(4)
        self.file_list.set_margin_bottom(4)
        self.file_list.add_css_class('navigation-sidebar')
        scrolled.set_child(self.file_list)
        self.browse_stack.add_named(scrolled, 'list')

        # Loading spinner
        spinner_box = Gtk.Box()
        spinner_box.set_halign(Gtk.Align.CENTER)
        spinner_box.set_valign(Gtk.Align.CENTER)
        self.browse_spinner = Gtk.Spinner()
        self.browse_spinner.set_size_request(32, 32)
        spinner_box.append(self.browse_spinner)
        self.browse_stack.add_named(spinner_box, 'loading')

        browse_box.append(self.browse_stack)

        self.view_stack.add_titled_with_icon(browse_box, 'browse', 'Browse', 'folder-symbolic')

    # ─── CONNECTION ──────────────────────────────────────────

    def _on_connect(self, button):
        host = self.host_row.get_text().strip()
        port = int(self.port_row.get_text().strip() or '22')
        username = self.user_row.get_text().strip()
        password = self.pass_row.get_text()

        if not host or not username:
            self.login_status.set_label("Please fill in all fields")
            self.login_status.set_visible(True)
            return

        self.connect_button.set_sensitive(False)
        self.connect_button.set_label("Connecting...")

        if self.remember_switch.get_active():
            save_config({
                'remember': True,
                'host': host,
                'port': port,
                'username': username,
                'password': password,
                'selected_paths': self.selected_paths,
                'selected_display_names': self.selected_display_names,
                'download_dir': self.download_dir,
            })

        threading.Thread(target=self._do_connect, args=(host, port, username, password), daemon=True).start()

    def _do_connect(self, host, port, username, password):
        try:
            self.connection.connect(host, username, password, port)
            GLib.idle_add(self._on_connected)
        except Exception as e:
            GLib.idle_add(self._on_connect_error, str(e))

    def _on_connected(self):
        self.connect_button.set_sensitive(True)
        self.connect_button.set_label("Connect")
        self.login_status.set_visible(False)
        self.view_stack.set_visible_child_name('backup')
        self._refresh_backup_list(skip_size=True)
        try:
            home = self.connection.sftp.normalize('.')
            self.current_remote_path = home
        except Exception:
            self.current_remote_path = '/'
        self._browse_to(self.current_remote_path)

    def _on_connect_error(self, error):
        self.connect_button.set_sensitive(True)
        self.connect_button.set_label("Connect")
        self.login_status.set_label(f"Failed: {error}")
        self.login_status.set_visible(True)

    # ─── BROWSE LOGIC ────────────────────────────────────────

    def _browse_to(self, path):
        if not self.connection.connected:
            return
        self._size_cancel = True
        self.current_remote_path = path
        self.path_label.set_label(path)
        self.browse_stack.set_visible_child_name('loading')
        self.browse_spinner.start()
        threading.Thread(target=self._load_directory, args=(path,), daemon=True).start()

    def _load_directory(self, path):
        try:
            entries = self.connection.list_dir(path)
            GLib.idle_add(self._populate_file_list, entries)
        except Exception as e:
            GLib.idle_add(self._browse_error, str(e))

    def _browse_error(self, msg):
        self.browse_spinner.stop()
        self._clear_list(self.file_list)
        row = Adw.ActionRow(title="Error", subtitle=msg)
        row.add_prefix(Gtk.Image.new_from_icon_name('dialog-error-symbolic'))
        self.file_list.append(row)
        self.browse_stack.set_visible_child_name('list')

    def _populate_file_list(self, entries):
        self.browse_spinner.stop()
        self._clear_list(self.file_list)

        if not entries:
            row = Adw.ActionRow(title="Empty folder")
            row.add_prefix(Gtk.Image.new_from_icon_name('folder-symbolic'))
            self.file_list.append(row)
            self.browse_stack.set_visible_child_name('list')
            return

        self._cached_entries = entries
        for entry in entries:
            self._append_file_row(entry)

        self.browse_stack.set_visible_child_name('list')

    def _append_file_row(self, entry):
        row = Adw.ActionRow()
        row.set_title(entry['name'])
        if not entry['is_dir']:
            row.set_subtitle(format_size(entry['size']))

        icon = Gtk.Image.new_from_icon_name(icon_for_entry(entry))
        icon.set_pixel_size(32)
        row.add_prefix(icon)

        is_selected = entry['path'] in self.selected_paths

        # Selected indicator
        if is_selected:
            check = Gtk.Image.new_from_icon_name('object-select-symbolic')
            check.add_css_class('success')
            row.add_suffix(check)

        # Select/deselect button
        if is_selected:
            sel_btn = Gtk.Button(icon_name='list-remove-symbolic')
            sel_btn.set_tooltip_text("Remove from backup")
        else:
            sel_btn = Gtk.Button(icon_name='list-add-symbolic')
            sel_btn.set_tooltip_text("Add to backup")
        sel_btn.set_valign(Gtk.Align.CENTER)
        sel_btn.add_css_class('flat')
        sel_btn.connect('clicked', self._on_select_item, entry['path'])
        row.add_suffix(sel_btn)

        # Navigate arrow for directories
        if entry['is_dir']:
            arrow = Gtk.Image.new_from_icon_name('go-next-symbolic')
            arrow.add_css_class('dim-label')
            row.add_suffix(arrow)
            row.set_activatable(True)
            row.connect('activated', self._on_row_activated, entry['path'])

        self.file_list.append(row)

    def _on_row_activated(self, row, path):
        self._browse_to(path)

    def _on_browse_back(self, button):
        parent = os.path.dirname(self.current_remote_path)
        if parent and parent != self.current_remote_path:
            self._browse_to(parent)

    def _on_browse_home(self, button):
        if self.connection.connected:
            try:
                home = self.connection.sftp.normalize('.')
                self._browse_to(home)
            except Exception:
                self._browse_to('/')

    def _on_select_current_folder(self, button):
        self._toggle_selection(self.current_remote_path)

    def _on_select_item(self, button, path):
        self._toggle_selection(path)

    def _toggle_selection(self, path):
        if path in self.selected_paths:
            self.selected_paths.remove(path)
            self.selected_display_names.pop(path, None)
        else:
            self.selected_paths.append(path)
        self._save_state()
        self._refresh_file_list_local()
        self._refresh_backup_list()

    def _refresh_file_list_local(self):
        if not hasattr(self, '_cached_entries'):
            return
        self._clear_list(self.file_list)
        for entry in self._cached_entries:
            self._append_file_row(entry)

    # ─── BACKUP LOGIC ────────────────────────────────────────

    def _refresh_backup_list(self, skip_size=False):
        self._clear_list(self.backup_list)

        if not self.selected_paths:
            self.backup_empty.set_visible(True)
            self.backup_content.set_visible(False)
            self.size_label.set_label("")
            return

        self.backup_empty.set_visible(False)
        self.backup_content.set_visible(True)

        self.check_rows = {}
        for path in self.selected_paths:
            display_name = self.selected_display_names.get(path, os.path.basename(path))
            row = Adw.ActionRow()
            row.set_title(display_name)
            row.set_subtitle(path)

            check = Gtk.CheckButton()
            check.set_active(True)
            row.add_prefix(check)
            row.set_activatable_widget(check)

            # Rename button
            rename_btn = Gtk.Button(icon_name='document-edit-symbolic')
            rename_btn.set_valign(Gtk.Align.CENTER)
            rename_btn.add_css_class('flat')
            rename_btn.set_tooltip_text("Rename label")
            rename_btn.connect('clicked', self._on_rename_item, path)
            row.add_suffix(rename_btn)

            # Remove button
            remove_btn = Gtk.Button(icon_name='edit-delete-symbolic')
            remove_btn.set_valign(Gtk.Align.CENTER)
            remove_btn.add_css_class('flat')
            remove_btn.connect('clicked', self._on_remove_item, path)
            row.add_suffix(remove_btn)

            self.backup_list.append(row)
            self.check_rows[path] = check

        if not skip_size and self.connection.connected:
            threading.Thread(target=self._calculate_total_size, daemon=True).start()

    def _calculate_total_size(self):
        self._size_cancel = False
        total = 0
        for path in self.selected_paths:
            if self._size_cancel:
                return
            try:
                with self.connection.lock:
                    attr = self.connection.sftp.stat(path)
                total += attr.st_size
            except Exception:
                pass
        GLib.idle_add(self.size_label.set_label, f"Total download: ~{format_size(total)}")

    def _on_rename_item(self, button, path):
        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading("Rename Label")
        dialog.set_body("This only changes the display name, not the actual file.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)

        entry = Gtk.Entry()
        entry.set_text(self.selected_display_names.get(path, os.path.basename(path)))
        entry.set_margin_start(24)
        entry.set_margin_end(24)
        dialog.set_extra_child(entry)
        dialog.connect('response', self._on_rename_response, path, entry)
        dialog.present()

    def _on_rename_response(self, dialog, response, path, entry):
        if response == 'rename':
            name = entry.get_text().strip()
            if name:
                self.selected_display_names[path] = name
                self._save_state()
                self._refresh_backup_list()

    def _on_remove_item(self, button, path):
        if path in self.selected_paths:
            self.selected_paths.remove(path)
            self.selected_display_names.pop(path, None)
            self._save_state()
            self._refresh_backup_list()

    def _choose_download_dir(self, button):
        dialog = Gtk.FileDialog()
        dialog.select_folder(self, None, self._on_dir_chosen)

    def _on_dir_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.download_dir = folder.get_path()
                self.dir_row.set_subtitle(self.download_dir)
                self._save_state()
        except Exception:
            pass

    def _on_backup(self, button):
        if not self.connection.connected:
            return

        paths_to_backup = [p for p, c in self.check_rows.items() if c.get_active()]
        if not paths_to_backup:
            return

        self.download_button.set_visible(True)
        self.backup_button.set_sensitive(False)
        self.backup_button.set_label("Downloading...")

        threading.Thread(target=self._do_backup, args=(paths_to_backup,), daemon=True).start()

    def _do_backup(self, paths):
        info = {'total': 0, 'downloaded': 0, 'done': False, 'local_path': self.download_dir, 'errors': []}
        self.downloads_in_progress.append(info)
        GLib.idle_add(self._update_download_popup)

        for path in paths:
            local_path = os.path.join(self.download_dir, os.path.basename(path))
            try:
                with self.connection.lock:
                    attr = self.connection.sftp.stat(path)
                if stat.S_ISDIR(attr.st_mode):
                    self._download_dir_tracked(path, local_path, info)
                else:
                    info['total'] += attr.st_size
                    GLib.idle_add(self._update_download_popup)
                    self._download_file_tracked(path, local_path, info)
            except Exception as e:
                info['errors'].append(f"{os.path.basename(path)}: {e}")

        info['done'] = True
        GLib.idle_add(self._update_download_popup)
        GLib.idle_add(self._on_backup_done)

    def _download_file_tracked(self, remote_path, local_path, info):
        prev = [0]
        last_ui = [0.0]
        def callback(transferred, total_file):
            delta = transferred - prev[0]
            prev[0] = transferred
            info['downloaded'] += delta
            now = time.monotonic()
            if now - last_ui[0] > 0.15:
                last_ui[0] = now
                GLib.idle_add(self._update_download_popup)
        with self.connection.lock:
            self.connection.sftp.get(remote_path, local_path, callback=callback)

    def _download_dir_tracked(self, remote_path, local_path, info):
        os.makedirs(local_path, exist_ok=True)
        with self.connection.lock:
            entries = list(self.connection.sftp.listdir_attr(remote_path))
        for attr in entries:
            rchild = os.path.join(remote_path, attr.filename)
            lchild = os.path.join(local_path, attr.filename)
            try:
                if stat.S_ISDIR(attr.st_mode):
                    self._download_dir_tracked(rchild, lchild, info)
                else:
                    info['total'] += attr.st_size
                    GLib.idle_add(self._update_download_popup)
                    self._download_file_tracked(rchild, lchild, info)
            except Exception as e:
                info['errors'].append(f"{attr.filename}: {e}")

    def _on_backup_done(self):
        self.backup_button.set_sensitive(True)
        self.backup_button.set_label("Backup")

    def _update_download_popup(self):
        self._clear_box(self.download_pop_box)

        for info in self.downloads_in_progress:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            if info['done']:
                done_row = Gtk.Box(spacing=8)
                icon = Gtk.Image.new_from_icon_name('emblem-ok-symbolic')
                icon.add_css_class('success')
                done_row.append(icon)
                label = Gtk.Label(label="Download complete")
                label.add_css_class('heading')
                done_row.append(label)
                box.append(done_row)

                for err in info.get('errors', []):
                    err_label = Gtk.Label(label=f"⚠ {err}")
                    err_label.add_css_class('error')
                    err_label.set_wrap(True)
                    err_label.set_halign(Gtk.Align.START)
                    box.append(err_label)

                open_btn = Gtk.Button(label="Show in Files")
                open_btn.add_css_class('flat')
                open_btn.connect('clicked', self._open_in_files, info['local_path'])
                box.append(open_btn)
            else:
                label = Gtk.Label(label="Downloading...")
                label.set_halign(Gtk.Align.START)
                box.append(label)

                progress = Gtk.ProgressBar()
                frac = info['downloaded'] / info['total'] if info['total'] > 0 else 0
                progress.set_fraction(min(frac, 1.0))
                progress.set_text(f"{format_size(info['downloaded'])} / {format_size(info['total'])}")
                progress.set_show_text(True)
                box.append(progress)

                remaining = max(0, info['total'] - info['downloaded'])
                rem_label = Gtk.Label(label=f"{format_size(remaining)} remaining")
                rem_label.set_halign(Gtk.Align.START)
                rem_label.add_css_class('dim-label')
                box.append(rem_label)

            self.download_pop_box.append(box)

    def _open_in_files(self, button, path):
        launcher = Gtk.FileLauncher()
        launcher.set_file(Gio.File.new_for_path(path))
        launcher.open_containing_folder(self, None, None)

    # ─── HELPERS ─────────────────────────────────────────────

    def _save_state(self):
        config = load_config()
        config['selected_paths'] = self.selected_paths
        config['selected_display_names'] = self.selected_display_names
        config['download_dir'] = self.download_dir
        save_config(config)

    def _clear_list(self, listbox):
        while True:
            child = listbox.get_first_child()
            if child is None:
                break
            listbox.remove(child)

    def _clear_box(self, box):
        while True:
            child = box.get_first_child()
            if child is None:
                break
            box.remove(child)
