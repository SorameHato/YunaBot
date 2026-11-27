"""The shared tree must not depend on modules shipped only with addon."""
import ast
import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_imports_do_not_depend_on_addon_modules():
    forbidden = ('Addon', 'addon_main', 'addon_scope', 'DB.db_addon_',
                 'Library.lib_music_', 'Library.lib_ohaasa', 'Library.lib_addon_', 'tone.addon_')
    files = [ROOT / 'main.py']
    for folder in ('Cogs', 'DB', 'Library'):
        files.extend(p for p in (ROOT / folder).glob('*.py')
                     if not p.stem.startswith(('db_addon_', 'lib_music_', 'lib_ohaasa')))
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level:
                    module = path.parent.name + ('.' + module if module else '')
                names = [module + '.' + alias.name for alias in node.names]
            assert not any(name.startswith(forbidden) for name in names), (path, names)


def test_all_core_cogs_import_without_loading_bot_entrypoints():
    for path in (ROOT / 'Cogs').glob('c_*.py'):
        importlib.import_module('Cogs.' + path.stem)


def test_public_tree_has_no_addon_implementation():
    # The same shared tests also run on the operational branch.
    if (ROOT / 'addon_scope.py').exists():
        return
    for pattern in ('Addon', 'addon_main.py', 'intranet_web', 'tone/addon_*.py',
                    'DB/db_addon_*.py', 'Library/lib_music_*.py', 'Library/lib_ohaasa.py',
                    'requirements-addon.txt', 'pull_addon.sh', 'pull_and_restart.sh'):
        assert not list(ROOT.glob(pattern)), pattern
