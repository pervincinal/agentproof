#!/usr/bin/env python3
"""Lokal onizleme — Render-in temiz URL davranisini tekrarlayir.

NIYE VAR: Render statik saytlari `.html` uzantisini kesir. `/rules` isleyir,
`/rules.html` ise 404 verir. Adi `python -m http.server` bunun tam eksini edir.
Bu ferq bir defe bizi tutdu: lokal onizlemede butun linkler islemisdi, canli
saytda ise naviqasiya tamamile sinmisdi ve bunu yalniz curl gosterdi.

Bu handler ferqi baglayir ki, lokal onizleme ile istehsalat eyni sey desin.

    python3 site/_dev_server.py [port]
"""

import functools
import http.server
import os
import sys


class CleanURLHandler(http.server.SimpleHTTPRequestHandler):
    """`/rules` -> `rules.html`; `/rules.html` -> 301 `/rules`."""

    def translate_path(self, path):
        local = super().translate_path(path)
        if os.path.isdir(local) or os.path.exists(local):
            return local
        # Uzantisiz yol: eyni adli .html faylini axtar.
        if not os.path.splitext(local)[1]:
            candidate = local + ".html"
            if os.path.isfile(candidate):
                return candidate
        return local

    def send_head(self):
        # `.html` ile gelen sorgunu temiz URL-e yonlendir — Render de bunu edir
        # (orada 404 gelir; burada 301 daha faydalidir, cunki sinmis linki
        # brauzerin unvan sətrinde gorursen).
        raw = self.path.split("?", 1)[0].split("#", 1)[0]
        if raw.endswith(".html"):
            target = raw[: -len(".html")]
            if target.endswith("/index"):
                target = target[: -len("index")]
            self.send_response(301)
            self.send_header("Location", target or "/")
            self.end_headers()
            return None
        return super().send_head()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    root = os.path.dirname(os.path.abspath(__file__))
    handler = functools.partial(CleanURLHandler, directory=root)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"site/ -> http://localhost:{port}  (Render kimi temiz URL)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
