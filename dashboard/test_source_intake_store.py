"""Real PostgreSQL checks, opt-in only on the dedicated isolated test database."""
import os
from pathlib import Path
import uuid
import psycopg2
import pytest
from dashboard import source_intake_store as store
from etl.seasonal_bact import inspect_workbook
from etl.test_seasonal_bact import source_bytes


@pytest.fixture
def conn():
    dsn=os.getenv('SOURCE_INTAKE_TEST_DSN')
    if not dsn:
        pytest.skip('Set SOURCE_INTAKE_TEST_DSN for the isolated integration checks')
    c=psycopg2.connect(dsn)
    assert c.info.dbname=='streamwatch_source_test', 'Only the dedicated test database is permitted'
    with c.cursor() as cur:
        cur.execute(Path('db/12_source_intake.sql').read_text())
        cur.execute('TRUNCATE source_review,source_observation,source_import RESTART IDENTITY')
    c.commit()
    yield c
    c.close()


def test_source_save_is_lossless_idempotent_and_reviews_have_history(conn):
    raw=source_bytes();p=inspect_workbook(raw,'fixture.xlsx')
    batch,created=store.save(conn,p,raw);assert created
    again,created=store.save(conn,p,raw);assert not created and again==batch
    b=store.batch(conn,batch);assert b['total']==4
    with conn.cursor() as cur:
        cur.execute('SELECT original_workbook FROM source_import WHERE import_id=%s',(batch,))
        assert bytes(cur.fetchone()[0])==raw
    row=b['rows'][0]
    assert row['parameters']['E. coli']['number']=='128.1'
    store.review(conn,batch,row['id'],0,'hold','Reviewer','Check uncertain source')
    with pytest.raises(ValueError,match='Someone reviewed'):
        store.review(conn,batch,row['id'],0,'reviewed','Other','Stale screen')
    store.review(conn,batch,row['id'],1,'reviewed','Reviewer','Checked against source')
    b=store.batch(conn,batch,decision='reviewed');assert b['total']==1
    assert len(b['rows'][0]['history'])==2
    assert store.batch(conn,batch,decision='pending')['total']==3
    assert store.batch(conn,batch,sheet='IDEXX')['total']==2


def test_bad_batch_rolls_back_all_records(conn):
    raw=source_bytes();p=inspect_workbook(raw,'fixture.xlsx');p['rows'].append(p['rows'][0])
    with pytest.raises(psycopg2.IntegrityError):store.save(conn,p,raw)
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM source_import');assert cur.fetchone()[0]==0
        cur.execute('SELECT COUNT(*) FROM source_observation');assert cur.fetchone()[0]==0


def test_review_cannot_target_another_batch(conn):
    raw=source_bytes();p=inspect_workbook(raw,'fixture.xlsx');batch,_=store.save(conn,p,raw)
    row=store.batch(conn,batch)['rows'][0]
    with pytest.raises(ValueError,match='not found'):
        store.review(conn,str(uuid.uuid4()),row['id'],0,'reviewed','Reviewer','Wrong batch')
    assert store.batch(conn,batch)['decisions']=={'pending':4}


def test_http_upload_save_review_and_original_download(conn, monkeypatch):
    from dashboard import app as module
    import io
    import re
    dsn=os.environ['SOURCE_INTAKE_TEST_DSN']
    monkeypatch.setenv('READ_ONLY_MODE','false');monkeypatch.setenv('PUBLIC_DEMO_MODE','false')
    monkeypatch.setattr(module,'get_db',lambda:psycopg2.connect(dsn))
    client=module.app.test_client()
    def token(html):
        return re.search(r'name="csrf" value="([^"]+)"',html).group(1)
    home=client.get('/imports/bact/workspace');assert home.status_code==200
    csrf=token(home.get_data(as_text=True))
    raw=source_bytes()
    uploaded=client.post('/imports/bact/workspace/inspect',data={'csrf':csrf,'workbook':(io.BytesIO(raw),'source.xlsx')},content_type='multipart/form-data')
    assert uploaded.status_code==302
    preview=client.get(uploaded.location);assert preview.status_code==200
    save_url=re.search(r'action="([^"]+/save/[^"]+)"',preview.get_data(as_text=True)).group(1)
    saved=client.post(save_url,data={'csrf':csrf});assert saved.status_code==302
    page=client.get(saved.location);assert page.status_code==200
    html=page.get_data(as_text=True)
    assert '128.1' in html and '&gt; 2419.6' in html and 'Pending' in html
    assert client.get(saved.location+'/original').data==raw
    review_url=re.search(r'action="([^"]+/review/\d+)"',html).group(1)
    assert client.post(review_url,data={'revision':0,'decision':'hold','reviewer':'Test reviewer','reason':'Check source'}).status_code==400
    decision=client.post(review_url,data={'csrf':csrf,'revision':0,'decision':'hold','reviewer':'Test reviewer','reason':'Check source'})
    html=client.get(decision.location).get_data(as_text=True)
    assert 'Test reviewer' in html and 'Check source' in html and 'Review history' in html
