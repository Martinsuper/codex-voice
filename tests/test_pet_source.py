import json
from pathlib import Path
import struct
import zlib
import tempfile
import unittest
from pet_source import selected_source,safe_url,PetSourceError

class PetSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.codex=self.root/'codex';self.codex.mkdir();self.app=self.root/'App.app';(self.app/'Contents/Resources').mkdir(parents=True)
    def config(self,pet):
        (self.codex/'config.toml').write_text('[desktop]\nselected-avatar-id = '+json.dumps(pet)+'\n')
    def cache(self,pet='pet_a',fingerprint='image1',query='first'):
        value={'electron-persisted-atom-state':{'cloud-pet-artwork-cache':{'pets':[{'id':pet,'spriteVersionNumber':2,'spritesheetFingerprint':fingerprint,'spritesheetUrl':'https://example.oaiusercontent.com/image?token='+query}]}}}
        (self.codex/'.codex-global-state.json').write_text(json.dumps(value))
    def test_tracks_current_desktop_selection_not_stale_cloud_selection(self):
        self.config('pet_new');self.cache('pet_new');self.assertEqual(selected_source(self.codex,self.app,cache_dirs=[])['id'],'pet_new')
    def test_expiring_url_does_not_change_identity_but_artwork_does(self):
        self.config('pet_a');self.cache(query='a');a=selected_source(self.codex,self.app,cache_dirs=[])
        self.cache(query='b');b=selected_source(self.codex,self.app,cache_dirs=[]);self.assertEqual(a['identity'],b['identity']);self.assertNotEqual(a['url'],b['url'])
        self.cache(fingerprint='image2');self.assertNotEqual(a['identity'],selected_source(self.codex,self.app,cache_dirs=[])['identity'])
    def test_missing_and_partial_state_preserves_previous_resource(self):
        self.config('pet_b');self.cache('pet_a')
        with self.assertRaises(PetSourceError):selected_source(self.codex,self.app,cache_dirs=[])
        (self.codex/'config.toml').write_text('[desktop]\n');self.assertEqual(selected_source(self.codex,self.app,cache_dirs=[])['state'],'no-selection')
    def test_url_allowlist_blocks_local_plaintext_and_credentials(self):
        for url in ['file:///etc/passwd','http://example.oaiusercontent.com/a','https://127.0.0.1/a','https://oaiusercontent.com.attacker.invalid/a','https://user:pass@a.oaiusercontent.com/a','https://a.oaiusercontent.com:444/a']:
            self.assertFalse(safe_url(url),url)
        self.assertTrue(safe_url('https://a.oaiusercontent.com/a?token=private'))
    def test_malformed_and_traversal_selection_rejected(self):
        for pet in ['../pet','custom:../../x','https://x','pet_']:
            self.config(pet)
            with self.assertRaises(PetSourceError):selected_source(self.codex,self.app,cache_dirs=[])
    def test_builtin_from_installed_archive_without_network(self):
        self.config('dewey');data=b'fixture-webp';name='dewey-spritesheet-v5-123abc.webp'
        header={'files':{'webview':{'files':{'assets':{'files':{name:{'size':len(data),'offset':'0'}}}}}}}
        raw=json.dumps(header).encode();header_size=8+len(raw)
        (self.app/'Contents/Resources/app.asar').write_bytes(struct.pack('<4I',4,header_size,header_size-4,len(raw))+raw+data)
        source=selected_source(self.codex,self.app,cache_dirs=[]);self.assertEqual(source['kind'],'range');self.assertEqual(source['size'],len(data))
        with Path(source['path']).open('rb') as f:f.seek(source['offset']);self.assertEqual(f.read(source['size']),data)
    def test_local_and_legacy_pet_change_detected_without_changing_name(self):
        self.config('custom:local-one');folder=self.codex/'avatars/local-one';folder.mkdir(parents=True)
        (folder/'avatar.json').write_text(json.dumps({'displayName':'Some Other Name','spriteVersionNumber':2,'spritesheetPath':'sheet.png'}))
        image=folder/'sheet.png';image.write_bytes(b'old');a=selected_source(self.codex,self.app,cache_dirs=[])
        image.write_bytes(b'new');b=selected_source(self.codex,self.app,cache_dirs=[])
        self.assertNotEqual(a['identity'],b['identity']);self.assertNotIn('displayName',b)
        (folder/'avatar.json').write_text(json.dumps({'spritesheetPath':'../../outside.png'}))
        with self.assertRaises(PetSourceError):selected_source(self.codex,self.app,cache_dirs=[])
    def test_cloud_disk_cache_extracts_only_selected_image_without_url_secrets(self):
        self.config('pet_a');self.cache();root=self.root/'image-cache';root.mkdir()
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1536,2288,8,6,0,0,0))+chunk(b'IEND',b'')
        key=b'https://example.oaiusercontent.com/image?token=do-not-export'
        (root/'abc123_0').write_bytes(b'cache-key:'+key+b'\x00'+png+b'HTTP metadata')
        source=selected_source(self.codex,self.app,cache_dirs=[root]);self.assertEqual(source['kind'],'range');self.assertNotIn('url',source)
        raw=Path(source['path']).read_bytes();self.assertEqual(raw[source['offset']:source['offset']+source['size']],png)
        broken=bytearray(raw);broken[source['offset']+20]^=1;(root/'abc123_0').write_bytes(broken)
        self.assertEqual(selected_source(self.codex,self.app,cache_dirs=[root])['kind'],'https')
    def test_missing_download_still_exposes_stable_identity_for_own_cache_reuse(self):
        self.config('pet_a');self.cache(query='');p=self.codex/'.codex-global-state.json';v=json.loads(p.read_text())
        v['electron-persisted-atom-state']['cloud-pet-artwork-cache']['pets'][0]['spritesheetUrl']='https://example.oaiusercontent.com/image';p.write_text(json.dumps(v))
        source=selected_source(self.codex,self.app,cache_dirs=[]);self.assertEqual(source['kind'],'waiting-image');self.assertEqual(len(source['identity']),64)

if __name__=='__main__':unittest.main()
