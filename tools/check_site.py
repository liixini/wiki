import argparse
import gzip
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from urllib.parse import unquote, urlsplit

MAX_FILES = 1000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_DATA = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2048
PATH_PART = re.compile(r'[A-Za-z0-9_.-]+\Z')


class References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {'href', 'src', 'poster'} and value:
                self.urls.append(value)


def check_reference(root, source, value):
    url = urlsplit(value)
    if url.scheme or url.netloc or not url.path:
        return
    path = unquote(url.path)
    target = root / path.lstrip('/') if path.startswith('/') else source.parent / path
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f'{source.relative_to(root)}: link leaves the site: {value}')
    if resolved.is_dir():
        resolved /= 'index.html'
    if not resolved.is_file():
        raise ValueError(f'{source.relative_to(root)}: missing local file: {value}')


def validate(site):
    if Path(site).is_symlink():
        raise ValueError('Symlinks are not deployable: site')
    root = Path(site).resolve(strict=True)
    if not (root / 'index.html').is_file():
        raise ValueError('site/index.html is required')
    files = []
    total = 0
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if len(str(relative)) > 240 or any(not PATH_PART.fullmatch(part) for part in relative.parts):
            raise ValueError(f'Unsupported filename: {relative}')
        if path.is_symlink():
            raise ValueError(f'Symlinks are not deployable: {relative}')
        if any(part.startswith('.') for part in relative.parts):
            raise ValueError(f'Hidden paths are not deployable: {relative}')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f'Only regular files are deployable: {relative}')
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f'File is too large: {relative}')
        total += size
        files.append(path)
        if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
            raise ValueError('Site exceeds the deployment size limit')
    if len(files) < 2:
        raise ValueError('The site requires index.html and at least one asset')
    for path in files:
        urls = []
        if path.suffix.lower() in {'.html', '.htm'}:
            parser = References()
            parser.feed(path.read_text(encoding='utf-8'))
            urls = parser.urls
        elif path.suffix.lower() == '.css':
            urls = [match[1] for match in re.findall(r'url\(\s*([\x22\x27]?)(.*?)\1\s*\)', path.read_text(encoding='utf-8'))]
        for url in urls:
            check_reference(root, path, url)
    return len(files), total


def validate_repository(repository, site):
    root = Path(repository).resolve(strict=True)
    site = Path(site).resolve(strict=True)
    if site != root / 'site':
        raise ValueError('Published files must be in the repository site/ directory')
    expected = {str(path.relative_to(site)) for path in site.rglob('*') if path.is_file()}
    with tempfile.TemporaryFile() as archive, tempfile.TemporaryFile() as expanded:
        subprocess.run(['git', '-C', str(root), 'archive', '--format=tar.gz', '--prefix=source/', 'HEAD'], stdout=archive, check=True, timeout=30)
        if archive.tell() > MAX_ARCHIVE_BYTES:
            raise ValueError('Repository archive exceeds 16 MiB')
        archive.seek(0)
        size = 0
        with gzip.GzipFile(fileobj=archive, mode='rb') as compressed:
            while chunk := compressed.read(65536):
                size += len(chunk)
                if size > MAX_ARCHIVE_DATA + MAX_ARCHIVE_ENTRIES * 2048:
                    raise ValueError('Repository archive expansion limit')
                expanded.write(chunk)
        expanded.seek(0)
        seen = set()
        published = set()
        total = 0
        with tarfile.open(fileobj=expanded, mode='r|') as tar:
            for member in tar:
                name = member.name.rstrip('/')
                parts = name.split('/')
                if name in seen or name.startswith('/') or '\\' in name or any(part in {'', '.', '..'} for part in parts):
                    raise ValueError('Unsafe repository archive path')
                seen.add(name)
                total += member.size
                if len(seen) > MAX_ARCHIVE_ENTRIES or member.size > MAX_FILE_BYTES or total > MAX_ARCHIVE_DATA:
                    raise ValueError('Repository archive member limit')
                if not (member.isdir() or member.isfile()) or member.issym() or member.islnk():
                    raise ValueError('Repository archive must contain only regular files and directories')
                if parts[0] != 'source':
                    raise ValueError('Unexpected repository archive root')
                if len(parts) > 2 and parts[1] == 'site' and member.isfile():
                    published.add('/'.join(parts[2:]))
        if published != expected:
            raise ValueError('Committed archive and site files differ; check tracked files and export-ignore rules')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('site', nargs='?', default='site')
    parser.add_argument('--repository')
    args = parser.parse_args()
    try:
        count, size = validate(args.site)
        if args.repository:
            validate_repository(args.repository, args.site)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'Validated {count} files ({size} bytes)')
