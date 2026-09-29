"""Contracts from the official legacy Minecraft version metadata."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cia_patcher

VANILLA_ARGS = ('--username ${auth_player_name} --version ${version_name} '
                '--gameDir ${game_directory} --assetsDir ${assets_root} '
                '--assetIndex ${assets_index_name} --uuid ${auth_uuid} '
                '--accessToken ${auth_access_token} --userProperties ${user_properties} '
                '--userType ${user_type}')
CB_ARGS = ('--username ${auth_player_name} --gameDir ${game_directory} '
           '--assetsDir ${assets_root} --uuid ${auth_uuid} '
           '--accessToken ${auth_access_token} --userType ${user_type}')


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for launch argument tests')
class LaunchArgumentTests(unittest.TestCase):
    def evaluate(self, version, args=VANILLA_ARGS, patched=True, token='0', metadata=None):
        source = (Path(__file__).parent / 'fixtures/launch_map.js').read_text()
        _, anchor, replacement, marker = next(p for p in cia_patcher.JS_PATCHES
                                              if p[0] == 'vanilla launch placeholders')
        self.assertEqual(source.count(anchor), 1)
        if patched:
            source = source.replace(anchor, replacement)
            self.assertIn(marker, source)
        expression = source.split('d=', 1)[1].split(',f=function', 1)[0]
        data = {'expression': expression, 'version': version, 'args': args, 'token': token,
                'metadata': metadata or {'id': version, 'assetIndex': {'id': '1.8' if version == '1.8.9' else '1.7.10'}}}
        script = r'''
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0,'utf8'));
const t={authorization:{accessToken:input.token,minecraftProfile:{name:'Test',id:'0123456789abcdef0123456789abcdef'},type:'Xbox'},overrides:{gameDirectory:'game'},root:'downloads',version:{number:input.version}};
const r=input.metadata, n={id:input.version,assets:'fallback-assets'};
const map=vm.runInNewContext('('+input.expression+')',{t,r,n,l:'assets'});
console.log(JSON.stringify(input.args.split(' ').map(x=>Object.hasOwn(map,x)?String(map[x]):x)));
'''
        result = subprocess.run(['node', '-e', script], input=json.dumps(data),
                                text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_old_map_reproduces_unresolved_json_argument(self):
        args = self.evaluate('1.8.9', patched=False)
        self.assertEqual(args[args.index('--userProperties') + 1], '${user_properties}')

    def test_vanilla_versions_resolve_all_placeholders(self):
        for version, asset in [('1.8.9', '1.8'), ('1.7.10', '1.7.10')]:
            with self.subTest(version=version):
                args = self.evaluate(version)
                self.assertFalse(any('${' in value for value in args))
                self.assertEqual(json.loads(args[args.index('--userProperties') + 1]), {})
                self.assertEqual(args[args.index('--assetIndex') + 1], asset)
                self.assertEqual(args[args.index('--version') + 1], version)

    def test_cb_launch_arguments_are_unchanged(self):
        for token in ('0', 'test-premium-token'):
            self.assertEqual(self.evaluate('1.8.9', CB_ARGS, token=token),
                             self.evaluate('1.8.9', CB_ARGS, patched=False, token=token))

    def test_inherited_metadata_fallback(self):
        args = self.evaluate('1.8.9', metadata={'type': 'release'})
        self.assertEqual(args[args.index('--version') + 1], '1.8.9')
        self.assertEqual(args[args.index('--assetIndex') + 1], 'fallback-assets')


if __name__ == '__main__':
    unittest.main()
