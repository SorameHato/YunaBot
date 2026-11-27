# coding: utf-8
from Library import lib_slash_tone_sync


def test_register_group_is_request_time_and_adds_keys():
    lib_slash_tone_sync.register_group('테스트그룹', {
        'desc': 'test_group_desc',
        'commands': {
            '실행': {'desc': 'test_cmd_desc'},
        },
    })
    try:
        assert '테스트그룹' in lib_slash_tone_sync._GROUP_SPECS
        assert 'test_group_desc' in lib_slash_tone_sync._SLASH_TONE_KEYS
        assert 'test_cmd_desc' in lib_slash_tone_sync._SLASH_TONE_KEYS
    finally:
        lib_slash_tone_sync._GROUP_SPECS.pop('테스트그룹', None)
