"""Reproduce the actual stale build/lib publication failure, without a service."""
import os

from setuptools import Distribution

from apatch_studio import build_assets


def test_stale_newer_build_copy_and_removed_module_never_enter_package(tmp_path, monkeypatch):
    source = tmp_path / 'apatch_studio'
    source.mkdir()
    (source / '__init__.py').write_text('VERSION = "new"\n')
    os.utime(source / '__init__.py', (1, 1))
    output = tmp_path / 'build/lib/apatch_studio'
    output.mkdir(parents=True)
    (output / '__init__.py').write_text('VERSION = "stale"\n')
    (output / 'removed.py').write_text('REMOVED = True\n')
    frontend = tmp_path / 'frontend/dist'
    (frontend / 'assets').mkdir(parents=True)
    (frontend / 'assets/app.js').write_text('/* current client */')
    (frontend / 'theme-init.js').write_text('/* current theme */')
    (frontend / 'index.html').write_text(
        '<meta content="__APATCH_STUDIO_SESSION__"><script src="/theme-init.js"></script>'
        '<script src="/assets/app.js"></script>')
    monkeypatch.setattr(build_assets, 'ROOT', tmp_path)
    distribution = Distribution({'packages': ['apatch_studio'],
        'package_dir': {'apatch_studio': str(source)}})
    distribution.script_name = str(tmp_path / 'setup.py')
    command = build_assets.BuildWithFrontend(distribution)
    command.ensure_finalized()
    command.build_lib = str(output.parent)
    command.run()
    assert (output / '__init__.py').read_bytes() == (source / '__init__.py').read_bytes()
    assert not (output / 'removed.py').exists()
    assert (output / '_web/assets/app.js').read_bytes() == (frontend / 'assets/app.js').read_bytes()
