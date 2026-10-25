#!/usr/bin/env python3
"""Pack the user's original sprite frames as flash-resident RGB565 images."""
from pathlib import Path
from PIL import Image
import hashlib
import json
ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'assets/pets/nomi/source-v2.png'
sheet = Image.open(source).convert('RGBA')
assert sheet.size == (1536,2288)
frames = []
# Stable offsets: idle 0, running 6, ready 12, waiting 18, blocked 24.
for row,count in [(0,6),(7,6),(8,6),(6,6),(5,8)]:
    for col in range(count):
        frame = sheet.crop((col*192,row*208,(col+1)*192,(row+1)*208)).resize((144,156),Image.Resampling.LANCZOS)
        bg = Image.new('RGBA',frame.size,(250,250,252,255)); bg.alpha_composite(frame)
        packed = bytearray()
        for r,g,b in bg.convert('RGB').getdata():
            word = ((r>>3)<<11)|((g>>2)<<5)|(b>>3)
            packed.extend((word&255,word>>8))
        frames.append(packed)
data = b''.join(frames)
output = ROOT/'assets/pets/nomi/frames-rgb565.bin'; output.write_bytes(data)
(ROOT/'assets/pets/nomi/frames.json').write_text(json.dumps({'size':[144,156],'frames':32,'frameBytes':44928,'background':'#fafafc','sha256':hashlib.sha256(data).hexdigest()},indent=2)+'\n')
print(f'Pet: {len(frames)} original frames, {len(data)} bytes in flash; no full-screen RAM buffer.')
