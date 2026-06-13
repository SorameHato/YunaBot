# coding: utf-8
from typing import Optional, Dict, Any
import importlib.util
import pathlib

try:
    from . import db_setting
except ImportError:
    import db_setting

DEFAULT_PROFILE = "default"
TONE_DIR = pathlib.Path(__file__).parent / "tone"


def _load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"tone_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_profile_templates(templates) -> Dict[str, str]:
    if not isinstance(templates, dict):
        return {}
    return templates


def _normalize_guild_templates(templates) -> Dict[str, Dict[str, str]]:
    if not isinstance(templates, dict):
        return {}
    if templates and all(not isinstance(value, dict) for value in templates.values()):
        return {DEFAULT_PROFILE: templates}
    return templates


def _build_title_to_stem(titles: Dict[str, str]) -> Dict[str, str]:
    return {title: stem for stem, title in titles.items()}


def _load_tone_templates():
    profile_templates: Dict[str, Dict[str, str]] = {}
    profile_titles: Dict[str, str] = {}
    guild_templates: Dict[int, Dict[str, Dict[str, str]]] = {}

    if not TONE_DIR.exists():
        return profile_templates, profile_titles, guild_templates

    for path in TONE_DIR.glob("*.py"):
        if path.name == "__init__.py":
            continue
        module = _load_module(path)
        if module is None:
            continue

        stem = path.stem
        if stem.startswith("addon_"):
            guild_ids:list = getattr(module, "PARM_ER_GUILD", None)
            templates = getattr(module, "LANG_PACK", None)
            if templates is None:
                templates = getattr(module, "GUILD_PACK", None)
            templates = _normalize_guild_templates(templates)
            if templates:
                for guild_id in guild_ids:
                    guild_templates[int(guild_id)] = templates
            continue

        templates = getattr(module, "LANG_PACK", None)
        if templates is None:
            templates = getattr(module, "TONE_PACK", None)
        templates = _normalize_profile_templates(templates)
        if templates:
            profile_templates[stem] = templates
            profile_titles[stem] = str(getattr(module, "PARM_TITLE", stem))

    return profile_templates, profile_titles, guild_templates


PROFILE_TEMPLATES, PROFILE_TITLES, GUILD_TEMPLATES = _load_tone_templates()
PROFILE_TITLE_TO_STEM = _build_title_to_stem(PROFILE_TITLES)


def reload_tone_templates() -> None:
    global PROFILE_TEMPLATES, PROFILE_TITLES, PROFILE_TITLE_TO_STEM, GUILD_TEMPLATES
    PROFILE_TEMPLATES, PROFILE_TITLES, GUILD_TEMPLATES = _load_tone_templates()
    PROFILE_TITLE_TO_STEM = _build_title_to_stem(PROFILE_TITLES)


def resolve_profile_stem(profile_key: str, default_profile: str = DEFAULT_PROFILE) -> str:
    if profile_key in PROFILE_TEMPLATES:
        return profile_key
    stem = PROFILE_TITLE_TO_STEM.get(profile_key)
    if stem:
        return stem
    return default_profile


def get_profile_title(profile_key: str) -> str:
    stem = resolve_profile_stem(profile_key, profile_key)
    return PROFILE_TITLES.get(stem, profile_key)


def get_profile_key(guild: int, default_profile: str = DEFAULT_PROFILE) -> str:
    try:
        profile = db_setting.get_setting(guild, "tone_profile")
    except Exception:
        profile = None
    if not profile:
        return default_profile
    return resolve_profile_stem(str(profile), default_profile)


def get_default_template(message_key: str) -> Optional[Any]:
    pack = PROFILE_TEMPLATES.get(DEFAULT_PROFILE) or {}
    return pack.get(message_key)


def get_template(
    guild: int,
    message_key: str,
    default_profile: str = DEFAULT_PROFILE,
) -> Optional[Any]:
    profile_key = get_profile_key(guild, default_profile)
    template = _get_guild_template(guild, profile_key, message_key, default_profile)
    if template is not None:
        return template
    return _get_profile_template(profile_key, message_key, default_profile)


def get_message_template(
    guild: int,
    message_key: str,
    default_profile: str = DEFAULT_PROFILE,
) -> Optional[str]:
    template = get_template(guild, message_key, default_profile)
    if isinstance(template, str):
        return template
    return None


def _get_profile_template(
    profile_key: str,
    message_key: str,
    default_profile: str,
) -> Optional[str]:
    profile_key = resolve_profile_stem(profile_key, default_profile)
    profile = PROFILE_TEMPLATES.get(profile_key) or {}
    template = profile.get(message_key)
    if template is None and profile_key != default_profile:
        template = (PROFILE_TEMPLATES.get(default_profile) or {}).get(message_key)
    return template


def _get_guild_template(
    guild: int,
    profile_key: str,
    message_key: str,
    default_profile: str,
) -> Optional[str]:
    profiles = GUILD_TEMPLATES.get(guild) or {}
    profile = profiles.get(profile_key) or {}
    template = profile.get(message_key)
    if template is None and profile_key != default_profile:
        template = (profiles.get(default_profile) or {}).get(message_key)
    return template


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


_RENDER_RESERVED_KEYS = frozenset({'guild', 'message_key', 'default_profile', 'template'})


def _tone_format_kwargs(**kwargs) -> dict:
    return {key: value for key, value in kwargs.items() if key not in _RENDER_RESERVED_KEYS}


def format_template(template: str, **kwargs) -> str:
    if not isinstance(template, str):
        return str(template)
    try:
        return template.format_map(_SafeDict(_tone_format_kwargs(**kwargs)))
    except Exception:
        return template


def render_default_message(message_key: str, **kwargs) -> str:
    template = get_default_template(message_key)
    if template is None:
        return message_key
    if not isinstance(template, str):
        return message_key
    return format_template(template, **kwargs)


def render_default_name() -> str:
    template = get_default_template('bot_name')
    if template is None:
        return '유나봇'
    if not isinstance(template, str):
        return str(template)
    return template


def render_message(
    guild: int,
    message_key: str,
    default_profile: str = DEFAULT_PROFILE,
    **kwargs,
) -> str:
    template = get_template(guild, message_key, default_profile)
    if template is None:
        return message_key
    if not isinstance(template, str):
        return message_key
    return format_template(template, **kwargs)
