desktop_file = i18n.merge_file(
  input: 'io.github.vpsbackup.VpsBackup.desktop.in',
  output: 'io.github.vpsbackup.VpsBackup.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications'
)

appstream_file = i18n.merge_file(
  input: 'io.github.vpsbackup.VpsBackup.metainfo.xml.in',
  output: 'io.github.vpsbackup.VpsBackup.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo'
)

install_data(
  'io.github.vpsbackup.VpsBackup.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas'
)

gnome.compile_resources('io.github.vpsbackup.VpsBackup',
  'io.github.vpsbackup.VpsBackup.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

install_data(
  'io.github.vpsbackup.VpsBackup.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps'
)
