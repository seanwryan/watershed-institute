from io import BytesIO
import os
import re
import unittest
from unittest.mock import Mock,patch
from etl.test_seasonal_bact import source_bytes


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        from dashboard import app as module
        self.module=module;self.client=module.app.test_client()
        self.mode=patch.dict(os.environ,READ_ONLY_MODE='false',PUBLIC_DEMO_MODE='false');self.mode.start();self.addCleanup(self.mode.stop)
        self.db=patch.object(module,'get_db',side_effect=AssertionError('must not connect'));self.connect=self.db.start();self.addCleanup(self.db.stop)

    def csrf(self):
        with self.client.session_transaction() as s:s['source_csrf']='test'
        return 'test'

    def upload(self):
        return self.client.post('/imports/bact/workspace/inspect',data={'csrf':self.csrf(),'workbook':(BytesIO(source_bytes()),'source.xlsx')},content_type='multipart/form-data')

    def test_preview_is_private_source_only_and_escaped(self):
        r=self.upload();self.assertEqual(r.status_code,302)
        html=self.client.get(r.location).get_data(as_text=True)
        self.assertIn('128.1',html);self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>Outlier',html)
        self.assertIn('Save source batch for review',html);self.assertIn('No limit substitutions',html)
        self.assertEqual(self.module.app.test_client().get(r.location).status_code,404)
        self.connect.assert_not_called()

    def test_readonly_can_preview_but_cannot_save_or_review(self):
        os.environ['READ_ONLY_MODE']='true'
        r=self.upload();self.assertEqual(r.status_code,302)
        html=self.client.get(r.location).get_data(as_text=True)
        self.assertNotIn('Save source batch for review',html)
        token=r.location.rsplit('/',1)[1]
        self.assertEqual(self.client.post('/imports/bact/workspace/save/'+token).status_code,403)
        self.assertEqual(self.client.post('/imports/bact/workspace/batches/00000000-0000-0000-0000-000000000000/review/1').status_code,403)
        self.connect.assert_not_called()

    def test_public_cannot_access_any_source_page_or_post(self):
        os.environ['PUBLIC_DEMO_MODE']='true'
        for path in ['/imports/bact/workspace','/imports/bact/workspace/preview/anything','/imports/bact/workspace/batches/00000000-0000-0000-0000-000000000000','/imports/bact/workspace/batches/00000000-0000-0000-0000-000000000000/original']:
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post('/imports/bact/workspace/inspect').status_code,404)
        self.assertEqual(self.client.post('/imports/bact/workspace/save/test').status_code,404)
        self.assertEqual(self.client.post('/imports/bact/workspace/batches/00000000-0000-0000-0000-000000000000/review/1').status_code,404)
        self.connect.assert_not_called()

    def test_csrf_missing_file_and_oversize_fail_before_database(self):
        self.assertEqual(self.client.post('/imports/bact/workspace/inspect').status_code,400)
        self.assertEqual(self.client.post('/imports/bact/workspace/inspect',data={'csrf':self.csrf()}).status_code,400)
        self.assertEqual(self.client.get('/imports/bact/workspace/preview/not-a-token').status_code,404)
        self.assertEqual(self.client.post('/imports/bact/workspace/inspect',data={'csrf':'test'},environ_overrides={'CONTENT_LENGTH':str(18*1024*1024)}).status_code,413)
        self.connect.assert_not_called()

    def test_all_mutations_are_classified(self):
        from dashboard.route_classification import verify_route_classification
        verify_route_classification(self.module.app)
