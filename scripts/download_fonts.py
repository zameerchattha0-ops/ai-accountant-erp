import re, urllib.request, os, urllib.parse

FAMILIES = {
    'Cinzel': 'Cinzel:wght@400;500;600;700',
    'Cormorant Garamond': 'Cormorant Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600',
    'Fraunces': 'Fraunces:ital,wght@0,400;1,400',
    'DM Serif Display': 'DM Serif Display:ital,wght@0,400;1,400',
    'Antic Didone': 'Antic Didone:wght@400',
    'Bodoni Moda': 'Bodoni Moda:ital,wght@0,400;1,400',
}

OUT_DIR = 'frontend/src/app/fonts'
os.makedirs(OUT_DIR, exist_ok=True)

blocks = {}
for family, query in FAMILIES.items():
    url = f'https://fonts.googleapis.com/css2?family={urllib.parse.quote(query, safe=":;,wghtital@")}'
    try:
        css = urllib.request.urlopen(url, timeout=30).read().decode('utf-8')
    except Exception as e:
        print(f'SKIP {family}: fetch failed -> {e}')
        continue
    for block in re.findall(r'@font-face \{([^}]+)\}', css):
        if 'src:' not in block:
            continue
        m = re.search(r'src:\s*url\(([^)]*?)\)', block)
        if not m:
            continue
        src_raw = m.group(1)
        src = src_raw.strip().strip("'\"")
        if not src:
            continue
        fmt = 'ttf'
        fmtd = re.search(r'format\(([^)]+)\)', block)
        if fmtd:
            fmtd = fmtd.group(1).lower()
            fmt = 'woff2' if 'woff2' in fmtd else ('woff' if 'woff' in fmtd else fmt)
        w = re.search(r'font-weight:\s*([^;]+);', block)
        weight = w.group(1).strip() if w else '400'
        s = re.search(r'font-style:\s*([^;]+);', block)
        style = s.group(1).strip() if s else 'normal'
        key = (family, weight, style)
        if key not in blocks:
            blocks[key] = (src, fmt)

for (family, weight, style), (url, fmt) in blocks.items():
    name = f'{family.replace(" ", "-")}-{weight}-{style}.{fmt}'
    path = os.path.join(OUT_DIR, name)
    if os.path.exists(path):
        print(f'skip {name}')
        continue
    urllib.request.urlretrieve(url, path)
    print(f'ok   {name} ({os.path.getsize(path):,} bytes)')

print(f'\n{len(blocks)} font files ready in {OUT_DIR}')
