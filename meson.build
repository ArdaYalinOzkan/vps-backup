project('vps-backup',
  version: '1.0.0',
  meson_version: '>= 0.59.0',
)

i18n = import('i18n')
python = import('python')
gnome = import('gnome')

py_installation = python.find_installation('python3')

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'src'

conf = configuration_data()
conf.set('PYTHON', py_installation.full_path())
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'io.github.ArdaYalinOzkan.VpsBackup.in',
  output: 'io.github.ArdaYalinOzkan.VpsBackup',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

install_subdir('src', install_dir: pkgdatadir)

subdir('data')
subdir('po')
