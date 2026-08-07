# Calibre

Calibre is the ebook library manager in this stack. It handles ebooks, audiobooks, and comics
in English and Brazilian Portuguese, and syncs to KOReader via a wireless device connection.

---

## Installed plugins

| Plugin | Purpose |
| --- | --- |
| Goodreads | Book metadata and covers |
| Amazon.com Multiple Countries | Metadata from regional Amazon stores including amazon.com.br |
| ComicVine | Comic metadata and covers (requires API key) |
| Embed Comic Metadata | Writes CBI/CIX metadata into CBZ/CBR files |

---

## Metadata sources

### Source priority

Configure source order in **Preferences > Metadata Download**:

| Content type | Priority order |
| --- | --- |
| Ebooks | Google > Amazon > Goodreads > Open Library |
| Comics | ComicVine > Google > Open Library |

### Brazilian Portuguese books

Sources default to English editions when the language field is blank. Set the language field
before downloading metadata:

1. Select the book and press **E** to open Edit Metadata
2. Set **Language** to `Portuguese (Brazil)`
3. Set the correct Portuguese title (e.g. `A Morte de Ivan Ilitch` instead of `The Death of
   Ivan Ilyich`)
4. Then run Download Metadata

For pt-BR covers and publisher data, enable `amazon.com.br` in the Amazon Multiple Countries
plugin settings. Disable cover download from Goodreads for Portuguese books since it often
returns English edition covers.

### Comics

The ComicVine plugin setting `max_volumes` controls how many matching series it considers.
The default of `2` is too low for common characters like Superman that have many volumes.
The config is at `configs/calibre/config/.config/calibre/plugins/comicvine.json`:

```json
{
  "max_volumes": 20
}
```

When auto-matching still picks the wrong series, use **Switch to manual search** in the
Download Metadata dialog to search and select the exact ComicVine entry.

---

## Updating metadata for existing books

### Single book

Press **E** to open Edit Metadata, then click **Download metadata**.

### Multiple books

Select books, then right-click > Edit metadata > **Download metadata and covers** (Ctrl+D).
Calibre downloads in parallel and shows a review dialog before applying.

### Bulk field edits

To change language, tags, or series across many books at once without re-downloading:
select books, then right-click > Edit metadata > **Edit metadata in bulk** (Ctrl+Shift+E).

---

## KOReader wireless sync

KOReader connects to Calibre using the SMART_DEVICE_APP wireless driver. Calibre's general
"Sending books to devices" preference does not apply to this connection. The wireless device
has its own template configured separately.

### Filename template

The filename template for the KOReader wireless connection is stored in
`configs/calibre/config/.config/calibre/device_drivers_SMART_DEVICE_APP.py.json`:

```json
{
  "save_template": "{id}"
}
```

Using `{id}` alone ensures the filename never changes when metadata (title, author) is
updated. A title change with a template like `{title} - {authors}` creates a duplicate on
the device because KOReader treats the new filename as a new book.

To change this via the UI, the KOReader device must be connected wirelessly first. Once it
appears as a connected device, click the device icon in the toolbar and select
**Configure this device**.

### Sending updated metadata to KOReader

After updating metadata in Calibre, re-send the book to push the changes:

1. Connect KOReader to Calibre wirelessly (KOReader: Plugins > Calibre > Connect)
2. Select the book in Calibre
3. Right-click > **Send to device > Send to main memory**

Calibre embeds updated metadata and the cover into the file before sending.

### Duplicate books after a metadata update

If a book was sent before the `{id}` template was set, and the filename changed after a
metadata update, KOReader will show two copies. Delete the old copy from KOReader storage
(long-press > Delete > Delete from storage).

To preserve reading progress from the old copy, connect via USB first and rename the old
`.sdr` folder to match the new filename before deleting the old book file.

---

## Audiobooks

Calibre has no built-in audiobook metadata source. Options:

- **Audible content**: install the Audible plugin to fetch metadata, narrator, and covers.
- **Other sources**: use [beets](https://beets.io) to tag M4B/MP3 files before importing
  into Calibre.

---

See also: [README.md](../README.md), [docs/MAKE_COMMANDS.md](MAKE_COMMANDS.md)
