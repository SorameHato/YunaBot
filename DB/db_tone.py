# coding: utf-8
from typing import Optional, Dict, Any
import importlib.util
import inspect
import pathlib

from . import db_setting

DEFAULT_PROFILE = "default"
TONE_DIR = pathlib.Path(__file__).resolve().parent.parent / "tone"


def _load_module(path: pathlib.Path):
    try:
        spec = importlib.util.spec_from_file_location(f"tone_{path.stem}", path)
        if spec is None or spec.loader is None:
            print(f'[tone] skip (no loader): {path.name}')
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        print(f'[tone] load failed, skipping {path.name}: {exc}')
        return None


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
    addon_profile_templates: Dict[str, Dict[str, str]] = {}
    addon_profile_titles: Dict[str, str] = {}

    if not TONE_DIR.exists():
        return (
            profile_templates,
            profile_titles,
            guild_templates,
            addon_profile_templates,
            addon_profile_titles,
        )

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
                profile_template = templates.get(DEFAULT_PROFILE)
                if profile_template is None:
                    for candidate in templates.values():
                        if isinstance(candidate, dict):
                            profile_template = candidate
                            break
                if isinstance(profile_template, dict) and profile_template:
                    addon_profile_templates[stem] = profile_template
                    addon_profile_titles[stem] = str(getattr(module, "PARM_TITLE", stem))

                for guild_id in guild_ids or []:
                    guild_templates[int(guild_id)] = templates
            continue

        templates = getattr(module, "LANG_PACK", None)
        if templates is None:
            templates = getattr(module, "TONE_PACK", None)
        templates = _normalize_profile_templates(templates)
        if templates:
            profile_templates[stem] = templates
            profile_titles[stem] = str(getattr(module, "PARM_TITLE", stem))

    return (
        profile_templates,
        profile_titles,
        guild_templates,
        addon_profile_templates,
        addon_profile_titles,
    )


(
    PROFILE_TEMPLATES,
    PROFILE_TITLES,
    GUILD_TEMPLATES,
    ADDON_PROFILE_TEMPLATES,
    ADDON_PROFILE_TITLES,
) = _load_tone_templates()
PROFILE_TITLE_TO_STEM = _build_title_to_stem(PROFILE_TITLES)
ACTIVE_ADDON_PROFILES: set[str] = set()
_COMMAND_BOOT_PROFILE = DEFAULT_PROFILE


def reload_tone_templates() -> None:
    global PROFILE_TEMPLATES, PROFILE_TITLES, PROFILE_TITLE_TO_STEM, GUILD_TEMPLATES
    global ADDON_PROFILE_TEMPLATES, ADDON_PROFILE_TITLES
    global ACTIVE_ADDON_PROFILES, _COMMAND_BOOT_PROFILE
    (
        PROFILE_TEMPLATES,
        PROFILE_TITLES,
        GUILD_TEMPLATES,
        ADDON_PROFILE_TEMPLATES,
        ADDON_PROFILE_TITLES,
    ) = _load_tone_templates()
    ACTIVE_ADDON_PROFILES = {
        stem for stem in ACTIVE_ADDON_PROFILES if stem in ADDON_PROFILE_TEMPLATES
    }
    if _COMMAND_BOOT_PROFILE not in ACTIVE_ADDON_PROFILES:
        _COMMAND_BOOT_PROFILE = DEFAULT_PROFILE
    PROFILE_TITLE_TO_STEM = _build_title_to_stem(PROFILE_TITLES)


def _addon_profile_stem(addon_no: str | int | None) -> str | None:
    if addon_no is None:
        return None
    stem = str(addon_no).strip()
    if not stem:
        return None
    if stem.startswith("addon_"):
        raw_no = stem[6:]
    else:
        raw_no = stem
    if not raw_no.isdigit():
        return None
    return f"addon_{raw_no.zfill(4)}"


def resolve_bot_boot_profile(bot) -> str:
    """Return default or boot tone profile for a bot instance (not guild tone_profile)."""
    profile_key = getattr(bot, "tone_boot_profile", None)
    if profile_key:
        profile_key = resolve_profile_stem(str(profile_key), DEFAULT_PROFILE)
    if profile_key in PROFILE_TEMPLATES:
        return profile_key
    return DEFAULT_PROFILE


def render_boot_message(message_key: str, profile_key: str, **kwargs) -> str:
    resolved = resolve_profile_stem(str(profile_key), DEFAULT_PROFILE)
    template = _get_profile_template(resolved, message_key, DEFAULT_PROFILE)
    if template is None:
        return message_key
    if not isinstance(template, str):
        return message_key
    return format_template(template, **kwargs)


def enable_addon_profile(addon_no: str | int | None) -> bool:
    stem = _addon_profile_stem(addon_no)
    if stem is None:
        return False
    templates = ADDON_PROFILE_TEMPLATES.get(stem)
    if not templates:
        return False

    PROFILE_TEMPLATES[stem] = templates
    PROFILE_TITLES[stem] = ADDON_PROFILE_TITLES.get(stem, stem)
    ACTIVE_ADDON_PROFILES.add(stem)
    global PROFILE_TITLE_TO_STEM
    PROFILE_TITLE_TO_STEM = _build_title_to_stem(PROFILE_TITLES)
    return True


def set_command_boot_profile(profile_key: str | None) -> str:
    global _COMMAND_BOOT_PROFILE
    prev = _COMMAND_BOOT_PROFILE
    if profile_key is None:
        _COMMAND_BOOT_PROFILE = DEFAULT_PROFILE
        return prev

    stem = _addon_profile_stem(profile_key)
    if stem and stem in ACTIVE_ADDON_PROFILES:
        _COMMAND_BOOT_PROFILE = stem
        return prev

    resolved = resolve_profile_stem(str(profile_key), DEFAULT_PROFILE)
    if resolved in PROFILE_TEMPLATES:
        _COMMAND_BOOT_PROFILE = resolved
    else:
        _COMMAND_BOOT_PROFILE = DEFAULT_PROFILE
    return prev


def _resolve_command_profile(guild: int | None = None) -> str:
    if guild:
        return get_profile_key(guild, DEFAULT_PROFILE)

    if _COMMAND_BOOT_PROFILE in PROFILE_TEMPLATES:
        return _COMMAND_BOOT_PROFILE
    return DEFAULT_PROFILE


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


def _default_template_pack() -> Dict[str, Any]:
    return PROFILE_TEMPLATES.get(DEFAULT_PROFILE) or {}


def _lookup_template(
    pack: Dict[str, Any],
    message_key: str,
    *,
    fallback_pack: Dict[str, Any] | None = None,
) -> Optional[Any]:
    template = pack.get(message_key)
    if template is not None:
        return template
    if fallback_pack is not None:
        return fallback_pack.get(message_key)
    return None


def get_default_template(message_key: str) -> Optional[Any]:
    return _default_template_pack().get(message_key)


def get_command_template(message_key: str, guild: int | None = None) -> Optional[Any]:
    profile_key = _resolve_command_profile(guild)
    if guild:
        template = _get_guild_template(guild, profile_key, message_key, DEFAULT_PROFILE)
        if template is not None:
            return template
    return _get_profile_template(profile_key, message_key, DEFAULT_PROFILE)


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
) -> Optional[Any]:
    profile_key = resolve_profile_stem(profile_key, default_profile)
    profile = PROFILE_TEMPLATES.get(profile_key) or {}
    fallback_pack = None
    if profile_key != default_profile:
        fallback_pack = PROFILE_TEMPLATES.get(default_profile) or {}
    template = _lookup_template(profile, message_key, fallback_pack=fallback_pack)
    if template is not None:
        return template
    if profile_key == default_profile:
        for stem in sorted(ACTIVE_ADDON_PROFILES):
            addon_template = (PROFILE_TEMPLATES.get(stem) or {}).get(message_key)
            if addon_template is not None:
                return addon_template
    return None


def _get_guild_template(
    guild: int,
    profile_key: str,
    message_key: str,
    default_profile: str,
) -> Optional[Any]:
    profiles = GUILD_TEMPLATES.get(guild) or {}
    profile_key = resolve_profile_stem(profile_key, default_profile)
    if profile_key not in profiles:
        return None
    return profiles[profile_key].get(message_key)


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


def render_default_message(message_key: str, guild: int | None = None, **kwargs) -> str:
    template = get_command_template(message_key, guild=guild)
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


def render_name(guild: int, default_profile: str = DEFAULT_PROFILE) -> str:
    if guild:
        name = render_message(guild, 'bot_name', default_profile=default_profile)
        if name != 'bot_name':
            return name
    return render_default_name()


def render_embed_footer(guild: int, ver: str, default_profile: str = DEFAULT_PROFILE) -> str:
    bot_name = render_name(guild, default_profile)
    if guild:
        footer = render_message(
            guild,
            'embed_footer',
            default_profile=default_profile,
            bot_name=bot_name,
            ver=ver,
        )
        if footer != 'embed_footer':
            return footer
    footer = render_default_message('embed_footer', bot_name=bot_name, ver=ver)
    if footer != 'embed_footer':
        return footer
    return f'{bot_name} 버전 {ver}'


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


def render_message_for_profile(guild: int, message_key: str, profile_key: str, **kwargs) -> str:
    """Render using a previously loaded profile, without querying guild settings."""
    template = _get_guild_template(guild, profile_key, message_key, DEFAULT_PROFILE)
    if template is None:
        template = _get_profile_template(profile_key, message_key, DEFAULT_PROFILE)
    if not isinstance(template, str):
        return message_key
    return format_template(template, **kwargs)


def render_validation_error(guild_id: int | None, reason: str) -> str:
    """Caller-attributed validation error. file/func are taken from the call site."""
    frame = inspect.currentframe()
    try:
        caller = frame.f_back if frame is not None else None
        if caller is None:
            file_name = '?'
            func_name = '?'
        else:
            file_name = pathlib.Path(caller.f_code.co_filename).stem
            func_name = caller.f_code.co_name
            self_obj = caller.f_locals.get('self')
            if self_obj is not None:
                func_name = f'{type(self_obj).__name__}.{func_name}'
    finally:
        del frame

    kwargs = {'file': file_name, 'func': func_name, 'reason': reason}
    gid = int(guild_id) if guild_id else 0
    if gid:
        text = render_message(gid, 'validation_error', **kwargs)
        if text != 'validation_error':
            return text
    return render_default_message('validation_error', **kwargs)


def render_command_message(guild: int, message_key: str, **kwargs) -> str:
    template = get_command_template(message_key, guild=guild)
    if template is None:
        return message_key
    if not isinstance(template, str):
        return message_key
    return format_template(template, **kwargs)
