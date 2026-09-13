"""Resolve UI vocal preferences into YuE2 native text conditions."""
import re

def resolve_prompt(d):
    mode=d.get('vocalMode','auto')
    if mode not in ('auto','male','female','instrumental'):
        raise ValueError('人声模式无效')
    # Preserve historical snapshots that predate this control exactly.
    if 'vocalMode' not in d and d['lyrics'].strip():
        return d['style'],d['lyrics']
    instrumental=mode=='instrumental' or not d['lyrics'].strip()
    style=d['style']
    if instrumental or mode in ('male','female'):
        style=re.sub(r'男声|女声|(?:fe)?male\s+(?:vocals?|voice)', '', style, flags=re.I)
        if instrumental:
            style=style.rstrip(' ·,')+', instrumental, no vocals'
        else:
            style=mode+' vocal, '+style.strip(' ·,')
    # The text may contain instrument or arrangement directions, even in instrumental mode.
    return style,d['lyrics']
