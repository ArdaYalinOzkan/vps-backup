desktop_file = i18n.merge_file(
  input: 'io.github.ArdaYalinOzkan.VpsBackup.desktop.in',
  output: 'io.github.ArdaYalinOzkan.VpsBackup.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications'
)

appstream_file = i18n.merge_file(
  input: 'io.github.ArdaYalinOzkan.VpsBackup.metainfo.xml.in',
  output: 'io.github.ArdaYalinOzkan.VpsBackup.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo'
)

install_data(
  'io.github.ArdaYalinOzkan.VpsBackup.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas'
)

gnome.compile_resources('io.github.ArdaYalinOzkan.VpsBackup',
  'io.github.ArdaYalinOzkan.VpsBackup.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

install_data(
  'io.github.ArdaYalinOzkan.VpsBackup.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps'
)
