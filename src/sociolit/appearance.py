"""Appearance and workflow settings share the already backed-up preferences file."""
import json
import os
import uuid

THEMES = {'silver', 'sage', 'ocean', 'paper', 'ink', 'lavender', 'teal', 'rose', 'contrast', 'system'}
DEFAULTS = {'theme': 'silver', 'motion': 'gentle', 'density': 'comfortable', 'auto_embed': True}
DESIGNS = {'apple', 'fluent', 'material'}
DEFAULTS['design'] = 'apple'


def read(directory):
    path = directory / 'preferences.json'
    values = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(values, dict):
        raise ValueError('本机设置格式无效，请保留原设置文件。')
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    validate(result)
    return result


def validate(values):
    if (values.get('design', 'apple') not in DESIGNS or values['theme'] not in THEMES or values['motion'] not in {'gentle', 'quick', 'none'}
            or values['density'] not in {'comfortable', 'compact'} or type(values['auto_embed']) is not bool):
        raise ValueError('外观或自动整理设置无效。')


def save(directory, values):
    path = directory / 'preferences.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError('本机设置格式无效，未覆盖。')
    # Old clients can still save the four original fields without resetting a
    # previously chosen design system. Unknown existing preferences stay intact.
    values = {key: values.get(key, previous.get(key, default)) for key, default in DEFAULTS.items()}
    validate(values)
    previous.update(values)
    temporary = path.with_name('preferences.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return values
