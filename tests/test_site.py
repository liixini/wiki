from pathlib import Path
import tempfile
import unittest

from tools.check_site import validate


class SiteChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name) / 'site'
        self.site.mkdir()

    def write(self, name, text):
        path = self.site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_nested_pages_assets_and_external_links(self):
        self.write('index.html', '<a href="guide/">Guide</a><a href="https://example.com/">External</a>')
        self.write('guide/index.html', '<link href="../site.css"><img src="/image.svg">')
        self.write('site.css', 'body { background: url("image.svg") }')
        self.write('image.svg', '<svg/>')
        self.assertEqual(validate(self.site)[0], 4)

    def test_missing_stylesheet_fails(self):
        self.write('index.html', '<link href="missing.css">')
        self.write('existing.css', 'body {}')
        with self.assertRaisesRegex(ValueError, 'missing local file'):
            validate(self.site)

    def test_missing_css_image_fails(self):
        self.write('index.html', '<link href="site.css">')
        self.write('site.css', 'body { background: url(missing.png) }')
        with self.assertRaisesRegex(ValueError, 'missing local file'):
            validate(self.site)

    def test_encoded_link_cannot_leave_site(self):
        self.write('index.html', '<a href="%2e%2e/private.txt">Private</a>')
        self.write('site.css', 'body {}')
        with self.assertRaisesRegex(ValueError, 'leaves the site'):
            validate(self.site)

    def test_symlink_to_outside_is_rejected(self):
        self.write('index.html', '<a href="secret.txt">Link</a>')
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('not published')
        (self.site / 'secret.txt').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            validate(self.site)

    def test_hidden_file_is_rejected(self):
        self.write('index.html', '<h1>Site</h1>')
        self.write('.env', 'not published')
        with self.assertRaisesRegex(ValueError, 'Hidden paths'):
            validate(self.site)

    def test_entry_page_is_required(self):
        self.write('site.css', 'body {}')
        with self.assertRaisesRegex(ValueError, 'index.html is required'):
            validate(self.site)

    def test_filename_rules_match_deployment(self):
        self.write('index.html', '<h1>Site</h1>')
        self.write('page name.html', '<h1>Page</h1>')
        with self.assertRaisesRegex(ValueError, 'Unsupported filename'):
            validate(self.site)

    def test_index_only_site_is_rejected(self):
        self.write('index.html', '<h1>Site</h1>')
        with self.assertRaisesRegex(ValueError, 'at least one asset'):
            validate(self.site)


if __name__ == '__main__':
    unittest.main()
