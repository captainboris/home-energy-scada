"""Exercise the actual current builder and its ZIPs, without source-path imports."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from zipfile import ZipFile


PROJECT = Path(__file__).resolve().parents[1]
ARTIFACTS = PROJECT / 'artifacts' / 'v0.6.2'


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.paths.append(attrs['src'])
        if tag == 'link' and attrs.get('href') and attrs.get('rel') in {'stylesheet', 'modulepreload'}:
            self.paths.append(attrs['href'])


class WebArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(['bash', str(PROJECT / 'source/scripts/build-current-artifacts.sh')],
                       cwd=PROJECT, check=True, capture_output=True, text=True, timeout=60)

    def test_web_zip_contains_exact_application_modules_and_no_frontend_or_collector(self):
        with ZipFile(ARTIFACTS / 'home-energy-web-v0.6.2.zip') as archive:
            self.assertIsNone(archive.testzip())
            names = {name.removeprefix('./') for name in archive.namelist()}
        self.assertEqual(names, {'index.py', 'lambda_function.py', 'range_analytics.py',
                               'history_service.py', 'telemetry_storage.py', 'analytics.py',
                               'common.py', 'storage.py'})

    def test_extracted_web_zip_import_and_entrypoint_call_are_isolated(self):
        # -I ignores PYTHONPATH/user-site/cwd. The only added application path is
        # the extracted real Web ZIP; boto3 remains a runtime/venv dependency.
        worker = '''
import json, os, pathlib, sys
from unittest.mock import patch
root = pathlib.Path(sys.argv[1]).resolve()
assert not any('/source' in item for item in sys.path)
sys.path.insert(0, str(root))
import boto3
with patch.object(boto3, 'resource', side_effect=AssertionError('Unexpected AWS IO')), \\
     patch.object(boto3, 'client', side_effect=AssertionError('Unexpected AWS IO')):
    import index
    assert pathlib.Path(index.__file__).resolve() == root / 'index.py'
    assert callable(index.web)
    result = index.web({'rawPath': '/api/health', 'requestContext': {'http': {'method': 'GET'}}}, None)
    assert result['statusCode'] == 200
    assert json.loads(result['body'])['ok'] is True
    import lambda_function, range_analytics, analytics, common, history_service, storage, telemetry_storage
    for module in [lambda_function, range_analytics, analytics, common, history_service, storage, telemetry_storage]:
        assert pathlib.Path(module.__file__).resolve().parent == root
    assert 'collector' not in sys.modules and 'fox_api' not in sys.modules
print(json.dumps({'isolated_import': 'PASS', 'index.web_health': 'PASS'}))
'''
        with tempfile.TemporaryDirectory(prefix='scada-web-zip-') as directory:
            root = Path(directory)
            with ZipFile(ARTIFACTS / 'home-energy-web-v0.6.2.zip') as archive:
                archive.extractall(root)
            env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
            env['AWS_EC2_METADATA_DISABLED'] = 'true'
            result = subprocess.run([sys.executable, '-I', '-c', worker, str(root)], cwd=root,
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # A deliberate missing-module control must fail; repository paths
            # cannot accidentally rescue the deployment ZIP.
            (root / 'range_analytics.py').unlink()
            # A fresh process does not use the first worker's imported modules.
            missing = subprocess.run([sys.executable, '-I', '-c', worker, str(root)], cwd=root,
                                     env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("No module named 'range_analytics'", missing.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]),
                         {'isolated_import': 'PASS', 'index.web_health': 'PASS'})

    def test_frontend_zip_closes_html_and_javascript_resource_dependencies(self):
        with ZipFile(ARTIFACTS / 'home-energy-frontend-v0.6.2.zip') as archive:
            self.assertIsNone(archive.testzip())
            content = {name.removeprefix('./'): archive.read(name)
                       for name in archive.namelist() if not name.endswith('/')}
        self.assertTrue({'index.html', 'daily.html', 'shared.js', 'shared.css'} <= content.keys())
        self.assertFalse(any(name.endswith('.py') for name in content))
        for page in ['index.html', 'daily.html']:
            resources = Resources(); resources.feed(content[page].decode())
            self.assertTrue(resources.paths)
            for path in resources.paths:
                self.assertIn(path.lstrip('/'), content, f'{page} -> {path}')
        # Vite bundles library code and emits relative chunk imports. Limit
        # the matches to paths so object keys such as "from" are not imports.
        for name, body in content.items():
            if not name.startswith('assets/') or not name.endswith('.js'):
                continue
            for dependency in re.findall(r'(?:\bfrom\s*|\bimport\s*\()\s*["\'](\.{1,2}/[^"\']+)["\']', body.decode()):
                resolved = str(PurePosixPath(name).parent / dependency)
                self.assertIn(resolved, content, f'{name} -> {dependency}')


if __name__ == '__main__':
    unittest.main()
