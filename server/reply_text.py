"""Readable screen text and a separate, symbol-free narration."""
import re


def readable(text):
    text = re.sub(r'<(?:think|analysis)>.*?</(?:think|analysis)>', '', text, flags=re.S)
    text = re.sub(r'```[^\n]*\n(.*?)```', lambda m: m[1].strip(), text, flags=re.S)
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.M)
    text = re.sub(r'^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*+]\s+', '• ', text, flags=re.M)
    text = re.sub(r'^\s*>\s?', '', text, flags=re.M)
    text = re.sub(r'\*\*(.*?)\*\*|__(.*?)__', lambda m: m[1] or m[2], text, flags=re.S)
    text = re.sub(r'(?<!\w)\*([^*\n]+)\*(?!\w)', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = '\n'.join('  '.join(cell.strip() for cell in line.strip().strip('|').split('|'))
                     if line.strip().startswith('|') else line for line in text.splitlines())
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def spoken(text):
    text = re.sub(r'```.*?```', ' The code is shown on screen. ', text, flags=re.S)
    text = readable(text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'^[ \t]*(?:[•*+-]|\d+[.)])\s+', '', text, flags=re.M)
    text = re.sub(r'[\U0001f000-\U0001faff\u2600-\u27bf]', '', text)
    text = text.replace('&', ' and ').replace('**', '').replace('`', '').replace('|', ', ')
    return re.sub(r'\s+', ' ', text).strip()
