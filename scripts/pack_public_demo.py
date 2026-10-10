"""Pack only the public build for parent-coordinated supported static hosting."""

import base64
import hashlib
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "web" / "dist-public"
output = root / "deliverables"
html = (source / "index.html").read_text(encoding="utf-8")
script_path = re.search(r'<script type="module"[^>]*src="([^"]+)"[^>]*></script>', html)
style_path = re.search(r'<link rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', html)
if not script_path or not style_path:
    raise SystemExit("build public GUI first: npm run build:public")
script = (source / script_path[1].lstrip("/")).read_text(encoding="utf-8")
style = (source / style_path[1].lstrip("/")).read_text(encoding="utf-8")
style = style.replace('@import"/fonts.css";', "")
script = re.sub(r"</script", r"<\\/script", script, flags=re.IGNORECASE)
html = html.replace(script_path[0], '<script type="module">' + script + "</script>")
html = html.replace(style_path[0], "<style>" + style + "</style>")
hashes = [
    base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() for text in [script, style]
]
csp = (
    "default-src 'none'; script-src 'sha256-"
    + hashes[0]
    + "'; style-src 'sha256-"
    + hashes[1]
    + "'; img-src data:; font-src 'none'; connect-src 'none'; base-uri 'none'; "
    "form-action 'none'; object-src 'none'"
)
html = html.replace(
    "<head>", '<head><meta http-equiv="Content-Security-Policy" content="' + csp + '">'
)
output.mkdir(exist_ok=True)
(output / "public-demo.html").write_text(html, encoding="utf-8")
print("deliverables/public-demo.html · public-only · CSP blocks all network connections")
