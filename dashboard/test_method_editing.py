"""Reference editing tests; no monitoring database writes."""
import os
import re
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from dashboard.app import app, _method_signer
from dashboard.methods_store import baseline_rows, validate_form, save_revision, read_rows
from dashboard.route_classification import verify_route_classification


def connection():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    cur.fetchone.return_value = (0,)
    return conn, cur


@pytest.fixture(autouse=True)
def normal_mode(monkeypatch):
    monkeypatch.setenv("READ_ONLY_MODE", "false")
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "false")
    app.config["TESTING"] = True


def test_baseline_identity_and_validation():
    rows = baseline_rows()
    assert len({r['reference_id'] for r in rows}) == len(rows)
    assert all(r['source_reference'] and r['revision'] == 0 for r in rows)
    _, _, _, error = validate_form({"parameter": "pH", "program": "CAT"})
    assert error
    assert not validate_form(dict(parameter="pH", program="CAT", source_reference="Staff protocol", change_note="Updated instrument"))[-1]


def test_overlay_and_no_lookup_writes():
    conn, cur = connection()
    row = baseline_rows()[0]
    cur.fetchall.return_value = [(row['reference_id'], 1, {"parameter": "Updated"}, "Protocol")]
    rows = read_rows(conn)
    assert rows[0]['parameter'] == 'Updated'
    assert rows[0]['source_reference'] == 'Protocol'
    assert save_revision(conn, row['reference_id'], 0, {}, "Protocol", "Change")
    sql = ' '.join(c.args[0] for c in cur.execute.call_args_list)
    assert 'method_reference_revision' in sql
    assert 'chemical' not in sql and 'lst_method' not in sql
    cur.fetchone.return_value = (1,)
    cur.reset_mock()
    assert not save_revision(conn, row['reference_id'], 0, {}, "Protocol", "Change")
    assert not any('INSERT' in c.args[0] for c in cur.execute.call_args_list)


def test_get_post_conflict_and_invalid_token():
    conn, cur = connection()
    client = app.test_client()
    key = baseline_rows()[0]['reference_id']
    with patch('dashboard.app.get_db', return_value=conn):
        response = client.get('/methods/' + key + '/edit')
        assert response.status_code == 200
        token = re.search(r'name="edit_token" value="([^"]+)"', response.text)[1]
        form = dict(edit_token=token, parameter='pH', program='CAT', source_reference='Protocol', change_note='Updated')
        assert client.post('/methods/' + key + '/edit', data=form).status_code == 302
        conn.commit.assert_called_once()
        cur.fetchone.return_value = (1,)
        assert client.post('/methods/' + key + '/edit', data=form).status_code == 409
        assert conn.commit.call_count == 1
        form['edit_token'] = 'tampered'
        assert client.post('/methods/' + key + '/edit', data=form).status_code == 400
        assert conn.commit.call_count == 1


def test_new_validation_and_escaping():
    conn, cur = connection()
    client = app.test_client()
    with patch('dashboard.app.get_db', return_value=conn):
        response = client.get('/methods/new')
        token = re.search(r'name="edit_token" value="([^"]+)"', response.text)[1]
        assert client.post('/methods/new', data=dict(edit_token=token, parameter='<script>')).status_code == 400
        conn.commit.assert_not_called()
        response = client.post('/methods/new', data=dict(edit_token=token, parameter='New', program='CAT', source_reference='Protocol', change_note='New reference'))
        assert response.status_code == 302
        assert any('INSERT INTO method_reference_revision' in c.args[0] for c in cur.execute.call_args_list)
        assert client.get('/methods/missing/edit').status_code == 404


def test_modes_and_missing_setup(monkeypatch):
    client = app.test_client()
    for readonly, public, expected in [('true', 'false', 403), ('false', 'true', 404), ('true', 'true', 403)]:
        monkeypatch.setenv('READ_ONLY_MODE', readonly)
        monkeypatch.setenv('PUBLIC_DEMO_MODE', public)
        with patch('dashboard.app.get_db', side_effect=AssertionError('database reached')):
            for path in ['/methods/new', '/methods/source-test/edit']:
                assert client.get(path).status_code == expected
                assert client.post(path).status_code == expected
    monkeypatch.setenv('READ_ONLY_MODE', 'false')
    monkeypatch.setenv('PUBLIC_DEMO_MODE', 'false')
    conn, cur = connection()
    cur.execute.side_effect = psycopg2.errors.UndefinedTable('not installed')
    with patch('dashboard.app.get_db', return_value=conn):
        response = client.get('/methods')
        assert response.status_code == 200
        assert 'Add reference' not in response.text
        assert client.get('/methods/new').status_code == 503
    assert verify_route_classification(app)


def test_methods_links_and_modes(monkeypatch):
    conn, _ = connection()
    client = app.test_client()
    with patch('dashboard.app.get_db', return_value=conn):
        assert 'Add reference' in client.get('/methods').text
        for mode in ['READ_ONLY_MODE', 'PUBLIC_DEMO_MODE']:
            monkeypatch.setenv(mode, 'true')
            assert 'Add reference' not in client.get('/methods').text
            monkeypatch.setenv(mode, 'false')
