"""Build browser-specific extension ZIPs using only the Python standard library."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
EXTENSION = ROOT / 'extension'
OUTPUT = ROOT / 'build'
PACKAGE_FILES = (
    'authentication.js',
    'background.js',
    'browser-polyfill.min.js',
    'icon16.png',
    'icon48.png',
    'icon128.png',
    'logic.js',
    'sync-context.js',
    'popup.html',
    'popup.js',
    'INSTALL_RU.txt',
)


def write_archive(path: Path, contents: dict[str, bytes]) -> None:
    """Write contents (archive name -> bytes) to path with reproducible metadata.

    Entries are sorted and use fixed timestamps and permissions. The parent
    directory must exist; an existing archive is replaced.
    """
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(contents.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content)


def build(release: bool = False, output: Path = OUTPUT) -> list[Path]:
    """Build Chromium and Firefox ZIPs and write their SHA256SUMS file.

    Args:
        release: Use distribution instructions and store-specific manifests;
            archives remain unsigned and are placed in output/release.
        output: Base output directory, created together with missing parents.

    Returns:
        Paths of the Chromium and Firefox archives, in that order.

    Raises:
        ValueError: The source manifest version is not a valid browser version.
        OSError: A required source cannot be read or an output cannot be written.
    """
    source_manifest = json.loads((EXTENSION / 'manifest.json').read_text(encoding='utf-8'))
    # Read the explicit file list before creating archives: exclude tests and local data.
    contents = {name: (EXTENSION / name).read_bytes() for name in PACKAGE_FILES}
    version = source_manifest['version']
    if not isinstance(version, str):
        raise ValueError('Expected a version string in manifest.json')
    parts = version.split('.')
    if (
        not 1 <= len(parts) <= 4
        or any(not part.isascii() or not part.isdecimal() or len(part) > 5 for part in parts)
        or any(int(part) > 65535 or str(int(part)) != part for part in parts)
        or not any(int(part) for part in parts)
    ):
        raise ValueError('Expected 1-4 version numbers in 0..65535 without leading zeros')
    if release:
        output = output / 'release'
        contents['INSTALL_RU.txt'] = (EXTENSION / 'INSTALL_RELEASE_RU.txt').read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    archives = []

    for browser in ('chromium', 'firefox'):
        manifest = copy.deepcopy(source_manifest)
        if browser == 'chromium':
            manifest['background'].pop('scripts', None)
            manifest.pop('browser_specific_settings', None)
        else:
            manifest['background'].pop('service_worker', None)
            manifest.pop('minimum_chrome_version', None)
            if release:
                # Required for new AMO submissions; this API is supported from 140.
                gecko = manifest['browser_specific_settings']['gecko']
                gecko['strict_min_version'] = '140.0'
                gecko['data_collection_permissions'] = {'required': ['authenticationInfo']}

        suffix = {'chromium': 'chrome', 'firefox': 'firefox-unsigned'}[browser] if release else browser
        archive_path = output / f'CookieSync-{version}-{suffix}.zip'
        packaged = {
            **contents,
            'manifest.json': (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
        }
        write_archive(archive_path, packaged)
        archives.append(archive_path)
        print(archive_path)
    checksums = ''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in archives
    )
    (output / 'SHA256SUMS').write_text(checksums, encoding='utf-8')
    return archives


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', action='store_true', help='Build unsigned distribution packages in build/release')
    parser.add_argument('--output', type=Path, default=OUTPUT, help='Output directory (default: build)')
    args = parser.parse_args()
    build(release=args.release, output=args.output)
