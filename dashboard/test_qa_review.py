"""Read-only QA investigation: filters, privacy, lineage, CSV and transactions."""
import csv
import io
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import psycopg2
import pytest
from dashboard.app import app
from dashboard import qa_review as qr
from dashboard.route_classification import verify_route_classification


@pytest.fixture(autouse=True)
def modes(monkeypatch):
    monkeypatch.setenv('READ_ONLY_MODE', 'false')
    monkeypatch.setenv('PUBLIC_DEMO_MODE', 'false')
    app.config['TESTING'] = True


def result_row(**overrides):
    row=dict(site_code='AC1',sample_date='2025-01-01',sample_code='AC1_2025-01-01',visit_id=12,
             family='chemical',record_id=7,method='CAT: Hanna',parameter='water_temp_c',
             parameter_label='Water temperature',value='0',value_display='0',unit='°C',condition='Outlier',
             flags=[{'code':'Suspect','description':'Suspected issue','notes':'<script>note</script>'}],
             detection_limit_note='@source note',visit_notes='=internal note',holding_time_flag=False,
             holding_temp_flag=False,record_label='Chemistry package 7',detail_url='/visits/12#chemical-7')
    row.update(overrides);return row


def mock_db():
    c=MagicMock();cur=c.cursor.return_value
    cur.fetchall.return_value=[]
    return c


def test_filter_validation_before_connection():
    client=app.test_client()
    with patch('dashboard.app.get_db',side_effect=AssertionError('connected')):
        for query in ['date_start=bad','date_start=2025-06-01&date_end=2024-01-01','parameter=drop_table','page=-1','page=bad','page=100001']:
            assert client.get('/qa/review?'+query).status_code==400
            assert client.get('/qa/review.csv?'+query).status_code==400
    f,p=qr.parse_filters({'parameter':'e_coli_mpn_100ml','condition':'Duplicate?','page':'2'})
    assert f['condition']=='Duplicate?' and p==2


def test_query_keeps_packages_and_record_flag_scope():
    f,_=qr.parse_filters({'site_code':"AC1' OR true --",'parameter':'water_temp_c','flag_type':'Suspect','condition':'Outlier'})
    sql,params=qr._query(f)
    assert f['site_code'] not in sql and f['site_code'] in params
    assert 'rf.result_table=r.family AND rf.result_pk=r.record_id' in sql
    assert 'UNION ALL' in sql and 'MIN(' not in sql and 'DISTINCT' not in sql
    assert 'm.key = %s' in sql and 'dc.code = %s' in sql
    assert 'LEFT JOIN LATERAL' in sql
    for field in ('chloride_mg_l','nitrate_ug_l'):
        assert 'c.'+field in sql
    no,_=qr._query(dict(flag_type='__none__',condition='__none__'))
    assert 'NOT EXISTS' in no and 'r.data_condition_id IS NULL' in no
    flagged,_=qr._query(dict(flag_type='__any__'))
    assert 'EXISTS' in flagged and 'NOT EXISTS' not in flagged


def test_query_pagination_and_export_use_same_filters():
    row=result_row();raw_keys=['family','record_id','visit_id','site_code','sample_date','sample_code','method','condition','parameter','value','detection_limit_note','visit_notes','holding_time_flag','holding_temp_flag','flags']
    cur=MagicMock();cur.description=[(key,) for key in raw_keys];cur.fetchone.return_value=(210,)
    cur.fetchall.return_value=[tuple(row[k] for k in raw_keys)]
    f,_=qr.parse_filters({'site_code':'AC1','flag_type':'Suspect'})
    page,total=qr.review_rows(cur,f,page=2)
    assert total==210 and page[0]['value_display']=='0' and page[0]['detail_url']=='/visits/12#chemical-7'
    query_args=cur.execute.call_args.args
    assert query_args[1][-2:]==[100,100]
    assert 'f.result_table=m.family AND f.result_pk=m.record_id' in query_args[0]
    qr.review_rows(cur,f,export=True)
    assert 'LIMIT' not in cur.execute.call_args.args[0]
    assert cur.execute.call_args.args[1]==query_args[1][:-2]


def test_page_and_csv_preserve_filters_escape_and_scope():
    c=mock_db();client=app.test_client();row=result_row()
    with patch('dashboard.app.get_db',return_value=c),patch('dashboard.app.qr.review_rows',return_value=([row],210)) as query:
        r=client.get('/qa/review?site_code=AC1&condition=Outlier&flag_type=Suspect&parameter=water_temp_c&page=2')
        assert r.status_code==200
        assert 'href="/qa" class="nav-link active"' in r.text
        assert '&lt;script&gt;note&lt;/script&gt;' in r.text and '<script>note</script>' not in r.text
        assert 'data-sort-value="0"' in r.text and '/visits/12#chemical-7' in r.text
        assert 'page=3' in r.text and 'page=1' in r.text
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):super().__init__();self.links=[]
            def handle_starttag(self,tag,attrs):
                if tag=='a':self.links.append(dict(attrs).get('href',''))
        links=Links();links.feed(r.text)
        url=next(x for x in links.links if x.startswith('/qa/review.csv?'))
        assert parse_qs(urlsplit(url).query)['condition']==['Outlier']
        assert 'page=' not in url
        page_filter=query.call_args.args[1]
        r=client.get(url);assert r.status_code==200
        assert query.call_args.args[1]==page_filter and query.call_args.kwargs['export']
        parsed=list(csv.reader(io.StringIO(r.text)));assert len(parsed)==2
        assert parsed[1][8]=='0'
        assert parsed[1][13]=="'@source note" and parsed[1][14]=="'=internal note"
        c.set_session.assert_called_with(readonly=True,isolation_level='REPEATABLE READ')
        c.commit.assert_not_called()


def test_csv_negative_numbers_and_missing_conditions():
    cells=list(qr.csv_cells([result_row(value='-2.5',condition=None)]))[0]
    assert cells[8]=='-2.5' and cells[10]==''
    assert dict((k,u) for k,_,u in qr.PARAMETERS)['nitrate_ug_l']=='Unresolved'


def test_modes_and_no_write_routes(monkeypatch):
    client=app.test_client()
    monkeypatch.setenv('READ_ONLY_MODE','true')
    with patch('dashboard.app.get_db',return_value=mock_db()),patch('dashboard.app.qr.review_rows',return_value=([],0)):
        assert client.get('/qa/review').status_code==200
        assert client.get('/qa/review.csv').status_code==200
        assert 'Review results &amp; notes' in client.get('/qa').text
    monkeypatch.setenv('PUBLIC_DEMO_MODE','true')
    for readonly in ('true','false'):
        monkeypatch.setenv('READ_ONLY_MODE',readonly)
        with patch('dashboard.app.get_db',side_effect=AssertionError('private data accessed')):
            for path in ['/qa/review','/qa/review?site_code=AC1','/qa/review.csv?condition=Outlier']:
                assert client.get(path).status_code==404
            assert 'Review results &amp; notes' not in client.get('/qa').text
    assert client.post('/qa/review').status_code==405
    assert client.post('/qa/review.csv').status_code==405
    verify_route_classification(app)


def test_connection_failure_and_readonly_setup_fail_closed():
    client=app.test_client();c=mock_db()
    c.set_session.side_effect=psycopg2.OperationalError('unavailable')
    with patch('dashboard.app.get_db',return_value=c),patch('dashboard.app.qr.review_rows') as query:
        assert client.get('/qa/review').status_code==503
        assert client.get('/qa/review.csv').status_code==503
        query.assert_not_called();c.close.assert_called()
