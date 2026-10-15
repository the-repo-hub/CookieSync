"""Проверки состава и воспроизводимости release-архивов во временном каталоге."""

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile

import build_extension


class ExtensionReleaseTests(unittest.TestCase):
    """Целостность ресурсов и браузерные различия неподписанных release-пакетов."""

    def test_release_packages_are_complete_reproducible_and_browser_specific(self):
        """Проверяет ссылки манифеста, PNG, стабильность ZIP и соответствие SHA256SUMS."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = build_extension.build(release=True, output=output)
            originals = {path.name: path.read_bytes() for path in paths}
            for path in paths:
                with ZipFile(path) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(set(archive.namelist()), {'manifest.json', *build_extension.PACKAGE_FILES})
                    manifest = json.loads(archive.read('manifest.json'))
                    for size, name in manifest['icons'].items():
                        image = archive.read(name)
                        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
                        self.assertEqual(struct.unpack('>II', image[16:24]), (int(size), int(size)))
                    for content_script in manifest['content_scripts']:
                        for name in content_script['js']:
                            self.assertIn(name, archive.namelist())
                    for name in manifest['action']['default_icon'].values():
                        self.assertIn(name, archive.namelist())
                    self.assertIn(manifest['action']['default_popup'], archive.namelist())
                    if 'firefox' in path.name:
                        self.assertNotIn('service_worker', manifest['background'])
                        self.assertNotIn('minimum_chrome_version', manifest)
                        gecko = manifest['browser_specific_settings']['gecko']
                        self.assertEqual(gecko['id'], 'cookiesync@extension')
                        self.assertEqual(gecko['strict_min_version'], '140.0')
                        self.assertEqual(gecko['data_collection_permissions']['required'], ['authenticationInfo'])
                        for name in manifest['background']['scripts']:
                            self.assertIn(name, archive.namelist())
                    else:
                        self.assertEqual(manifest['background'], {'service_worker': 'background.js'})
                        self.assertNotIn('browser_specific_settings', manifest)
            build_extension.build(release=True, output=output)
            for path in paths:
                self.assertEqual(path.read_bytes(), originals[path.name])
            for line in (output / 'release' / 'SHA256SUMS').read_text().splitlines():
                digest, name = line.split('  ')
                self.assertEqual(digest, hashlib.sha256(originals[name]).hexdigest())


if __name__ == '__main__':
    unittest.main()
