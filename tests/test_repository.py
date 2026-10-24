from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.check_site import validate_repository


class ArchiveChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / 'site').mkdir()
        (self.repo / 'site/index.html').write_text('<link href="site.css">')
        (self.repo / 'site/site.css').write_text('body {}')
        self.git('init', '-q', '-b', 'main')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *args], check=True, capture_output=True, text=True)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Add fixture files')

    def test_archive_contains_the_validated_site(self):
        self.commit()
        validate_repository(self.repo, self.repo / 'site')

    def test_unpublished_link_outside_site_is_rejected(self):
        (self.repo / 'linked-file').symlink_to('site/index.html')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'only regular files'):
            validate_repository(self.repo, self.repo / 'site')

    def test_export_ignore_cannot_remove_deployable_files(self):
        (self.repo / '.gitattributes').write_text('site/site.css export-ignore\n')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'Committed archive and site files differ'):
            validate_repository(self.repo, self.repo / 'site')

    def test_oversized_file_outside_site_is_rejected(self):
        (self.repo / 'large-file').write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        self.commit()
        with self.assertRaisesRegex(ValueError, 'archive member limit'):
            validate_repository(self.repo, self.repo / 'site')


if __name__ == '__main__':
    unittest.main()
