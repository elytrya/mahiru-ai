from __future__ import annotations
import asyncio
import io
import re
import time
import uuid
import zipfile
from html import escape as _html_escape
from pathlib import Path
from typing import Any

from methods.base import Tool
from methods.lib.client import (api_get, download_image, download_bytes,
                                image_servers, LibError)
from methods.lib.meta import fetch_title_meta
from config import settings
from utils.logger import log

_KINDS = {"manga", "ranobe", "hentai"}

_MAX_PAGES_TOTAL     = 4000
_MAX_CHAPTERS_MANGA  = 80
_MAX_CHAPTERS_RANOBE = 2000
_PAGE_CONCURRENCY    = 5

_CHAPTER_TIMEOUT = 90.0
_CHAPTER_TRIES   = 6

_SANITIZE = re.compile(r"[^\w\-. а-яёА-ЯЁ]+", flags=re.UNICODE)

def max_chapters(kind: str) -> int:
    return _MAX_CHAPTERS_RANOBE if kind == "ranobe" else _MAX_CHAPTERS_MANGA

def _safe(name: str, fallback: str = "chapter") -> str:
    name = (name or fallback).strip()
    name = _SANITIZE.sub("_", name)[:80]
    return name or fallback

def _download_dir() -> Path:
    d = Path(getattr(settings, "DOWNLOAD_DIR", "./downloads"))
    d.mkdir(parents=True, exist_ok=True)
    return d

async def _load_meta_and_cover(kind: str, slug: str) -> tuple[dict | None, bytes | None]:
    meta = None
    try:
        meta = await fetch_title_meta(kind, slug)
    except Exception as e:
        log.debug(f"meta fetch failed for {slug}: {e}")
    cover_bytes = None
    if meta and meta.get("cover"):
        try:
            cover_bytes = await download_bytes(meta["cover"])
        except Exception as e:
            log.debug(f"cover download failed for {slug}: {e}")
    return meta, cover_bytes

def _txt_with_header(title: str, meta: dict | None, parts: list[str]) -> str:
    head = [title]
    if meta:
        if meta.get("eng_name"):
            head.append(meta["eng_name"])
        line = " · ".join(str(x) for x in [meta.get("type"), meta.get("year"),
                                           meta.get("status")] if x)
        if line:
            head.append(line)
        if meta.get("authors"):
            head.append("Авторы: " + ", ".join(meta["authors"]))
        if meta.get("teams"):
            head.append("Перевод: " + ", ".join(meta["teams"]))
        if meta.get("genres"):
            head.append("Жанры: " + ", ".join(meta["genres"]))
        if meta.get("summary"):
            head.append("\n" + meta["summary"])
    return "\n".join(head) + "\n\n" + ("=" * 40) + "\n\n" + "\n\n".join(parts)

async def _api_get_retry(kind: str, path: str, params: dict | None = None,
                         timeout: float = _CHAPTER_TIMEOUT,
                         tries: int = _CHAPTER_TRIES) -> dict[str, Any]:
    import random as _rnd
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return await api_get(kind, path, params=params, timeout=timeout)
        except LibError as e:
            last = e
            status = getattr(e, "status", None)
            low = str(e).lower()
            if status in (401, 403, 404) or any(c in low for c in (" 401", " 403", " 404")):
                raise
            if attempt < tries:
                is_429 = status == 429 or " 429" in low
                if is_429:
                    ra = getattr(e, "retry_after", None)
                    base = ra if (ra and ra > 0) else 6.0 * attempt
                    delay = min(60.0, base) + _rnd.uniform(0.5, 2.0)
                    log.warning(f"⏸ 429 rate limit {path} ({params}) → торможу на {delay:.1f}с "
                                f"(попытка {attempt}/{tries})")
                else:
                    delay = min(12.0, 1.5 * (2 ** (attempt - 1))) + _rnd.uniform(0, 1.2)
                    log.warning(f"retry {attempt}/{tries} {path} ({params}): {e!r} → пауза {delay:.1f}с")
                await asyncio.sleep(delay)
            else:
                log.warning(f"retry {attempt}/{tries} исчерпан {path} ({params}): {e!r}")
    raise last or LibError("api_get failed")

_PAGE_TRIES = 5

async def _dl_page(sem: asyncio.Semaphore, url: str,
                   servers: list[str] | None = None,
                   tries: int = _PAGE_TRIES) -> bytes | None:
    import random as _rnd
    async with sem:
        last: Exception | None = None
        for attempt in range(1, tries + 1):
            try:
                return await download_image(url, timeout=45.0, servers=servers)
            except LibError as e:
                last = e
                if attempt < tries:
                    delay = min(6.0, 0.7 * (2 ** (attempt - 1))) + _rnd.uniform(0, 0.5)
                    await asyncio.sleep(delay)
        log.warning(f"page download failed after {tries} tries: {last}")
        return None

def _img_ext(buf: bytes) -> str:
    if buf[:3] == b"\xff\xd8\xff":
        return "jpg"
    if buf[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if buf[:4] == b"RIFF" and buf[8:12] == b"WEBP":
        return "webp"
    if buf[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "jpg"

def _images_to_pdf(images: list[bytes], out_path: Path) -> None:
    from PIL import Image
    frames = []
    for buf in images:
        if not buf:
            continue
        try:
            im = Image.open(io.BytesIO(buf))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            frames.append(im)
        except Exception as e:
            log.warning(f"skip corrupted image: {e}")
    if not frames:
        raise LibError("нет валидных страниц для PDF")
    frames[0].save(str(out_path), "PDF", save_all=True, append_images=frames[1:])

def _comicinfo_xml(meta: dict[str, Any], page_count: int) -> str:
    esc = _html_escape
    genres = ", ".join(list(meta.get("genres") or []) + list(meta.get("tags") or []))
    fields: list[str] = [f"<Title>{esc(meta.get('name') or '')}</Title>",
                         f"<Series>{esc(meta.get('name') or '')}</Series>"]
    if meta.get("summary"):
        fields.append(f"<Summary>{esc(meta['summary'])}</Summary>")
    year = str(meta.get("year") or "")
    if year[:4].isdigit():
        fields.append(f"<Year>{esc(year[:4])}</Year>")
    if meta.get("authors"):
        fields.append(f"<Writer>{esc(', '.join(meta['authors']))}</Writer>")
    if meta.get("artists"):
        fields.append(f"<Penciller>{esc(', '.join(meta['artists']))}</Penciller>")
    if meta.get("teams"):
        fields.append(f"<Translator>{esc(', '.join(meta['teams']))}</Translator>")
    if meta.get("publisher"):
        fields.append(f"<Publisher>{esc(', '.join(meta['publisher']))}</Publisher>")
    if genres:
        fields.append(f"<Genre>{esc(genres)}</Genre>")
    if meta.get("eng_name"):
        fields.append(f"<AlternateSeries>{esc(meta['eng_name'])}</AlternateSeries>")
    if meta.get("age"):
        fields.append(f"<AgeRating>{esc(meta['age'])}</AgeRating>")
    if meta.get("slug"):
        fields.append("<Web>https://mangalib.org/ru/manga/" + esc(meta["slug"]) + "</Web>")
    fields.append(f"<PageCount>{page_count}</PageCount>")
    fields.append("<LanguageISO>ru</LanguageISO>")
    fields.append("<Manga>Yes</Manga>")
    body = "\n  ".join(fields)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n  '
            + body + "\n</ComicInfo>\n")

def _images_to_cbz(pages: list[tuple[str, bytes]], out_path: Path,
                   meta: dict[str, Any] | None = None,
                   cover: bytes | None = None) -> None:
    if not pages:
        raise LibError("нет страниц для CBZ")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as z:
        if cover:
            z.writestr(f"0000_cover.{_img_ext(cover)}", cover)
        for name, buf in pages:
            if not buf:
                continue
            z.writestr(f"{name}.{_img_ext(buf)}", buf)
        if meta:
            z.writestr("ComicInfo.xml",
                       _comicinfo_xml(meta, len(pages) + (1 if cover else 0)))

_CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '  <rootfiles>\n'
    '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
    '  </rootfiles>\n'
    '</container>\n'
)

def _text_to_xhtml_body(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paras:
        paras = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = []
    for p in paras:
        p = _html_escape(p).replace("\n", "<br/>")
        out.append(f"<p>{p}</p>")
    return "\n".join(out) or "<p></p>"

def _chapter_xhtml(heading: str, body_html: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>\n'
        f'<title>{_html_escape(heading)}</title>\n'
        '<meta charset="utf-8"/></head><body>\n'
        f'<h2>{_html_escape(heading)}</h2>\n'
        f'{body_html}\n'
        '</body></html>\n'
    )

def _epub_media_type(ext: str) -> str:
    return {"jpg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")

def _build_epub(out_path: Path, title: str, author: str,
                chapters: list[tuple[str, str]],
                meta: dict[str, Any] | None = None,
                cover: bytes | None = None) -> None:
    if not chapters:
        raise LibError("нет глав для EPUB")
    meta = meta or {}
    esc = _html_escape
    book_id = "urn:uuid:" + str(uuid.uuid4())
    manifest, spine, navpoints, navlis = [], [], [], []
    cover_manifest = cover_spine = cover_meta = ""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER_XML)
        if cover:
            cext = _img_ext(cover)
            z.writestr(f"OEBPS/cover.{cext}", cover)
            z.writestr("OEBPS/cover.xhtml", (
                '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<title>Обложка</title><meta charset="utf-8"/></head>'
                '<body style="margin:0;text-align:center">'
                f'<img src="cover.{cext}" alt="cover" style="max-width:100%"/>'
                '</body></html>\n'))
            cover_manifest = (
                f'<item id="cover-img" href="cover.{cext}" '
                f'media-type="{_epub_media_type(cext)}" properties="cover-image"/>\n'
                '<item id="coverpage" href="cover.xhtml" '
                'media-type="application/xhtml+xml"/>\n')
            cover_spine = '<itemref idref="coverpage"/>\n'
            cover_meta = '<meta name="cover" content="cover-img"/>\n'
        for i, (heading, body) in enumerate(chapters, 1):
            fname = f"chap_{i:04d}.xhtml"
            z.writestr(f"OEBPS/{fname}", _chapter_xhtml(heading, body))
            manifest.append(
                f'<item id="chap{i}" href="{fname}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="chap{i}"/>')
            navpoints.append(
                f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>'
                f'{_html_escape(heading)}</text></navLabel>'
                f'<content src="{fname}"/></navPoint>')
            navlis.append(f'<li><a href="{fname}">{_html_escape(heading)}</a></li>')
        md = [f'<dc:identifier id="bookid">{book_id}</dc:identifier>',
              f'<dc:title>{esc(title)}</dc:title>']
        for a in (meta.get("authors") or ([author] if author else [])):
            md.append(f'<dc:creator>{esc(a)}</dc:creator>')
        for artist in (meta.get("artists") or []):
            md.append(f'<dc:contributor>{esc(artist)} (иллюстрации)</dc:contributor>')
        for team in (meta.get("teams") or []):
            md.append(f'<dc:contributor>{esc(team)} (перевод)</dc:contributor>')
        if meta.get("summary"):
            md.append(f'<dc:description>{esc(meta["summary"])}</dc:description>')
        for g in list(meta.get("genres") or []) + list(meta.get("tags") or []):
            md.append(f'<dc:subject>{esc(g)}</dc:subject>')
        for p in (meta.get("publisher") or []):
            md.append(f'<dc:publisher>{esc(p)}</dc:publisher>')
        if meta.get("year") and str(meta.get("year"))[:4].isdigit():
            md.append(f'<dc:date>{esc(str(meta["year"])[:4])}</dc:date>')
        if meta.get("eng_name"):
            md.append(f'<dc:title id="alt-title">{esc(meta["eng_name"])}</dc:title>')
        md.append('<dc:language>ru</dc:language>')
        md.append(f'<meta property="dcterms:modified">'
                  f'{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta>')
        opf = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid">\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            + "\n".join(md) + "\n" + cover_meta +
            '</metadata>\n<manifest>\n'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
            '<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>\n'
            + cover_manifest
            + "\n".join(manifest) +
            '\n</manifest>\n<spine toc="ncx">\n'
            + cover_spine
            + "\n".join(spine) +
            '\n</spine>\n</package>\n'
        )
        z.writestr("OEBPS/content.opf", opf)
        ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            f'<head><meta name="dtb:uid" content="{book_id}"/></head>\n'
            f'<docTitle><text>{_html_escape(title)}</text></docTitle>\n'
            '<navMap>\n' + "\n".join(navpoints) + '\n</navMap>\n</ncx>\n'
        )
        z.writestr("OEBPS/toc.ncx", ncx)
        nav = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
            '<title>Оглавление</title><meta charset="utf-8"/></head><body>\n'
            '<nav epub:type="toc"><h1>Оглавление</h1><ol>\n'
            + "\n".join(navlis) +
            '\n</ol></nav>\n</body></html>\n'
        )
        z.writestr("OEBPS/nav.xhtml", nav)

class LibDownloadTool(Tool):
    name = "lib_download"
    description = (
        "Скачать главы манги/хентая (CBZ/PDF) или ранобэ (EPUB/TXT) с MangaLib/RanobeLib/HentaiLib. "
        "Обычно вызывается не тулом, а кнопочным флоу (handlers/lib_download.py)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "slug_url тайтла из lib_search"},
            "kind": {"type": "string", "enum": ["manga", "ranobe", "hentai"], "default": "manga"},
            "chapter_from": {"type": "number", "default": 1},
            "chapter_to":   {"type": "number", "default": 1},
            "format": {"type": "string", "enum": ["cbz", "pdf", "epub", "txt"]},
        },
        "required": ["slug"],
    }

    async def run(self, args: dict[str, Any], *, session=None, user_id: int = 0) -> dict[str, Any]:
        slug = str(args.get("slug") or "").strip()
        kind = str(args.get("kind") or "manga").lower()
        fmt  = str(args.get("format") or "").lower()
        chapter_from = args.get("chapter_from", 1)
        chapter_to   = args.get("chapter_to", chapter_from)
        if kind not in _KINDS:
            return {"error": "kind должен быть manga/ranobe/hentai"}
        if not slug:
            return {"error": "slug пуст"}
        try:
            cf = float(chapter_from)
            ct = float(chapter_to) if chapter_to is not None else cf
        except Exception:
            return {"error": "chapter_from/chapter_to — число"}
        if ct < cf:
            cf, ct = ct, cf
        try:
            chapters = await _api_get_retry(kind, f"/api/manga/{slug}/chapters")
        except LibError as e:
            return {"error": str(e)}
        all_ch = chapters.get("data") if isinstance(chapters, dict) else []
        if not isinstance(all_ch, list) or not all_ch:
            return {"error": "глав не найдено"}

        def _n(c: dict) -> float | None:
            try:
                return float(c.get("number"))
            except Exception:
                return None

        def _vol(c: dict) -> float:
            try:
                return float(c.get("volume"))
            except Exception:
                return 0.0

        selected = [c for c in all_ch if isinstance(c, dict)
                    and (n := _n(c)) is not None and cf <= n <= ct]
        if not selected:
            return {"error": f"нет глав в диапазоне {cf}..{ct}. Всего: {len(all_ch)}"}
        selected.sort(key=lambda c: (_vol(c), _n(c) if _n(c) is not None else 0.0))
        lim = max_chapters(kind)
        if len(selected) > lim:
            selected = selected[:lim]
        if kind == "ranobe":
            return await self._download_ranobe(kind, slug, selected, fmt=fmt or "epub")
        return await self._download_manga(kind, slug, selected, fmt=fmt or "cbz")

    async def _download_manga(self, kind: str, slug: str, selected: list[dict],
                              fmt: str = "cbz") -> dict[str, Any]:
        fmt = (fmt or "cbz").lower()
        if fmt not in ("cbz", "pdf"):
            fmt = "cbz"
        images_flat: list[bytes] = []
        pages_meta: list[tuple[str, bytes]] = []
        pages_total = 0
        sem = asyncio.Semaphore(_PAGE_CONCURRENCY)

        servers = await image_servers(kind)

        meta, cover_bytes = await _load_meta_and_cover(kind, slug)
        nice = (meta or {}).get("name") or slug

        total_ch = len(selected)
        failed: list[str] = []
        log.info(f"📚 Манга/хентай '{nice}': начинаю скачивание, глав к загрузке: {total_ch}, формат {fmt.upper()}")
        for ci, ch in enumerate(selected, 1):
            vol = str(ch.get("volume") or "").strip()
            num = str(ch.get("number") or "").strip()
            log.info(f"📥 {kind} '{slug}': глава {num} (том {vol or '-'}) [{ci}/{total_ch}], страниц уже: {pages_total}")
            try:
                cd = await _api_get_retry(kind, f"/api/manga/{slug}/chapter",
                                          params={"volume": vol, "number": num})
            except LibError as e:
                log.warning(f"⛔ глава {num} (том {vol or '-'}) не скачалась после ретраев, пропускаю: {e}")
                failed.append(num)
                continue
            data = cd.get("data") if isinstance(cd, dict) else None
            pages = (data or {}).get("pages") if isinstance(data, dict) else None
            if not isinstance(pages, list) or not pages:
                log.warning(f"chapter {num}: pages empty")
                continue
            urls = []
            for p in pages:
                if isinstance(p, dict):
                    u = p.get("url") or p.get("image") or ""
                    if u:
                        urls.append(u)
            if pages_total + len(urls) > _MAX_PAGES_TOTAL:
                urls = urls[: _MAX_PAGES_TOTAL - pages_total]

            page_bufs: list[bytes | None] = await asyncio.gather(
                *[_dl_page(sem, u, servers) for u in urls])
            for extra_pass in range(2):
                missing = [i for i, b in enumerate(page_bufs) if not b]
                if not missing:
                    break
                log.warning(f"🔁 глава {num}: недокачано {len(missing)}/{len(urls)} стр., допроход {extra_pass + 1}/2")
                await asyncio.sleep(1.5)
                servers = await image_servers(kind)
                refetched = await asyncio.gather(
                    *[_dl_page(sem, urls[i], servers) for i in missing])
                for idx, buf in zip(missing, refetched):
                    if buf:
                        page_bufs[idx] = buf

            still_missing = [i for i, b in enumerate(page_bufs) if not b]
            if still_missing:
                log.warning(f"⛔ глава {num}: не вышло скачать {len(still_missing)} стр. после всех ретраев, пропускаю главу целиком")
                failed.append(num)
                continue

            for i, buf in enumerate(page_bufs, 1):
                pages_total += 1
                images_flat.append(buf)
                pages_meta.append((f"ch{num}_{i:03d}", buf))
            if pages_total >= _MAX_PAGES_TOTAL:
                log.warning("reached MAX_PAGES_TOTAL, cutting")
                break

        if not images_flat:
            return {"error": "не удалось скачать ни одной страницы (может нужен токен?)"}
        if failed:
            log.warning(f"⚠️ манга '{slug}': пропущено глав из-за сети: {len(failed)} ({', '.join(failed[:10])})")

        first_n = selected[0].get("number") or ""
        last_n  = selected[-1].get("number") or first_n
        rng = f"ch{first_n}" if first_n == last_n else f"ch{first_n}-{last_n}"
        base = _download_dir() / f"{_safe(nice)}_{rng}_{int(time.time())}"
        try:
            if fmt == "pdf":
                out = base.with_suffix(".pdf")
                _images_to_pdf(images_flat, out)
            else:
                out = base.with_suffix(".cbz")
                _images_to_cbz(pages_meta, out, meta=meta, cover=cover_bytes)
        except Exception as e:
            return {"error": f"не смогла собрать {fmt.upper()}: {e}"}

        skip_note = f", пропущено глав: {len(failed)}" if failed else ""
        caption = f"{nice} — главы {first_n}..{last_n} ({len(images_flat)} стр., {fmt.upper()}{skip_note})"
        log.info(f"✅ манга '{nice}': собрано {len(images_flat)} стр. из {total_ch} глав"
                 f"{(' (пропущено ' + str(len(failed)) + ')') if failed else ''} → {out.name}")
        return {"ok": True, "pages": len(images_flat), "chapters": len(selected),
                "skipped": len(failed),
                "path": str(out), "_send_file": str(out), "caption": caption}

    async def _download_ranobe(self, kind: str, slug: str, selected: list[dict],
                               fmt: str = "epub", title: str | None = None) -> dict[str, Any]:
        fmt = (fmt or "epub").lower()
        if fmt not in ("epub", "txt"):
            fmt = "epub"
        epub_chapters: list[tuple[str, str]] = []
        txt_parts: list[str] = []

        meta, cover_bytes = await _load_meta_and_cover(kind, slug)
        nice = (meta or {}).get("name") or title or slug

        total_ch = len(selected)
        failed: list[str] = []
        log.info(f"📖 Ранобэ '{nice}': начинаю скачивание, глав к загрузке: {total_ch}, формат {fmt.upper()}")
        for ci, ch in enumerate(selected, 1):
            vol = str(ch.get("volume") or "").strip()
            num = str(ch.get("number") or "").strip()
            log.info(f"📥 ранобэ '{slug}': глава {num} (том {vol or '-'}) [{ci}/{total_ch}], собрано глав: {len(epub_chapters)}")
            try:
                cd = await _api_get_retry(kind, f"/api/manga/{slug}/chapter",
                                          params={"volume": vol, "number": num})
            except LibError as e:
                log.warning(f"⛔ глава {num} (том {vol or '-'}) не скачалась после ретраев, пропускаю: {e}")
                failed.append(num)
                continue
            data = cd.get("data") if isinstance(cd, dict) else None
            if not isinstance(data, dict):
                continue
            ch_name = data.get("name") or ""
            heading = f"Том {vol} Глава {num}" + (f" — {ch_name}" if ch_name else "")
            content = data.get("content") or ""
            if isinstance(content, dict):
                text = _prosemirror_to_text(content)
            elif isinstance(content, list):
                text = "\n".join(_prosemirror_to_text(x) if isinstance(x, dict) else str(x)
                                 for x in content)
            else:
                text = _strip_html(str(content))
            text = text.strip()
            epub_chapters.append((heading, _text_to_xhtml_body(text)))
            txt_parts.append(f"# {heading}\n\n{text}\n")

        if not epub_chapters:
            return {"error": "текста глав не получено"}
        if failed:
            log.warning(f"⚠️ ранобэ '{slug}': пропущено глав из-за сети: {len(failed)} ({', '.join(failed[:10])})")

        first_n = selected[0].get("number") or ""
        last_n  = selected[-1].get("number") or first_n
        rng = f"ch{first_n}" if first_n == last_n else f"ch{first_n}-{last_n}"
        base = _download_dir() / f"{_safe(nice)}_{rng}_{int(time.time())}"
        ep_author = ", ".join((meta or {}).get("authors") or []) or "RanobeLib"
        try:
            if fmt == "txt":
                out = base.with_suffix(".txt")
                out.write_text(_txt_with_header(nice, meta, txt_parts), encoding="utf-8")
            else:
                out = base.with_suffix(".epub")
                _build_epub(out, nice, ep_author, epub_chapters,
                            meta=meta, cover=cover_bytes)
        except Exception as e:
            return {"error": f"не смогла собрать {fmt.upper()}: {e}"}

        skip_note = f", пропущено: {len(failed)}" if failed else ""
        caption = f"{nice} — ранобэ, главы {first_n}..{last_n} ({len(epub_chapters)} гл., {fmt.upper()}{skip_note})"
        log.info(f"✅ ранобэ '{nice}': собрано {len(epub_chapters)} гл. из {total_ch}"
                 f"{(' (пропущено ' + str(len(failed)) + ')') if failed else ''} → {out.name}")
        return {"ok": True, "chapters": len(epub_chapters), "skipped": len(failed),
                "path": str(out), "_send_file": str(out), "caption": caption}

def _strip_html(html: str) -> str:
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.IGNORECASE)
    txt = re.sub(r"</p\s*>", "\n\n", txt, flags=re.IGNORECASE)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()

def _prosemirror_to_text(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "") or ""
    if t == "hardBreak":
        return "\n"
    content = node.get("content") or []
    inner = "".join(_prosemirror_to_text(c) for c in content)
    if t in ("paragraph", "heading", "blockquote"):
        return inner + "\n\n"
    if t in ("bulletList", "orderedList"):
        return inner + "\n"
    if t == "listItem":
        return "• " + inner
    return inner
