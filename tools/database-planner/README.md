# StreamWatch data planning desk

Open `index.html` in a browser. It is a standalone page with no dependencies or database connection.

- **Database structure:** Review 15 proposed domains, fields, requirements, relationships, candidate sources and cleaning questions. Include/exclude fields, add a field, choose release scope and keep notes.
- **Source decisions:** Assign a proposed role to each of 17 data files and the R scoring script; record overlap and source questions.
- **Cleaning & open rules:** Distinguish documented conventions, verification work and unresolved policy.

The page saves planning state in browser local storage if available. Storage belongs to that browser and origin, so notes from a localhost preview may not appear when opening the file directly. Use **Export plan** to download a portable JSON snapshot, then **Open plan** to restore it elsewhere. Opening a plan replaces the current browser draft after confirmation. Nothing is sent to a server.

Optional local preview, from this directory:

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

Then visit http://127.0.0.1:8765. Stop the server when finished.

All supplied table structures and source roles are discussion proposals based on the source review. Several grouped concepts need separate related tables in an eventual physical schema. This prototype does not generate SQL, clean raw files, import records, or certify scientific rules.
