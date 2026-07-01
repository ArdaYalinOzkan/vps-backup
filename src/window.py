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


_SERVICE_PATTERNS = [
    {'name': 'Immich', 'desc': 'Photo & video library', 'icon': 'image-x-generic-symbolic',
     'paths': ['/root/immich/library', '/root/immich/upload', '/home/immich',
               '/opt/immich/library', '/srv/immich', '/var/lib/immich', '/data/immich']},
    {'name': 'Jellyfin', 'desc': 'Media server data', 'icon': 'video-x-generic-symbolic',
     'paths': ['/var/lib/jellyfin', '/opt/jellyfin', '/config/jellyfin',
               '/data/jellyfin', '/srv/jellyfin', '/jellyfin']},
    {'name': 'Nextcloud', 'desc': 'File sync & share data', 'icon': 'folder-symbolic',
     'paths': ['/var/www/nextcloud/data', '/var/lib/nextcloud/data',
               '/opt/nextcloud', '/srv/nextcloud', '/data/nextcloud']},
    {'name': 'Vaultwarden', 'desc': 'Password vault', 'icon': 'dialog-password-symbolic',
     'paths': ['/var/lib/vaultwarden', '/opt/vaultwarden/data',
               '/srv/vaultwarden', '/data/vaultwarden', '/vaultwarden']},
    {'name': 'Gitea / Forgejo', 'desc': 'Git repositories', 'icon': 'folder-symbolic',
     'paths': ['/var/lib/gitea', '/opt/gitea', '/home/git',
               '/srv/gitea', '/var/lib/forgejo', '/opt/forgejo']},
    {'name': 'Home Assistant', 'desc': 'Smart home config', 'icon': 'folder-symbolic',
     'paths': ['/config', '/homeassistant', '/home/homeassistant/.homeassistant',
               '/opt/homeassistant']},
    {'name': 'Syncthing', 'desc': 'Sync configuration', 'icon': 'folder-symbolic',
     'paths': ['/var/lib/syncthing', '/root/.config/syncthing',
               '/root/.local/share/syncthing']},
    {'name': 'Plex', 'desc': 'Media server', 'icon': 'video-x-generic-symbolic',
     'paths': ['/var/lib/plexmediaserver', '/opt/plex', '/srv/plex']},
    {'name': 'Paperless-ngx', 'desc': 'Document archive', 'icon': 'folder-symbolic',
     'paths': ['/opt/paperless/data', '/srv/paperless', '/var/lib/paperless']},
    {'name': 'PostgreSQL', 'desc': 'Database files', 'icon': 'folder-symbolic',
     'paths': ['/var/lib/postgresql']},
    {'name': 'MySQL / MariaDB', 'desc': 'Database files', 'icon': 'folder-symbolic',
     'paths': ['/var/lib/mysql', '/var/lib/mariadb']},
    {'name': 'Docker Volumes', 'desc': 'Container data volumes', 'icon': 'folder-symbolic',
     'paths': ['/var/lib/docker/volumes']},
]

_SERVICE_KEYWORDS = {
    'immich': ('Immich', 'Photo & video library', 'image-x-generic-symbolic'),
    'jellyfin': ('Jellyfin', 'Media server', 'video-x-generic-symbolic'),
    'plex': ('Plex', 'Media server', 'video-x-generic-symbolic'),
    'nextcloud': ('Nextcloud', 'File sync & share', 'folder-symbolic'),
    'vaultwarden': ('Vaultwarden', 'Password vault', 'dialog-password-symbolic'),
    'bitwarden': ('Vaultwarden', 'Password vault', 'dialog-password-symbolic'),
    'gitea': ('Gitea', 'Git repositories', 'folder-symbolic'),
    'forgejo': ('Forgejo', 'Git repositories', 'folder-symbolic'),
    'homeassistant': ('Home Assistant', 'Smart home', 'folder-symbolic'),
    'syncthing': ('Syncthing', 'File sync', 'folder-symbolic'),
    'paperless': ('Paperless-ngx', 'Document archive', 'folder-symbolic'),
    'pihole': ('Pi-hole', 'DNS ad blocker', 'folder-symbolic'),
    'adguard': ('AdGuard Home', 'DNS ad blocker', 'folder-symbolic'),
    'miniflux': ('Miniflux', 'RSS reader', 'folder-symbolic'),
    'freshrss': ('FreshRSS', 'RSS reader', 'folder-symbolic'),
    'mealie': ('Mealie', 'Recipe manager', 'folder-symbolic'),
    'memos': ('Memos', 'Note taking', 'folder-symbolic'),
    'uptime': ('Uptime Kuma', 'Status monitor', 'folder-symbolic'),
}


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
    elif name.endswith(('.py', '.js', '.ts', '.c', '.h', '.rs', '.go', '.sh',
                        '.json', '.xml', '.yaml', '.toml', '.html', '.css')):
        return 'text-x-script'
    elif name.endswith(('.txt', '.md', '.log', '.csv')):
        return 'text-x-generic'
    elif name.endswith(('.pdf',)):
        return 'x-office-document'
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
        self.download_dir = str(Path.home() / 'Documents' / 'VPS Backup')
        self.current_remote_path = '/'
        self.downloads_in_progress = []
        self._size_cancel = False
        self._recommendations = None
        self._rec_scanning = False

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

        self.view_stack = Adw.ViewStack()
        self.main_box.append(self.view_stack)

        self.switcher_title = Adw.ViewSwitcherTitle()
        self.switcher_title.set_stack(self.view_stack)
        self.header.set_title_widget(self.switcher_title)

        self.switcher_bar = Adw.ViewSwitcherBar()
        self.switcher_bar.set_stack(self.view_stack)
        self.switcher_title.connect(
            'notify::title-visible',
            lambda *a: self.switcher_bar.set_reveal(self.switcher_title.get_title_visible())
        )
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

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        bottom.set_margin_start(16)
        bottom.set_margin_end(16)
        bottom.set_margin_bottom(16)

        dir_row = Adw.ActionRow(title="Backup Location")
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

        self.view_stack.add_titled_with_icon(
            self.backup_box, 'backup', 'Backup', 'drive-harddisk-symbolic'
        )

    # ─── BROWSE ──────────────────────────────────────────────

    def _build_browse_page(self):
        browse_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

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

        # ── Recommendations dropdown ──
        self.rec_popover = Gtk.Popover()
        self.rec_popover.set_size_request(380, -1)
        self.rec_pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.rec_popover.set_child(self.rec_pop_box)

        rec_btn = Gtk.MenuButton()
        rec_btn.set_label("Recommended")
        rec_btn.add_css_class('flat')
        rec_btn.set_popover(self.rec_popover)
        rec_btn.connect('notify::active', self._on_rec_btn_toggled)
        nav_bar.append(rec_btn)

        select_cur_btn = Gtk.Button(label="Select This Folder")
        select_cur_btn.add_css_class('flat')
        select_cur_btn.connect('clicked', self._on_select_current_folder)
        nav_bar.append(select_cur_btn)

        browse_box.append(nav_bar)
        browse_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self.browse_stack = Gtk.Stack()
        self.browse_stack.set_vexpand(True)
        self.browse_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

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

        threading.Thread(
            target=self._do_connect, args=(host, port, username, password), daemon=True
        ).start()

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
        self._recommendations = None
        self._rec_scanning = False
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

    # ─── RECOMMENDATIONS ─────────────────────────────────────

    def _on_rec_btn_toggled(self, btn, _param):
        if not btn.get_active():
            return

        if not self.connection.connected:
            self._clear_box(self.rec_pop_box)
            lbl = Gtk.Label(label="Not connected to a server")
            lbl.add_css_class('dim-label')
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
            lbl.set_margin_start(16)
            lbl.set_margin_end(16)
            self.rec_pop_box.append(lbl)
            return

        if self._recommendations is not None or self._rec_scanning:
            return  # already have results or in progress

        # Show spinner and start scan
        self._clear_box(self.rec_pop_box)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_margin_top(16)
        row.set_margin_bottom(16)
        row.set_margin_start(16)
        row.set_margin_end(16)
        sp = Gtk.Spinner()
        sp.start()
        row.append(sp)
        row.append(Gtk.Label(label="Analyzing server structure..."))
        self.rec_pop_box.append(row)

        self._rec_scanning = True
        threading.Thread(target=self._scan_recommendations, daemon=True).start()

    def _scan_recommendations(self):
        found = []
        seen = set()

        for pattern in _SERVICE_PATTERNS:
            for path in pattern['paths']:
                if path in seen:
                    continue
                try:
                    with self.connection.lock:
                        self.connection.sftp.stat(path)
                    found.append({
                        'name': pattern['name'],
                        'desc': pattern['desc'],
                        'icon': pattern['icon'],
                        'path': path,
                    })
                    seen.add(path)
                    break
                except Exception:
                    pass

        scan_roots = ['/', '/root', '/opt', '/srv', '/data', '/home', '/var/lib']
        if self.current_remote_path not in scan_roots:
            scan_roots.append(self.current_remote_path)

        for root in scan_roots:
            try:
                with self.connection.lock:
                    entries = self.connection.sftp.listdir_attr(root)
                for attr in entries:
                    if not stat.S_ISDIR(attr.st_mode):
                        continue
                    path = os.path.join(root, attr.filename)
                    if path in seen:
                        continue
                    name_lower = attr.filename.lower()
                    for kw, (svc, desc, icon) in _SERVICE_KEYWORDS.items():
                        if kw in name_lower:
                            found.append({'name': svc, 'desc': desc, 'icon': icon, 'path': path})
                            seen.add(path)
                            break
            except Exception:
                pass

        self._rec_scanning = False
        self._recommendations = found
        GLib.idle_add(self._populate_recommendations_ui)

    def _populate_recommendations_ui(self):
        self._clear_box(self.rec_pop_box)

        if not self._recommendations:
            lbl = Gtk.Label(label="No known services found on this server")
            lbl.add_css_class('dim-label')
            lbl.set_wrap(True)
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
            lbl.set_margin_start(16)
            lbl.set_margin_end(16)
            self.rec_pop_box.append(lbl)
            return

        hdr = Gtk.Label(label="Detected services")
        hdr.add_css_class('heading')
        hdr.set_halign(Gtk.Align.START)
        hdr.set_margin_top(12)
        hdr.set_margin_start(12)
        hdr.set_margin_bottom(4)
        self.rec_pop_box.append(hdr)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class('boxed-list')
        listbox.set_margin_top(4)
        listbox.set_margin_bottom(12)
        listbox.set_margin_start(8)
        listbox.set_margin_end(8)

        for rec in self._recommendations:
            row = Adw.ActionRow()
            row.set_title(rec['name'])
            row.set_subtitle(rec['path'])

            ico = Gtk.Image.new_from_icon_name(rec['icon'])
            ico.set_pixel_size(24)
            row.add_prefix(ico)

            view_btn = Gtk.Button(label="View")
            view_btn.add_css_class('flat')
            view_btn.set_valign(Gtk.Align.CENTER)
            view_btn.connect('clicked', self._on_rec_view, rec['path'])
            row.add_suffix(view_btn)

            add_btn = Gtk.Button(label="Add")
            add_btn.add_css_class('suggested-action')
            add_btn.add_css_class('flat')
            add_btn.set_valign(Gtk.Align.CENTER)
            add_btn.connect('clicked', self._on_rec_add, rec['path'])
            row.add_suffix(add_btn)

            listbox.append(row)

        self.rec_pop_box.append(listbox)

    def _on_rec_view(self, _btn, path):
        self.rec_popover.popdown()
        self.view_stack.set_visible_child_name('browse')
        self._browse_to(path)

    def _on_rec_add(self, _btn, path):
        if path not in self.selected_paths:
            self.selected_paths.append(path)
            self._save_state()
            self._refresh_file_list_local()
            self._refresh_backup_list()

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

        if is_selected:
            check = Gtk.Image.new_from_icon_name('object-select-symbolic')
            check.add_css_class('success')
            row.add_suffix(check)

        sel_btn = Gtk.Button(
            icon_name='list-remove-symbolic' if is_selected else 'list-add-symbolic'
        )
        sel_btn.set_tooltip_text("Remove from backup" if is_selected else "Add to backup")
        sel_btn.set_valign(Gtk.Align.CENTER)
        sel_btn.add_css_class('flat')
        sel_btn.connect('clicked', self._on_select_item, entry['path'])
        row.add_suffix(sel_btn)

        if entry['is_dir']:
            arrow = Gtk.Image.new_from_icon_name('go-next-symbolic')
            arrow.add_css_class('dim-label')
            row.add_suffix(arrow)
            row.set_activatable(True)
            row.connect('activated', self._on_row_activated, entry['path'])

        self.file_list.append(row)

    def _on_row_activated(self, _row, path):
        self._browse_to(path)

    def _on_browse_back(self, _btn):
        parent = os.path.dirname(self.current_remote_path)
        if parent and parent != self.current_remote_path:
            self._browse_to(parent)

    def _on_browse_home(self, _btn):
        if self.connection.connected:
            try:
                home = self.connection.sftp.normalize('.')
                self._browse_to(home)
            except Exception:
                self._browse_to('/')

    def _on_select_current_folder(self, _btn):
        self._toggle_selection(self.current_remote_path)

    def _on_select_item(self, _btn, path):
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

            rename_btn = Gtk.Button(icon_name='document-edit-symbolic')
            rename_btn.set_valign(Gtk.Align.CENTER)
            rename_btn.add_css_class('flat')
            rename_btn.set_tooltip_text("Rename label")
            rename_btn.connect('clicked', self._on_rename_item, path)
            row.add_suffix(rename_btn)

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
        GLib.idle_add(self.size_label.set_label, f"~{format_size(total)} on server")

    def _on_rename_item(self, _btn, path):
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

    def _on_rename_response(self, _dialog, response, path, entry):
        if response == 'rename':
            name = entry.get_text().strip()
            if name:
                self.selected_display_names[path] = name
                self._save_state()
                self._refresh_backup_list()

    def _on_remove_item(self, _btn, path):
        if path in self.selected_paths:
            self.selected_paths.remove(path)
            self.selected_display_names.pop(path, None)
            self._save_state()
            self._refresh_backup_list()

    def _choose_download_dir(self, _btn):
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

    def _on_backup(self, _btn):
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
        info = {
            'total': 0, 'downloaded': 0, 'done': False,
            'local_path': self.download_dir, 'errors': [],
            'scanning': True, 'files_total': 0, 'files_done': 0,
        }
        self.downloads_in_progress.append(info)
        GLib.idle_add(self._update_download_popup)

        os.makedirs(self.download_dir, exist_ok=True)

        # Phase 1: scan remote vs local, collect only files that need downloading
        files_to_download = []
        for path in paths:
            local_path = os.path.join(self.download_dir, os.path.basename(path))
            try:
                self._collect_files_to_download(path, local_path, files_to_download)
            except Exception as e:
                info['errors'].append(f"{os.path.basename(path)}: {e}")

        info['scanning'] = False
        info['total'] = sum(sz for _, _, sz in files_to_download)
        info['files_total'] = len(files_to_download)
        GLib.idle_add(self._update_download_popup)

        # Phase 2: download with fixed denominator
        for remote_path, local_path, size in files_to_download:
            try:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                self._download_file_tracked(remote_path, local_path, info)
                info['files_done'] += 1
            except Exception as e:
                info['errors'].append(f"{os.path.basename(remote_path)}: {e}")
                info['downloaded'] += size  # advance progress past failed file

        info['done'] = True
        GLib.idle_add(self._update_download_popup)
        GLib.idle_add(self._on_backup_done)

    def _collect_files_to_download(self, remote_path, local_path, file_list):
        with self.connection.lock:
            attr = self.connection.sftp.stat(remote_path)

        if stat.S_ISDIR(attr.st_mode):
            with self.connection.lock:
                entries = list(self.connection.sftp.listdir_attr(remote_path))
            for entry_attr in entries:
                rchild = os.path.join(remote_path, entry_attr.filename)
                lchild = os.path.join(local_path, entry_attr.filename)
                if stat.S_ISDIR(entry_attr.st_mode):
                    self._collect_files_to_download(rchild, lchild, file_list)
                else:
                    try:
                        if os.stat(lchild).st_size == entry_attr.st_size:
                            continue  # already up to date
                    except OSError:
                        pass
                    file_list.append((rchild, lchild, entry_attr.st_size))
        else:
            try:
                if os.stat(local_path).st_size == attr.st_size:
                    return  # already up to date
            except OSError:
                pass
            file_list.append((remote_path, local_path, attr.st_size))

    def _download_file_tracked(self, remote_path, local_path, info):
        prev = [0]
        last_ui = [0.0]

        def callback(transferred, _total_file):
            delta = transferred - prev[0]
            prev[0] = transferred
            info['downloaded'] += delta
            now = time.monotonic()
            if now - last_ui[0] > 0.15:
                last_ui[0] = now
                GLib.idle_add(self._update_download_popup)

        with self.connection.lock:
            self.connection.sftp.get(remote_path, local_path, callback=callback)

    def _on_backup_done(self):
        self.backup_button.set_sensitive(True)
        self.backup_button.set_label("Backup")

    def _update_download_popup(self):
        self._clear_box(self.download_pop_box)

        for info in self.downloads_in_progress:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            if info.get('scanning'):
                row = Gtk.Box(spacing=8)
                sp = Gtk.Spinner()
                sp.start()
                row.append(sp)
                lbl = Gtk.Label(label="Scanning for changes...")
                lbl.set_halign(Gtk.Align.START)
                row.append(lbl)
                box.append(row)

            elif info['done']:
                done_row = Gtk.Box(spacing=8)
                icon = Gtk.Image.new_from_icon_name('emblem-ok-symbolic')
                icon.add_css_class('success')
                done_row.append(icon)

                files_done = info.get('files_done', 0)
                files_total = info.get('files_total', 0)
                skipped = files_total - files_done - len(info.get('errors', []))
                summary = f"{files_done} file(s) downloaded"
                if skipped > 0:
                    summary += f", {skipped} already up to date"
                lbl = Gtk.Label(label=summary)
                lbl.add_css_class('heading')
                lbl.set_wrap(True)
                done_row.append(lbl)
                box.append(done_row)

                for err in info.get('errors', []):
                    el = Gtk.Label(label=f"⚠ {err}")
                    el.add_css_class('error')
                    el.set_wrap(True)
                    el.set_halign(Gtk.Align.START)
                    box.append(el)

                open_btn = Gtk.Button(label="Show in Files")
                open_btn.add_css_class('flat')
                open_btn.connect('clicked', self._open_in_files, info['local_path'])
                box.append(open_btn)

            else:
                files_done = info.get('files_done', 0)
                files_total = info.get('files_total', 0)
                lbl = Gtk.Label(label=f"Downloading... ({files_done}/{files_total} files)")
                lbl.set_halign(Gtk.Align.START)
                box.append(lbl)

                progress = Gtk.ProgressBar()
                frac = info['downloaded'] / info['total'] if info['total'] > 0 else 0
                progress.set_fraction(min(frac, 1.0))
                progress.set_text(
                    f"{format_size(info['downloaded'])} / {format_size(info['total'])}"
                )
                progress.set_show_text(True)
                box.append(progress)

                remaining = max(0, info['total'] - info['downloaded'])
                rem_lbl = Gtk.Label(label=f"{format_size(remaining)} remaining")
                rem_lbl.set_halign(Gtk.Align.START)
                rem_lbl.add_css_class('dim-label')
                box.append(rem_lbl)

            self.download_pop_box.append(box)

    def _open_in_files(self, _btn, path):
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
