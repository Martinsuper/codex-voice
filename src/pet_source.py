"""Read only the selected pet and its artwork reference; never read auth material.

The private desktop cache adapter is intentionally narrow and version tolerant.
Its transient stdout goes only to the native companion, not status.json or logs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import tomllib
import zlib
from urllib.parse import urlsplit

BUILTINS=frozenset({'codex','dewey','fireball','hoots','rocky','seedy','stacky','bsod','null-signal'})
MAX_IMAGE=20*1024*1024

class PetSourceError(ValueError):
    pass

def bounded(path,limit):
    if path.stat().st_size>limit:raise PetSourceError('宠物配置过大，保留当前形象。')
    return path.read_bytes()

def safe_url(value):
    if not isinstance(value,str) or len(value)>16384:return False
    try:
        p=urlsplit(value);h=(p.hostname or '').lower()
        return p.scheme=='https' and p.port in (None,443) and not p.username and not p.password and any(h==s or h.endswith('.'+s) for s in ['oaiusercontent.com','oaistatic.com','blob.core.windows.net'])
    except ValueError:return False

def local_source(codex,pet_id):
    slug=pet_id.removeprefix('custom:')
    for folder,manifest in [('pets','pet.json'),('avatars','avatar.json')]:
        directory=(codex/folder/slug).resolve();path=directory/manifest
        if not path.is_file():continue
        meta=json.loads(bounded(path,65536));version=meta.get('spriteVersionNumber',1)
        relative=meta.get('spritesheetPath','spritesheet.webp')
        if type(version) is not int or version not in (1,2) or not isinstance(relative,str) or Path(relative).is_absolute():raise PetSourceError('本地宠物资源无效。')
        image=(directory/relative).resolve()
        if not image.is_relative_to(directory) or image==directory or image.suffix.lower() not in ('.png','.webp'):raise PetSourceError('本地宠物图片必须保存在宠物目录内。')
        raw=bounded(image,MAX_IMAGE)
        return {'kind':'range','path':str(image),'offset':0,'size':len(raw),'version':version,'fingerprint':hashlib.sha256(raw).hexdigest()}
    raise PetSourceError('未找到选中的本地宠物，保留当前形象。')

def image_range(raw,version):
    """Find only a complete sprite image in a cache entry, excluding HTTP metadata."""
    start=raw.find(b'\x89PNG\r\n\x1a\n')
    if start>=0 and start+24<=len(raw):
        if struct.unpack('>II',raw[start+16:start+24]) != (1536,2288 if version==2 else 1872):return None
        pos=start+8
        while pos+12<=len(raw):
            size=struct.unpack('>I',raw[pos:pos+4])[0];end=pos+12+size
            if size>MAX_IMAGE or end>len(raw) or end-start>MAX_IMAGE:return None
            kind=raw[pos+4:pos+8]
            if zlib.crc32(raw[pos+4:pos+8+size]) != struct.unpack('>I',raw[pos+8+size:end])[0]:return None
            if kind==b'IEND':return (start,end-start) if size==0 else None
            pos=end
    start=raw.find(b'RIFF')
    if start>=0 and raw[start+8:start+12]==b'WEBP':
        size=8+struct.unpack('<I',raw[start+4:start+8])[0]
        if 12<=size<=MAX_IMAGE and start+size<=len(raw):return start,size
    return None

def cached_cloud_image(url,version,cache_dirs):
    normalized=urlsplit(url)._replace(query='',fragment='').geturl().encode()
    for root in cache_dirs:
        if not root.is_dir():continue
        # Inspect only the key prefix of entries; read a body only after its
        # immutable resource URL matches the user's selected pet exactly.
        for path in root.glob('*_0'):
            try:
                if path.is_symlink() or path.stat().st_size>MAX_IMAGE+65536:continue
                with path.open('rb') as f:head=f.read(16384)
                at=head.find(normalized)
                if at<0:continue
                following=head[at+len(normalized):at+len(normalized)+1]
                if following and following not in (b'?',b'\x00',b'\n',b'\r',b' '):continue
                image=image_range(path.read_bytes(),version)
                if image:return {'kind':'range','path':str(path),'offset':image[0],'size':image[1],'version':version}
            except OSError:continue
    return None

def builtin_source(app,pet_id):
    if pet_id not in BUILTINS:raise PetSourceError('尚不支持此宠物，保留当前形象。')
    asar=app/'Contents/Resources/app.asar'
    with asar.open('rb') as f:
        raw=f.read(16)
        if len(raw)!=16:raise PetSourceError('无法读取 Codex 宠物资源。')
        _,header_size,_,json_size=struct.unpack('<4I',raw)
        if not 0<json_size<=header_size<=32*1024*1024:raise PetSourceError('Codex 资源格式已变化，保留当前形象。')
        header=json.loads(f.read(json_size));base=8+header_size
        files=header['files']['webview']['files']['assets']['files']
        pattern=re.compile(re.escape(pet_id)+r'-spritesheet-v\d+-[a-f0-9]+\.(?:webp|png)')
        matches=[(n,v) for n,v in files.items() if pattern.fullmatch(n) and not v.get('unpacked')]
        if len(matches)!=1:raise PetSourceError('未找到内置宠物图片，保留当前形象。')
        name,entry=matches[0];offset=base+int(entry['offset']);size=entry['size']
        if type(size) is not int or not 0<size<=MAX_IMAGE or offset<base or offset+size>asar.stat().st_size:raise PetSourceError('Codex 资源边界无效。')
    return {'kind':'range','path':str(asar),'offset':offset,'size':size,'version':2,'fingerprint':name}

def selected_source(codex,app,cache_dirs=None):
    config=tomllib.loads(bounded(codex/'config.toml',4*1024*1024).decode())
    pet_id=config.get('desktop',{}).get('selected-avatar-id')
    if pet_id is None:return {'state':'no-selection','detail':'Codex 未选择宠物，保留工牌当前形象。'}
    if not isinstance(pet_id,str) or not re.fullmatch(r'(?:pet_[a-zA-Z0-9_-]{1,100}|custom:[a-zA-Z0-9_-]{1,100}|[a-z-]{1,30})',pet_id):raise PetSourceError('宠物选择格式已变化，保留当前形象。')
    if pet_id in BUILTINS:source=builtin_source(app,pet_id)
    elif pet_id.startswith('pet_'):
        state=json.loads(bounded(codex/'.codex-global-state.json',16*1024*1024))
        pets=state.get('electron-persisted-atom-state',{}).get('cloud-pet-artwork-cache',{}).get('pets',[])
        pet=next((p for p in pets if isinstance(p,dict) and p.get('id')==pet_id),None)
        if pet is None:raise PetSourceError('等待 Codex 加载新宠物，稍后自动重试。')
        if not safe_url(pet.get('spritesheetUrl')):raise PetSourceError('宠物资源地址不受支持，保留当前形象。')
        version=pet.get('spriteVersionNumber')
        if type(version) is not int or version not in (1,2):raise PetSourceError('宠物动画格式暂不支持。')
        fingerprint=pet.get('spritesheetFingerprint') or urlsplit(pet['spritesheetUrl']).path
        if not isinstance(fingerprint,str) or len(fingerprint)>4096:raise PetSourceError('宠物资源信息不完整。')
        if cache_dirs is None:
            base=Path.home()/'Library/Caches/Codex'
            cache_dirs=[base/'Default/Cache/Cache_Data',base/'Cache/Cache_Data']
        source=cached_cloud_image(pet['spritesheetUrl'],version,cache_dirs)
        if source is None:
            source=({'kind':'https','url':pet['spritesheetUrl'],'version':version} if urlsplit(pet['spritesheetUrl']).query
                    else {'kind':'waiting-image','version':version})
        source['fingerprint']=fingerprint
    elif pet_id.startswith('custom:'):source=local_source(codex,pet_id)
    else:raise PetSourceError('尚不支持此宠物，保留当前形象。')
    identity=hashlib.sha256(json.dumps([pet_id,source['version'],source.pop('fingerprint'),'badge-pet-format-1'],ensure_ascii=True).encode()).hexdigest()
    return dict(source,state='ready',id=pet_id,identity=identity)

def main():
    p=argparse.ArgumentParser();p.add_argument('--codex-dir',type=Path,required=True);p.add_argument('--app',type=Path,required=True);args=p.parse_args()
    try:result=selected_source(args.codex_dir,args.app)
    except PetSourceError as e:result={'state':'waiting','detail':str(e)}
    except (OSError,ValueError,KeyError,TypeError,StopIteration):result={'state':'waiting','detail':'暂时无法读取 Codex 宠物，稍后自动重试。'}
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
