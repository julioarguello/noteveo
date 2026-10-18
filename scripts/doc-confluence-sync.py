#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "pyyaml", "beautifulsoup4", "markdown"]
#
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Sincroniza documentación Markdown con Confluence Cloud, en ambas direcciones.

Convierte un fichero Markdown (con la convención del repo: frontmatter
`confluence_page_id`, alerts estilo GitHub, directivas de layout y TOC) a
*storage format* de Confluence, sube las imágenes relativas como adjuntos y
actualiza la página destino vía la API REST. También hace el viaje inverso
(`--pull`) y compara ambos lados sin escribir nada (`--check`).

Uso:
    doc-confluence-sync.py <fichero.md> [opciones]

Opciones:
    --page-id ID     Sobrescribe el id de página del frontmatter.
    --dry-run        No toca Confluence: escribe el storage format en disco.
    --out RUTA       Fichero de salida del dry-run (default: <md>.storage.html).
    --keep-draft     Si la página es un borrador, la actualiza sin publicarla.
    --title TÍTULO   Fuerza el título de la página (default: el actual).
    --pull           Trae la página viva al fichero Markdown (conserva el
                     frontmatter y descarga los adjuntos que falten en local).
    --check          Compara el inventario de la página viva con el render del
                     Markdown local. No escribe nada. Sale con 1 si publicar
                     perdería contenido que la página viva sí tiene.
    --create         Crea la página (el fichero NO debe tener page id todavía)
                     y escribe el `confluence_page_id` en el frontmatter.
    --space CLAVE    Espacio destino de --create (o `confluence_space:` en el
                     frontmatter, o la variable CONFLUENCE_SPACE).
    --parent TÍTULO  Página padre de --create, por título (opcional).
    --parent-id ID   Página padre de --create, por id (opcional).
    -v/--verbose     Traza detallada.

Credenciales (basic auth email:token). Se leen, por orden de prioridad, de:
    1. Variables de entorno CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN
       (+ CONFLUENCE_BASE_URL).
    2. ~/.config/atlassian/confluence.env  (formato KEY=VALUE, chmod 600).

Las directivas soportadas (comentarios HTML que aplican al bloque siguiente):
    <!-- TOC: maxLevel=3, minLevel=1, ... -->        → macro `toc`
    <!-- table-layout: align-start,width=1200,colwidths=284|322 -->
        → data-layout, data-table-width y <colgroup> de la tabla siguiente
    <!-- code-layout: breakoutMode=wide, breakoutWidth=760, ... -->
        → parámetros del macro de código siguiente (theme, linenumbers, ...)

Alerts GitHub ⇄ paneles Confluence (ambas direcciones):
    [!NOTE] ⇄ info · [!TIP] ⇄ tip · [!IMPORTANT] ⇄ note ·
    [!WARNING] ⇄ warning · [!CAUTION] → warning

Bloques plegables (ambas direcciones):
    <details><summary>Título</summary> … </details> ⇄ macro `expand`

Lozenges de estado (ambas direcciones):
    <status colour="Green">OK</status> ⇄ macro `status`

Imágenes con pie (ambas direcciones):
    ![alt](fichero.png "Pie de imagen") ⇄ <ac:image>…<ac:caption>
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdown import Markdown

CREDS_FILE = Path.home() / ".config" / "atlassian" / "confluence.env"

ALERT_MAP = {
    "NOTE": "info",
    "TIP": "tip",
    "IMPORTANT": "note",
    "WARNING": "warning",
    "CAUTION": "warning",
}

# Inverso para --pull. `warning` vuelve como [!WARNING]: el par WARNING/CAUTION
# comparte panel en Confluence, así que la distinción no sobrevive a la ida.
PANEL_MAP = {"info": "NOTE", "tip": "TIP", "note": "IMPORTANT", "warning": "WARNING"}

# Lenguajes que el macro de código de Confluence reconoce; el resto cae a "none".
# `text` es un valor válido en storage (verificado contra una página real), no
# se normaliza a "none": hacerlo cambiaría la página en cada publicación.
KNOWN_LANGS = {
    "bash", "shell", "sh", "python", "py", "sql", "json", "yaml", "yml",
    "java", "javascript", "js", "typescript", "ts", "go", "xml", "html",
    "text", "plaintext", "none", "diff", "dockerfile", "groovy", "kotlin",
}

# Valores de data-layout que Confluence almacena tal cual en las tablas.
TABLE_LAYOUTS = {"default", "wide", "full-width", "center", "align-start", "align-end"}

# Orden canónico de parámetros del macro de código (el que escribe Confluence).
CODE_PARAM_ORDER = ["breakoutMode", "breakoutWidth", "language", "theme", "linenumbers"]

# Colores que acepta el macro `status`.
STATUS_COLOURS = {"Green", "Red", "Yellow", "Blue", "Grey", "Purple"}


# ── Credenciales ────────────────────────────────────────────────────────────────


def _strip_inline_comment(value: str) -> str:
    """Recorta un comentario al final de un valor, respetando las comillas.

    Es lo que hace ``python-dotenv``: un ``#`` precedido de espacio y fuera de
    comillas abre un comentario. Sin esto, ``FOO=bar  # nota`` vale
    ``bar  # nota`` y el comentario viaja hasta donde el valor se usa —una ruta
    de credenciales, una URL, un token— muy lejos del fichero que lo originó.
    El síntoma llega disfrazado: ``DefaultCredentialsError`` sobre un fichero
    cuyo nombre lleva un comentario dentro, o un 401 que parece un token
    caducado.

    Exige el espacio antes del ``#`` a propósito: ``FOO=a#b`` es el valor
    ``a#b``, no ``a``. Un secreto que necesite un ``#`` tras un espacio se
    entrecomilla, que es la convención de dotenv.
    """
    quote = ""
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value


def load_credentials() -> tuple[str, str, str]:
    """Devuelve (base_url, email, token). Falla si faltan."""
    env: dict[str, str] = {}
    if CREDS_FILE.exists():
        for line in CREDS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = _strip_inline_comment(val.strip())

    def lookup(*names: str) -> str | None:
        # CONFLUENCE_USER / CONFLUENCE_TOKEN son los nombres que usaba la
        # skill previa de sincronización; se aceptan como alias para no
        # obligar a renombrar entornos que ya funcionan.
        for name in names:
            value = os.environ.get(name) or env.get(name)
            if value:
                return value
        return None

    base = lookup("CONFLUENCE_BASE_URL")
    email = lookup("CONFLUENCE_EMAIL", "CONFLUENCE_USER")
    token = lookup("CONFLUENCE_API_TOKEN", "CONFLUENCE_TOKEN")

    missing = [
        name
        for name, val in (
            ("CONFLUENCE_BASE_URL", base),
            ("CONFLUENCE_EMAIL (o CONFLUENCE_USER)", email),
            ("CONFLUENCE_API_TOKEN (o CONFLUENCE_TOKEN)", token),
        )
        if not val
    ]
    if missing:
        sys.exit(
            f"[confluence] faltan credenciales: {', '.join(missing)}.\n"
            f"  Defínelas en el entorno o en {CREDS_FILE}"
        )
    return base.rstrip("/"), email, token  # type: ignore[union-attr]


# ── Parsing del Markdown ────────────────────────────────────────────────────────


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Separa el frontmatter YAML (--- ... ---) del cuerpo."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end].strip()
            body = text[end + 4 :].lstrip("\n")
            try:
                meta = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, body
    return {}, text


def raw_frontmatter(text: str) -> str:
    """El bloque frontmatter tal cual está escrito, incluidos los `---`."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[: end + 4]
    return ""


def parse_directive(comment: str) -> tuple[str, dict[str, str]] | None:
    """Parsea `name: k=v, k2=v2` de un comentario de directiva."""
    m = re.match(r"\s*(TOC|table-layout|code-layout)\s*:?\s*(.*)", comment.strip())
    if not m:
        return None
    name, rest = m.group(1), m.group(2)
    params: dict[str, str] = {}
    for token in re.split(r"[,]", rest):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, _, v = token.partition("=")
            params[k.strip()] = v.strip()
        else:
            params[token] = ""  # flag suelto, p.ej. "align-start"
    return name, params


def rewrite_alert_runs(md_body: str) -> str:
    """Reescribe los alerts GitHub como `<div data-panel=… markdown="1">`.

    python-markdown fusiona blockquotes adyacentes aunque los separe una línea
    en blanco, así que dos alerts seguidos acabarían en un solo panel. Como div
    con `markdown="1"` cada alert conserva su identidad y su interior se
    convierte en el MISMO pase que el resto del documento — fences y tablas
    incluidos, que dentro de un blockquote el preprocesador de fences no ve.

    Un run de citas puede traer texto normal antes del primer marcador y varios
    marcadores dentro: se segmenta en cada `[!TYPE]` y lo previo al primero
    sigue siendo cita normal. Los runs dentro de un fence (```) se dejan tal
    cual: son ejemplos de sintaxis, no alerts.
    """
    lines = md_body.split("\n")
    out: list[str] = []
    i = 0
    in_fence = False
    while i < len(lines):
        if re.match(r"\s*```", lines[i]):
            in_fence = not in_fence
        if in_fence or not lines[i].lstrip().startswith(">"):
            out.append(lines[i])
            i += 1
            continue
        run: list[str] = []
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            run.append(lines[i])
            i += 1
        inner = [re.sub(r"^\s*>\s?", "", line) for line in run]

        segments: list[tuple[str | None, list[str]]] = []
        marker: str | None = None
        current: list[str] = []
        for line in inner:
            m = re.match(r"\[!(\w+)\]\s*$", line.strip())
            if m and m.group(1).upper() in ALERT_MAP:
                segments.append((marker, current))
                marker, current = m.group(1).upper(), []
            else:
                current.append(line)
        segments.append((marker, current))

        for seg_marker, body in segments:
            if seg_marker is None:
                if any(line.strip() for line in body):
                    out.extend("> " + line if line.strip() else ">" for line in body)
            else:
                out.extend(["", f'<div data-panel="{ALERT_MAP[seg_marker]}" markdown="1">', ""])
                out.extend(body)
                out.extend(["", "</div>", ""])
    return "\n".join(out)


# ── Conversión a storage format ─────────────────────────────────────────────────


def apply_table_layout(soup: BeautifulSoup, table: Tag, params: dict[str, str]) -> None:
    """Aplica una directiva table-layout a la tabla: layout, ancho y columnas.

    Confluence almacena el layout tal cual (`data-layout="align-start"`) y el
    ancho aparte (`data-table-width`); no se cuantiza el ancho a un layout.
    """
    layout = next((key for key in params if key in TABLE_LAYOUTS), None)
    if layout:
        table["data-layout"] = layout
    if params.get("width"):
        table["data-table-width"] = params["width"]
    if params.get("colwidths"):
        colgroup = soup.new_tag("colgroup")
        for width in params["colwidths"].split("|"):
            width = width.strip()
            if not width:
                continue
            col = soup.new_tag("col")
            col["style"] = f"width: {width}px;"
            colgroup.append(col)
        table.insert(0, colgroup)


def make_code_macro(
    soup: BeautifulSoup, code_text: str, language: str, extra: dict[str, str]
) -> Tag:
    """Macro `code`: lenguaje + parámetros de layout (breakout, theme...)."""
    lang = (language or "").lower()
    lang = lang if lang in KNOWN_LANGS else "none"
    params = dict(extra)
    params["language"] = lang
    macro = soup.new_tag("ac:structured-macro")
    macro["ac:name"] = "code"
    macro["ac:schema-version"] = "1"
    ordered = [k for k in CODE_PARAM_ORDER if k in params]
    ordered += [k for k in params if k not in CODE_PARAM_ORDER]
    for key in ordered:
        p = soup.new_tag("ac:parameter")
        p["ac:name"] = key
        p.string = params[key]
        macro.append(p)
    body = soup.new_tag("ac:plain-text-body")
    # CDATA: insertamos un marcador y lo sustituimos en serialización final.
    body.string = f"@@CDATA_START@@{code_text}@@CDATA_END@@"
    macro.append(body)
    return macro


def make_image(soup: BeautifulSoup, filename: str, alt: str, caption: str) -> Tag:
    """Imagen como adjunto de la página, con alt y pie opcionales."""
    img = soup.new_tag("ac:image")
    img["ac:align"] = "center"
    img["ac:layout"] = "center"
    if alt:
        img["ac:alt"] = alt
    ri = soup.new_tag("ri:attachment")
    ri["ri:filename"] = filename
    img.append(ri)
    if caption:
        cap = soup.new_tag("ac:caption")
        p = soup.new_tag("p")
        p.string = caption
        cap.append(p)
        img.append(cap)
    return img


def make_expand(soup: BeautifulSoup, title: str, children: list, width: str = "") -> Tag:
    """Bloque plegable: ``<details>`` no existe en storage format.

    Confluence lo escribe como macro ``expand``. Los hijos llegan ya
    convertidos: el interior del ``<details>`` se procesa en el mismo pase que
    el resto del documento gracias a ``markdown="1"`` (extensión md_in_html).
    """
    macro = soup.new_tag("ac:structured-macro")
    macro["ac:name"] = "expand"
    macro["ac:schema-version"] = "1"
    if width:
        param = soup.new_tag("ac:parameter")
        param["ac:name"] = "breakoutWidth"
        param.string = width
        macro.append(param)
    param = soup.new_tag("ac:parameter")
    param["ac:name"] = "title"
    param.string = title
    macro.append(param)
    body = soup.new_tag("ac:rich-text-body")
    for node in children:
        body.append(node)
    macro.append(body)
    return macro


def make_status(soup: BeautifulSoup, colour: str, title: str) -> Tag:
    """Macro `status` (lozenge de color): <status colour="Green">OK</status>."""
    colour = colour.strip().capitalize()
    if colour not in STATUS_COLOURS:
        print(
            f"[confluence] aviso: colour «{colour}» no es un color de status "
            f"conocido ({', '.join(sorted(STATUS_COLOURS))}); se envía tal cual",
            file=sys.stderr,
        )
    macro = soup.new_tag("ac:structured-macro")
    macro["ac:name"] = "status"
    macro["ac:schema-version"] = "1"
    p = soup.new_tag("ac:parameter")
    p["ac:name"] = "colour"
    p.string = colour
    macro.append(p)
    p = soup.new_tag("ac:parameter")
    p["ac:name"] = "title"
    p.string = title
    macro.append(p)
    return macro


def make_toc(soup: BeautifulSoup, params: dict[str, str]) -> Tag:
    """Macro `toc` con los parámetros de la directiva homónima."""
    macro = soup.new_tag("ac:structured-macro")
    macro["ac:name"] = "toc"
    macro["ac:schema-version"] = "1"
    for key in ("maxLevel", "minLevel", "outline", "style", "type", "printable"):
        if key in params:
            p = soup.new_tag("ac:parameter")
            p["ac:name"] = key
            p.string = params[key]
            macro.append(p)
    return macro


def transform(soup: BeautifulSoup) -> None:
    """Aplica todas las transformaciones in-place sobre el DOM.

    El DOM llega COMPLETO de un único pase de Markdown: también el interior de
    los `<details>` y de los divs de alert (md_in_html). Cada paso recorre el
    documento entero, interiores incluidos.
    """
    # 1. Directivas en comentarios HTML → aplican al siguiente elemento.
    for comment in list(soup.find_all(string=lambda t: isinstance(t, Comment))):
        parsed = parse_directive(str(comment))
        if not parsed:
            comment.extract()
            continue
        name, params = parsed
        if name == "TOC":
            comment.replace_with(make_toc(soup, params))
        elif name == "table-layout":
            nxt = comment.find_next("table")
            if nxt is not None:
                apply_table_layout(soup, nxt, params)
            comment.extract()
        else:  # code-layout → parámetros extra del siguiente macro de código
            nxt = comment.find_next("pre")
            if nxt is not None:
                nxt["data-code-layout"] = ";".join(f"{k}={v}" for k, v in params.items())
            comment.extract()

    # 2. Bloques de código <pre><code> → code macro (+ params de code-layout).
    for pre in list(soup.find_all("pre")):
        code = pre.find("code")
        code_text = (code.get_text() if code else pre.get_text())
        code_text = code_text.rstrip("\n")
        language = ""
        if code is not None:
            classes = code.get("class") or []
            for cls in classes:
                if cls.startswith("language-"):
                    language = cls[len("language-") :]
        extra = dict(
            kv.split("=", 1)
            for kv in pre.get("data-code-layout", "").split(";")
            if "=" in kv
        )
        pre.replace_with(make_code_macro(soup, code_text, language, extra))

    # 3. Tablas sin layout → data-layout default.
    for table in soup.find_all("table"):
        if not table.get("data-layout"):
            table["data-layout"] = "default"

    # 4. Imágenes → adjuntos (title del Markdown → pie de imagen). Markdown
    # envuelve la imagen en un párrafo; Confluence la almacena a nivel de
    # bloque, así que si el párrafo solo contenía la imagen, se desenvuelve.
    for img in list(soup.find_all("img")):
        src = img.get("src", "")
        alt = img.get("alt", "")
        caption = img.get("title", "")
        filename = os.path.basename(src)
        ac_image = make_image(soup, filename, alt, caption)
        holder = img.parent
        img.replace_with(ac_image)
        # Vacío = sin más hijos que la imagen; get_text() no sirve aquí porque
        # incluiría el texto del pie, que vive DENTRO de ac:image.
        if holder is not None and holder.name == "p" and not any(
            child is not ac_image and (isinstance(child, Tag) or str(child).strip())
            for child in holder.children
        ):
            holder.replace_with(ac_image)

    # 5. <caption> suelto tras una imagen → pie de imagen con markup. Es la
    # forma que usa --pull cuando el pie lleva links o código, que el atributo
    # title de ![alt](f "pie") no puede transportar.
    for cap in list(soup.find_all("caption")):
        if cap.find_parent("table") is not None:
            continue  # caption real de tabla, no un pie de imagen
        target = cap.find_previous("ac:image")
        if target is None:
            print("[confluence] aviso: <caption> sin imagen precedente; se descarta",
                  file=sys.stderr)
            cap.extract()
            continue
        accap = soup.new_tag("ac:caption")
        inner_p = soup.new_tag("p")
        for child in list(cap.children):
            inner_p.append(child.extract())
        accap.append(inner_p)
        target.append(accap)
        holder = cap.parent
        cap.extract()
        if holder is not None and holder.name == "p" and not holder.get_text(strip=True) \
                and holder.find(True) is None:
            holder.extract()

    # 6. Divs de alert (reescritos por rewrite_alert_runs) → paneles.
    for div in list(soup.find_all("div", attrs={"data-panel": True})):
        macro = soup.new_tag("ac:structured-macro")
        macro["ac:name"] = div["data-panel"]
        macro["ac:schema-version"] = "1"
        rtb = soup.new_tag("ac:rich-text-body")
        for child in list(div.children):
            rtb.append(child.extract())
        macro.append(rtb)
        div.replace_with(macro)

    # 7. <status colour="…">TÍTULO</status> → macro status (lozenge).
    for st in list(soup.find_all("status")):
        st.replace_with(make_status(soup, st.get("colour", "Grey"), st.get_text(strip=True)))

    # 8. <details>/<summary> → macro expand. Va el último: sus hijos ya están
    # transformados por los pasos anteriores y solo hay que envolverlos.
    for details in list(soup.find_all("details")):
        summary = details.find("summary")
        title = summary.get_text(strip=True) if summary is not None else "Ver más"
        if summary is not None:
            summary.extract()
        details.replace_with(
            make_expand(soup, title, list(details.contents), details.get("width", ""))
        )


def _new_md() -> Markdown:
    return Markdown(
        # extra: tablas, fenced_code, attr_list... · md_in_html: convierte el
        # interior de bloques HTML con markdown="1" en el mismo pase.
        extensions=["extra", "sane_lists", "md_in_html"],
        output_format="html",
    )


def _finalize_cdata(xhtml: str) -> str:
    """Reconstituye los CDATA de los bloques de código y los des-escapa."""
    xhtml = xhtml.replace("@@CDATA_START@@", "<![CDATA[").replace(
        "@@CDATA_END@@", "]]>"
    )

    def _unescape(match: re.Match[str]) -> str:
        return "<![CDATA[" + html.unescape(match.group(1)) + "]]>"

    xhtml = re.sub(r"&lt;!\[CDATA\[(.*?)\]\]&gt;", _unescape, xhtml, flags=re.DOTALL)
    xhtml = re.sub(r"<!\[CDATA\[(.*?)\]\]>", _unescape, xhtml, flags=re.DOTALL)
    return xhtml


def collect_images(md_body: str) -> list[str]:
    """Basenames de todas las imágenes referenciadas en el Markdown."""
    found = {
        os.path.basename(src.split()[0].strip("<>"))
        for src in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_body)
    }
    return sorted(found)


def markdown_to_storage(md_body: str) -> tuple[str, list[str]]:
    """Convierte Markdown a storage XHTML en un único pase. → (xhtml, imágenes)."""
    images = collect_images(md_body)
    body = rewrite_alert_runs(md_body)
    # md_in_html solo entra en los bloques que lo piden; el repo escribe
    # <details> a secas (a veces con width=…), así que el atributo se inyecta aquí.
    body = re.sub(r"<details(?=[\s>])", '<details markdown="1"', body)
    soup = BeautifulSoup(_new_md().convert(body), "html.parser")
    transform(soup)
    return _finalize_cdata(str(soup)), images


# ── Conversión inversa: storage format → Markdown (--pull) ──────────────────────


class UnhandledStorage(Exception):
    """Contenido de la página que el conversor inverso no sabe representar."""


def _inline_md(node: object, unhandled: list[str]) -> str:
    """Serializa contenido inline de storage a Markdown."""
    if isinstance(node, NavigableString):
        # La página puede traer *, _ o ` literales; sin escapar, la siguiente
        # publicación los reinterpretaría como énfasis o código.
        return re.sub(r"([\\`*_])", r"\\\1", re.sub(r"\s+", " ", str(node)))
    if not isinstance(node, Tag):
        return ""
    # Ramas que NO recorren hijos, antes de calcular `inner`: recorrer los
    # hijos de un macro registraría sus ac:parameter como no soportados.
    if node.name == "ac:structured-macro" and node.get("ac:name") == "status":
        params = {
            p.get("ac:name"): p.get_text(strip=True)
            for p in node.find_all("ac:parameter", recursive=False)
        }
        colour = params.get("colour", "Grey")
        title = params.get("title", "")
        return f'<status colour="{colour}">{title}</status>'
    if node.name == "code":
        text = node.get_text()
        fence = "``" if "`" in text else "`"
        return f"{fence}{text}{fence}"
    if node.name == "br":
        return "<br>"
    inner = "".join(_inline_md(child, unhandled) for child in node.children)
    if node.name == "strong":
        return f"**{inner.strip()}**" if inner.strip() else ""
    if node.name == "em":
        return f"*{inner.strip()}*" if inner.strip() else ""
    if node.name == "a":
        return f"[{inner.strip()}]({node.get('href', '')})"
    if node.name in {"span", "p", "u", "sub", "sup", "time"}:
        return inner
    unhandled.append(f"inline <{node.name}>")
    return inner


def _macro_params(macro: Tag) -> dict[str, str]:
    return {
        p.get("ac:name"): p.get_text(strip=True)
        for p in macro.find_all("ac:parameter", recursive=False)
    }


def _quote_block(text: str) -> list[str]:
    return ["> " + line if line.strip() else ">" for line in text.split("\n")]


def _list_md(tag: Tag, unhandled: list[str], indent: int = 0) -> str:
    lines: list[str] = []
    ordered = tag.name == "ol"
    for position, li in enumerate(tag.find_all("li", recursive=False), start=1):
        bullet = f"{position}. " if ordered else "- "
        sublists = li.find_all(["ul", "ol"], recursive=False)
        inline = "".join(
            _inline_md(child, unhandled)
            for child in li.children
            if not (isinstance(child, Tag) and child.name in {"ul", "ol"})
        ).strip()
        lines.append(" " * indent + bullet + inline)
        for sub in sublists:
            lines.append(_list_md(sub, unhandled, indent + 4))
    return "\n".join(lines)


def _table_md(table: Tag, unhandled: list[str]) -> str:
    directive_parts: list[str] = []
    layout = table.get("data-layout", "")
    if layout and layout != "default":
        directive_parts.append(layout)
    if table.get("data-table-width"):
        directive_parts.append(f"width={table['data-table-width']}")
    colgroup = table.find("colgroup")
    if colgroup is not None:
        widths = []
        for col in colgroup.find_all("col"):
            m = re.search(r"width:\s*([\d.]+)px", col.get("style", ""))
            if m:
                widths.append(str(int(float(m.group(1)))))
        if widths:
            directive_parts.append("colwidths=" + "|".join(widths))
    lines: list[str] = []
    if directive_parts:
        lines.append(f"<!-- table-layout: {','.join(directive_parts)} -->")

    rows = table.find_all("tr")
    if not rows:
        return "\n".join(lines)

    def cells(row: Tag) -> list[str]:
        out = []
        for cell in row.find_all(["th", "td"], recursive=False):
            text = "".join(_inline_md(child, unhandled) for child in cell.children)
            out.append(re.sub(r"\s+", " ", text).strip().replace("|", r"\|"))
        return out

    header = cells(rows[0])
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(cells(row)) + " |")
    return "\n".join(lines)


def _macro_md(macro: Tag, unhandled: list[str]) -> str:
    name = macro.get("ac:name", "")
    params = _macro_params(macro)

    if name == "toc":
        inner = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"<!-- TOC: {inner} -->"

    if name == "code":
        language = params.pop("language", "")
        body = macro.find("ac:plain-text-body")
        code_text = body.get_text() if body is not None else ""
        lines = []
        extra = {k: params[k] for k in CODE_PARAM_ORDER if k in params and k != "language"}
        extra.update({k: v for k, v in params.items() if k not in extra})
        if extra:
            inner = ", ".join(f"{k}={v}" for k, v in extra.items())
            lines.append(f"<!-- code-layout: {inner} -->")
        fence_lang = "" if language == "none" else language
        lines.append(f"```{fence_lang}")
        lines.append(code_text)
        lines.append("```")
        return "\n".join(lines)

    if name in PANEL_MAP:
        for extra_param in params:
            unhandled.append(f"param {name}.{extra_param}")
        body = macro.find("ac:rich-text-body")
        inner = _blocks_md(list(body.children) if body is not None else [], unhandled)
        return "\n".join([f"> [!{PANEL_MAP[name]}]", *_quote_block(inner)])

    if name == "expand":
        title = params.pop("title", "Ver más")
        width = params.pop("breakoutWidth", "")
        for extra_param in params:
            unhandled.append(f"param expand.{extra_param}")
        body = macro.find("ac:rich-text-body")
        inner = _blocks_md(list(body.children) if body is not None else [], unhandled)
        attrs = f' width="{width}"' if width else ""
        return f"<details{attrs}>\n<summary>{title}</summary>\n\n{inner}\n\n</details>"

    if name == "status":  # a nivel de bloque: envuelto en párrafo propio
        return _inline_md(macro, unhandled)

    unhandled.append(f"macro «{name}»")
    return ""


def _image_md(img: Tag, unhandled: list[str]) -> str:
    att = img.find("ri:attachment")
    filename = att.get("ri:filename", "") if att is not None else ""
    alt = img.get("ac:alt", "")
    cap = img.find("ac:caption")
    if cap is None:
        return f"![{alt}]({filename})"
    cap_body = cap.find("p") or cap
    if cap_body.find(True) is None:  # texto plano → atributo title
        return f'![{alt}]({filename} "{cap_body.get_text(strip=True)}")'
    # Pie con markup (links, código): el title no lo transporta.
    inner = "".join(_inline_md(child, unhandled) for child in cap_body.children).strip()
    return f"![{alt}]({filename})\n\n<caption>{inner}</caption>"


def _blocks_md(nodes: list, unhandled: list[str]) -> str:
    blocks: list[str] = []
    for node in nodes:
        if isinstance(node, NavigableString):
            if str(node).strip():
                blocks.append(str(node).strip())
            continue
        if not isinstance(node, Tag):
            continue
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(node.name[1])
            blocks.append("#" * level + " " + node.get_text(" ", strip=True))
        elif node.name == "p":
            children_tags = [c for c in node.children if isinstance(c, Tag)]
            only_image = (
                len(children_tags) == 1
                and children_tags[0].name == "ac:image"
                and not node.get_text(strip=True)
            )
            if only_image:
                blocks.append(_image_md(children_tags[0], unhandled))
                continue
            text = "".join(_inline_md(child, unhandled) for child in node.children).strip()
            if text:
                blocks.append(text)
        elif node.name == "hr":
            blocks.append("---")
        elif node.name in {"ul", "ol"}:
            blocks.append(_list_md(node, unhandled))
        elif node.name == "table":
            blocks.append(_table_md(node, unhandled))
        elif node.name == "blockquote":
            inner = _blocks_md(list(node.children), unhandled)
            blocks.append("\n".join(_quote_block(inner)))
        elif node.name == "ac:image":
            blocks.append(_image_md(node, unhandled))
        elif node.name == "ac:structured-macro":
            rendered = _macro_md(node, unhandled)
            if rendered:
                blocks.append(rendered)
        elif node.name in {"div", "section"}:
            blocks.append(_blocks_md(list(node.children), unhandled))
        else:
            unhandled.append(f"bloque <{node.name}>")
    return "\n\n".join(b for b in blocks if b)


def storage_to_markdown(storage: str) -> str:
    """Convierte storage format a Markdown con la convención del repo.

    Falla con la lista de construcciones no soportadas en vez de omitirlas:
    una omisión silenciosa aquí es contenido que la siguiente publicación
    borraría de la página.
    """
    soup = BeautifulSoup(storage, "html.parser")
    unhandled: list[str] = []
    md = _blocks_md(list(soup.children), unhandled)
    if unhandled:
        raise UnhandledStorage(
            "la página contiene construcciones que el conversor no sabe "
            "representar en Markdown: " + ", ".join(sorted(set(unhandled)))
        )
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


# ── Inventario y comparación (--check) ──────────────────────────────────────────


def storage_inventory(storage: str) -> Counter:
    """Recuento de todo lo que una página puede perder al republicarla."""
    soup = BeautifulSoup(storage, "html.parser")
    inv: Counter = Counter()
    for macro in soup.find_all("ac:structured-macro"):
        name = macro.get("ac:name", "?")
        inv[f"macro {name}"] += 1
        for p in macro.find_all("ac:parameter", recursive=False):
            pname = p.get("ac:name", "?")
            if pname == "title" and name == "expand":
                inv[f"param expand.title «{p.get_text(strip=True)[:40]}»"] += 1
            else:
                inv[f"param {name}.{pname}={p.get_text(strip=True)}"] += 1
    for img in soup.find_all("ac:image"):
        att = img.find("ri:attachment")
        inv[f"imagen {att.get('ri:filename', '?') if att is not None else '?'}"] += 1
        if img.find("ac:caption") is not None:
            inv["imagen con pie"] += 1
    for tag_name in ("h1", "h2", "h3", "h4", "h5", "h6", "table", "ol", "ul", "li",
                     "a", "strong", "em", "hr"):
        count = len(soup.find_all(tag_name))
        if count:
            inv[f"tag {tag_name}"] = count
    return inv


def compare_inventories(live: Counter, local: Counter) -> tuple[list[str], list[str]]:
    """(pérdidas, adiciones) de publicar el render local sobre la página viva."""
    losses: list[str] = []
    additions: list[str] = []
    for key in sorted(set(live) | set(local)):
        in_live, in_local = live[key], local[key]
        if in_local < in_live:
            losses.append(f"{key}: viva={in_live} local={in_local}")
        elif in_local > in_live:
            additions.append(f"{key}: viva={in_live} local={in_local}")
    return losses, additions


# ── API de Confluence ───────────────────────────────────────────────────────────


class Confluence:
    """Cliente mínimo de la API REST de Confluence Cloud (v2 + v1 adjuntos)."""

    def __init__(self, base_url: str, email: str, token: str, verbose: bool = False) -> None:
        self.base = base_url.rstrip("/")
        self.api_root = self.base[: -len("/wiki")] if self.base.endswith("/wiki") else self.base
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.verbose = verbose

    def _log(self, *args: object) -> None:
        if self.verbose:
            print("[confluence]", *args)

    def get_page(self, page_id: str) -> dict:
        """Página por id, con su storage format (busca también en borradores)."""
        url = f"{self.base}/api/v2/pages/{page_id}"
        r = self.session.get(
            url, params={"body-format": "storage"}, headers={"Accept": "application/json"}
        )
        if r.status_code == 404:
            r = self.session.get(
                url,
                params={"status": "draft", "body-format": "storage"},
                headers={"Accept": "application/json"},
            )
        r.raise_for_status()
        return r.json()

    def get_page_by_title(self, space_key: str, title: str) -> dict | None:
        """Primera página con ese título exacto en el espacio, o None."""
        r = self.session.get(
            f"{self.base}/rest/api/content",
            params={"spaceKey": space_key, "title": title, "limit": 1},
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        return results[0] if results else None

    def create_page(
        self, space_key: str, title: str, body_storage: str, parent_id: str | None
    ) -> dict:
        """Crea la página (publicada) y devuelve la respuesta de la API."""
        payload: dict = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": body_storage, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        r = self.session.post(
            f"{self.base}/rest/api/content",
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            print(f"[confluence] error {r.status_code}: {r.text[:800]}", file=sys.stderr)
        r.raise_for_status()
        return r.json()

    def _existing_attachments(self, page_id: str) -> dict[str, dict]:
        """{filename: {"id": …, "download": …}} de los adjuntos de la página."""
        url = f"{self.base}/rest/api/content/{page_id}/child/attachment"
        result: dict[str, dict] = {}
        start = 0
        while True:
            r = self.session.get(
                url,
                params={"limit": 100, "start": start},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            for att in data.get("results", []):
                result[att["title"]] = {
                    "id": att["id"],
                    "download": att.get("_links", {}).get("download", ""),
                }
            if data.get("size", 0) < data.get("limit", 0) or not data.get("results"):
                break
            start += data.get("limit", 100)
        return result

    # Reintentos de la subida de adjuntos. Medido el 2026-09-15 sobre la página
    # 1275723777: subir sus TRES adjuntos en una pasada devuelve 500 en el
    # segundo, reproduciblemente, y subir ESE MISMO adjunto solo devuelve 200
    # con el mismo contenido y el mismo content-type. No es el fichero: es que
    # cada subida es una edición de la página, y Confluence Cloud no digiere dos
    # seguidas sobre la misma. Un 500 aquí no es un fallo del que informar, es
    # uno del que apartarse un momento.
    _RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
    _RETRY_WAITS = (1.0, 3.0, 7.0)  # tres reintentos; el último espera de sobra

    def upload_attachment(self, page_id: str, path: Path, existing: dict[str, dict]) -> None:
        """Crea el adjunto, o actualiza su contenido si ya existe (idempotente)."""
        headers = {"X-Atlassian-Token": "no-check", "Accept": "application/json"}
        att = existing.get(path.name)
        if att:
            url = f"{self.base}/rest/api/content/{page_id}/child/attachment/{att['id']}/data"
        else:
            url = f"{self.base}/rest/api/content/{page_id}/child/attachment"

        for intento, espera in enumerate((*self._RETRY_WAITS, None), start=1):
            # El fichero se reabre en CADA intento: un handle ya consumido por
            # el POST anterior se reenviaría vacío y el adjunto quedaría a 0
            # bytes sin que nadie lo notase.
            with path.open("rb") as fh:
                r = self.session.post(
                    url,
                    files={"file": (path.name, fh, "application/octet-stream")},
                    data={"minorEdit": "true"},
                    headers=headers,
                )
            if r.status_code < 400 or r.status_code not in self._RETRY_STATUS or espera is None:
                break
            # Retry-After manda cuando viene (429); si no, la escala propia.
            try:
                espera = max(espera, float(r.headers.get("Retry-After", 0)))
            except ValueError:
                pass
            self._log(
                f"adjunto {path.name}: {r.status_code}, reintento "
                f"{intento}/{len(self._RETRY_WAITS)} en {espera:.0f}s"
            )
            time.sleep(espera)

        if r.status_code >= 400:
            print(f"[confluence] error adjunto {path.name}: {r.status_code} "
                  f"{r.text[:400]}", file=sys.stderr)
        r.raise_for_status()
        self._log(f"adjunto {'actualizado' if att else 'creado'}: {path.name}")

    def download_attachment(self, download_link: str, dest: Path) -> None:
        """Descarga un adjunto a `dest` (el link viene de _existing_attachments)."""
        r = self.session.get(f"{self.base}{download_link}")
        r.raise_for_status()
        dest.write_bytes(r.content)
        self._log(f"adjunto descargado: {dest.name} ({len(r.content)} bytes)")

    def update_page(
        self,
        page: dict,
        body_storage: str,
        title: str,
        publish_draft: bool,
    ) -> dict:
        """Sube el cuerpo y publica el borrador salvo que se pida conservarlo."""
        page_id = page["id"]
        is_draft = page.get("status") == "draft"
        cur_version = int(page.get("version", {}).get("number", 1))

        if is_draft and publish_draft:
            status = "current"
            # Publicar un borrador por primera vez conserva version.number = 1.
            new_version = 1 if cur_version == 1 else cur_version + 1
        elif is_draft:
            status = "draft"
            new_version = cur_version + 1
        else:
            status = "current"
            new_version = cur_version + 1

        payload = {
            "id": page_id,
            "status": status,
            "title": title,
            "spaceId": page.get("spaceId"),
            "body": {"representation": "storage", "value": body_storage},
            "version": {"number": new_version, "message": "Publicado desde Git (doc-confluence-sync.py)"},
        }
        url = f"{self.base}/api/v2/pages/{page_id}"
        r = self.session.put(
            url,
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            self._log("payload:", {k: v for k, v in payload.items() if k != "body"})
            print(f"[confluence] error {r.status_code}: {r.text[:800]}", file=sys.stderr)
        r.raise_for_status()
        return r.json()


# ── CLI ─────────────────────────────────────────────────────────────────────────


def run_check(cf: Confluence, page_id: str, md_body: str) -> int:
    """Compara la página viva con el render local. 1 si publicar perdería algo."""
    page = cf.get_page(page_id)
    live_storage = page.get("body", {}).get("storage", {}).get("value", "")
    local_storage, _ = markdown_to_storage(md_body)
    print(f"[check] página {page_id} «{page.get('title')}» "
          f"version={page.get('version', {}).get('number')}")
    losses, additions = compare_inventories(
        storage_inventory(live_storage), storage_inventory(local_storage)
    )
    if additions:
        print(f"[check] el render local AÑADE {len(additions)} elementos "
              "(normal si el Markdown va por delante):")
        for line in additions:
            print(f"    + {line}")
    if losses:
        print(f"[check] publicar PERDERÍA {len(losses)} elementos que la página viva tiene:")
        for line in losses:
            print(f"    - {line}")
        print("[check] ✗ sincroniza primero con --pull, o corrige el Markdown.")
        return 1
    print("[check] ✓ publicar no pierde nada de la página viva.")
    return 0


def run_pull(cf: Confluence, page_id: str, md_path: Path) -> int:
    """Trae la página viva al fichero local, conservando el frontmatter."""
    page = cf.get_page(page_id)
    live_storage = page.get("body", {}).get("storage", {}).get("value", "")
    try:
        new_body = storage_to_markdown(live_storage)
    except UnhandledStorage as exc:
        sys.exit(f"[pull] ✗ {exc}")

    text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    front = raw_frontmatter(text)
    md_path.write_text((front + "\n\n" if front else "") + new_body, encoding="utf-8")
    print(f"[pull] página {page_id} «{page.get('title')}» "
          f"version={page.get('version', {}).get('number')} → {md_path}")

    # Adjuntos referenciados que no existen en local: se descargan.
    referenced = collect_images(new_body)
    missing = [name for name in referenced if not (md_path.parent / name).exists()]
    if missing:
        attachments = cf._existing_attachments(page_id)
        for name in missing:
            att = attachments.get(name)
            if att and att["download"]:
                cf.download_attachment(att["download"], md_path.parent / name)
                print(f"[pull] adjunto descargado: {name}")
            else:
                print(f"[pull] aviso: la página referencia «{name}» pero no está "
                      "entre sus adjuntos", file=sys.stderr)
    print("[pull] revisa el diff antes de commitear: git diff " + str(md_path))
    return 0


def write_page_id(md_path: Path, page_id: str) -> None:
    """Inserta `confluence_page_id` en el frontmatter, creándolo si no existe."""
    text = md_path.read_text(encoding="utf-8")
    front = raw_frontmatter(text)
    line = f"confluence_page_id: {page_id}"
    if front:
        closing = front.rfind("\n---")
        new_front = front[:closing] + f"\n{line}" + front[closing:]
        md_path.write_text(new_front + text[len(front) :], encoding="utf-8")
    else:
        md_path.write_text(f"---\n{line}\n---\n\n" + text, encoding="utf-8")


def run_create(cf: Confluence, args: argparse.Namespace, meta: dict, body: str) -> int:
    """Crea la página en Confluence y deja su id en el frontmatter del md."""
    md_path: Path = args.markdown
    existing = args.page_id or meta.get("confluence_page_id")
    if existing:
        sys.exit(
            f"[create] ✗ {md_path} ya apunta a la página {existing}; "
            "usa la publicación normal (sin --create)."
        )
    space = args.space or meta.get("confluence_space") or os.environ.get("CONFLUENCE_SPACE")
    if not space:
        sys.exit(
            "[create] falta el espacio destino: --space, `confluence_space:` "
            "en el frontmatter, o la variable CONFLUENCE_SPACE."
        )
    title = args.title or meta.get("title")
    if not title:
        sys.exit("[create] falta el título: --title o `title:` en el frontmatter.")

    storage, image_names = markdown_to_storage(body)
    images = [md_path.parent / name for name in image_names]
    missing = [str(p) for p in images if not p.exists()]
    if missing:
        sys.exit("Imágenes referenciadas que no existen:\n  " + "\n  ".join(missing))

    parent_id = args.parent_id
    if args.parent and not parent_id:
        parent = cf.get_page_by_title(space, args.parent)
        if not parent:
            sys.exit(
                f"[create] ✗ no existe la página padre «{args.parent}» "
                f"en el espacio {space}."
            )
        parent_id = parent["id"]

    result = cf.create_page(space, title, storage, parent_id)
    page_id = str(result["id"])
    write_page_id(md_path, page_id)

    attachments = cf._existing_attachments(page_id)
    for img in images:
        cf.upload_attachment(page_id, img, attachments)

    links = result.get("_links", {})
    url = (links.get("base", "") + links.get("webui", "")) or f"{cf.base}/pages/{page_id}"
    print(f"[create] página {page_id} «{title}» creada en el espacio {space}"
          + (f" (padre {parent_id})" if parent_id else ""))
    print(f"[create] {len(images)} imágenes adjuntadas")
    print(f"[create] frontmatter actualizado: confluence_page_id: {page_id} → {md_path}")
    print(f"[create] {url}")
    return 0


def main() -> int:
    """Punto de entrada de la CLI."""
    ap = argparse.ArgumentParser(description="Sincroniza Markdown con Confluence Cloud.")
    ap.add_argument("markdown", type=Path, help="Fichero Markdown a sincronizar.")
    ap.add_argument("--page-id", help="Id de página (sobrescribe el frontmatter).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="No publica; escribe el storage.")
    mode.add_argument("--pull", action="store_true",
                      help="Trae la página viva al fichero Markdown.")
    mode.add_argument("--check", action="store_true",
                      help="Compara la página viva con el render local; no escribe nada.")
    mode.add_argument("--create", action="store_true",
                      help="Crea la página y escribe su id en el frontmatter.")
    ap.add_argument("--space", help="Clave del espacio destino (--create).")
    ap.add_argument("--parent", help="Título de la página padre (--create).")
    ap.add_argument("--parent-id", help="Id de la página padre (--create).")
    ap.add_argument("--out", type=Path, help="Salida del dry-run.")
    ap.add_argument("--keep-draft", action="store_true", help="No publicar el borrador.")
    ap.add_argument("--title", help="Fuerza el título de la página.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not args.markdown.exists() and not args.pull:
        sys.exit(f"No existe el fichero: {args.markdown}")

    text = args.markdown.read_text(encoding="utf-8") if args.markdown.exists() else ""
    meta, body = split_frontmatter(text)

    if args.create:
        base_url, email, token = load_credentials()
        cf = Confluence(base_url, email, token, verbose=args.verbose)
        return run_create(cf, args, meta, body)

    page_id = args.page_id or (meta.get("confluence_page_id") and str(meta["confluence_page_id"]))
    if not page_id:
        sys.exit(
            "No hay page id. Añade `confluence_page_id:` al frontmatter o usa --page-id."
        )

    if args.pull or args.check:
        base_url, email, token = load_credentials()
        cf = Confluence(base_url, email, token, verbose=args.verbose)
        if args.pull:
            return run_pull(cf, page_id, args.markdown)
        return run_check(cf, page_id, body)

    storage, image_names = markdown_to_storage(body)

    # Resuelve rutas de imágenes relativas al .md.
    base_dir = args.markdown.parent
    images = [base_dir / name for name in image_names]
    missing = [str(p) for p in images if not p.exists()]
    if missing:
        sys.exit("Imágenes referenciadas que no existen:\n  " + "\n  ".join(missing))

    if args.dry_run:
        out = args.out or args.markdown.with_suffix(".storage.html")
        out.write_text(storage, encoding="utf-8")
        print(f"[dry-run] storage format escrito en: {out}")
        print(f"[dry-run] página destino: {page_id}")
        print(f"[dry-run] imágenes a adjuntar ({len(images)}): "
              + ", ".join(p.name for p in images))
        return 0

    base_url, email, token = load_credentials()
    cf = Confluence(base_url, email, token, verbose=args.verbose)

    page = cf.get_page(page_id)
    title = args.title or page.get("title") or args.markdown.stem
    print(f"[confluence] página {page_id} «{title}» (status={page.get('status')}, "
          f"version={page.get('version', {}).get('number')})")

    # El cuerpo va primero: la API de adjuntos (v1) no encuentra páginas en
    # estado draft, así que primero publicamos/actualizamos y luego adjuntamos.
    result = cf.update_page(
        page, storage, title, publish_draft=not args.keep_draft
    )

    existing = cf._existing_attachments(page_id)
    for img in images:
        cf.upload_attachment(page_id, img, existing)
    print(f"[confluence] {len(images)} imágenes adjuntadas")

    new_status = result.get("status")
    new_ver = result.get("version", {}).get("number")
    print(f"[confluence] página actualizada → status={new_status}, version={new_ver}")
    print(f"[confluence] URL: {base_url}/spaces/"
          f"{meta.get('confluence_space', 'LDMCDK')}/pages/{page_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
