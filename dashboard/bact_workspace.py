"""Private seasonal source intake and durable review pages."""
from io import BytesIO
import os
from pathlib import Path
import secrets
import tempfile
import time
from uuid import UUID, uuid4

import psycopg2
from flask import abort, redirect, render_template, request, session, url_for, send_file
from werkzeug.utils import secure_filename
from etl.seasonal_bact import inspect_workbook, MAX_BYTES
from dashboard import source_intake_store as store

TTL = 30 * 60
PREVIEW_DIR = Path(tempfile.gettempdir()) / 'streamwatch_source_intake'


def csrf():
    if 'source_csrf' not in session:
        session['source_csrf'] = secrets.token_hex(32)
    return session['source_csrf']


def check_csrf():
    if not session.get('source_csrf') or not secrets.compare_digest(session['source_csrf'], request.form.get('csrf', '')):
        abort(400, 'This form expired. Reload the page before continuing.')


def preview_path(token):
    try:
        if str(UUID(token)) != token:
            abort(404)
    except ValueError:
        abort(404)
    owned = session.get('source_previews', {})
    item = owned.get(token)
    path = PREVIEW_DIR / (token + '.xlsx')
    if not item or time.time() - item['time'] > TTL or not path.is_file():
        abort(404, 'This preview expired. Upload the workbook again.')
    return path, item['filename']


class SourceUnavailable(Exception):
    pass


def register(app, get_db):
    # Session-bound form and preview ownership; use SECRET_KEY for multiworker hosting.
    if not app.secret_key:
        app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)

    def connection(readonly=True):
        try:
            conn = get_db()
        except psycopg2.Error as exc:
            raise SourceUnavailable() from exc
        try:
            conn.set_session(readonly=readonly)
            return conn
        except Exception:
            conn.close()
            raise

    @app.errorhandler(SourceUnavailable)
    def unavailable(exc):
        return render_template('bact_workspace.html', history=[], available=False, csrf=csrf(),
                               error='Saved source history is unavailable. Please try again when the database is online.'), 503

    @app.get('/imports/bact/workspace', endpoint='imports_bact_workspace')
    def home():
        history, available, error = [], False, None
        try:
            conn = connection()
            try:
                available = store.ready(conn)
                if available:
                    history = store.batches(conn)
            finally:
                conn.close()
        except (psycopg2.Error, SourceUnavailable):
            error = 'Saved source history is unavailable. You can still inspect a workbook.'
        return render_template('bact_workspace.html', history=history, available=available, error=error, csrf=csrf())

    @app.post('/imports/bact/workspace/inspect', endpoint='imports_bact_source_preview')
    def inspect():
        if request.content_length and request.content_length > MAX_BYTES + 1024 * 1024:
            abort(413)
        check_csrf()
        upload = request.files.get('workbook')
        if not upload or not upload.filename or not upload.filename.lower().endswith('.xlsx'):
            return render_template('bact_workspace.html', history=[], available=False, error='Choose a BACT and HAB .xlsx source workbook.', csrf=csrf()), 400
        data = upload.stream.read(MAX_BYTES + 1)
        filename = secure_filename(upload.filename) or 'seasonal-bact.xlsx'
        try:
            parsed = inspect_workbook(data, filename)
        except Exception:
            return render_template('bact_workspace.html', history=[], available=False,
                                   error='This file could not be inspected. Use a BACT and HAB source workbook with the expected site and date headings, under 16 MB.', csrf=csrf()), 400
        PREVIEW_DIR.mkdir(mode=0o700, exist_ok=True)
        for path in PREVIEW_DIR.glob('*.xlsx'):
            try:
                if time.time() - path.stat().st_mtime > TTL:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        owned = {k: v for k,v in session.get('source_previews', {}).items() if time.time()-v['time'] <= TTL}
        while len(owned) >= 3:
            oldest = min(owned, key=lambda k: owned[k]['time'])
            (PREVIEW_DIR / (oldest + '.xlsx')).unlink(missing_ok=True)
            del owned[oldest]
        token = str(uuid4())
        with os.fdopen(os.open(PREVIEW_DIR / (token + '.xlsx'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            f.write(data)
        owned[token] = {'time':time.time(), 'filename':filename}
        session['source_previews'] = owned
        return redirect(url_for('imports_bact_source_preview_page', token=token))

    @app.get('/imports/bact/workspace/preview/<token>', endpoint='imports_bact_source_preview_page')
    def preview(token):
        path, filename = preview_path(token)
        parsed = inspect_workbook(path.read_bytes(), filename)
        sheet = request.args.get('sheet', '')
        rows = [r for r in parsed['rows'] if not sheet or r['sheet'] == sheet]
        return render_template('bact_source_review.html', parsed=parsed, rows=rows[:50], total=len(rows),
                               token=token, batch_id=None, csrf=csrf(), error=None, sheet=sheet, decision='', page=1)

    @app.post('/imports/bact/workspace/save/<token>', endpoint='imports_bact_source_save')
    def save(token):
        check_csrf()
        path, filename = preview_path(token)
        data = path.read_bytes()
        parsed = inspect_workbook(data, filename)
        conn = connection(readonly=False)
        try:
            if not store.ready(conn):
                return render_template('bact_workspace.html', history=[], available=False, csrf=csrf(),
                                       error='Source storage is not set up yet. Your preview is unchanged.'), 503
            batch_id, created = store.save(conn, parsed, data)
        except psycopg2.Error:
            conn.rollback()
            return render_template('bact_workspace.html', history=[], available=False, csrf=csrf(),
                                   error='The workbook could not be saved. Nothing was partially imported. You can retry the preview.'), 503
        finally:
            conn.close()
        path.unlink(missing_ok=True)
        owned=session.get('source_previews', {});owned.pop(token,None);session['source_previews']=owned
        return redirect(url_for('imports_bact_source_batch', batch_id=batch_id))

    @app.get('/imports/bact/workspace/batches/<uuid:batch_id>', endpoint='imports_bact_source_batch')
    def batch(batch_id):
        sheet = request.args.get('sheet','')
        decision = request.args.get('decision','')
        try:
            page=max(1,min(int(request.args.get('page','1')),100000))
        except ValueError:
            page=1
        conn = connection()
        try:
            if not store.ready(conn):
                raise SourceUnavailable()
            result=store.batch(conn,str(batch_id),sheet,decision,page)
        finally:
            conn.close()
        if result is None:
            abort(404)
        return render_template('bact_source_review.html', parsed=result['summary'], rows=result['rows'], total=result['total'],
                               batch_id=str(batch_id), batch=result, token=None, csrf=csrf(), error=request.args.get('message'),
                               sheet=sheet, decision=decision, page=page)

    @app.post('/imports/bact/workspace/batches/<uuid:batch_id>/review/<int:observation_id>', endpoint='imports_bact_source_decision')
    def decide(batch_id, observation_id):
        check_csrf()
        try:
            revision=int(request.form.get('revision',''))
        except ValueError:
            abort(400)
        conn=connection(readonly=False)
        message='Review saved. Monitoring results have not been changed.'
        try:
            store.review(conn,str(batch_id),observation_id,revision,request.form.get('decision',''),
                         request.form.get('reviewer',''), request.form.get('reason',''))
        except ValueError as exc:
            message=str(exc)
        finally:
            conn.close()
        return redirect(url_for('imports_bact_source_batch',batch_id=batch_id,message=message,
                                sheet=request.form.get('sheet',''), decision=request.form.get('filter_decision',''),
                                page=request.form.get('page','1')))

    @app.get('/imports/bact/workspace/batches/<uuid:batch_id>/original', endpoint='imports_bact_source_original')
    def original(batch_id):
        conn=connection()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT filename,original_workbook FROM source_import WHERE import_id=%s',(str(batch_id),))
                row=cur.fetchone()
        finally:
            conn.close()
        if not row:
            abort(404)
        return send_file(BytesIO(bytes(row[1])),download_name=row[0],as_attachment=True,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
