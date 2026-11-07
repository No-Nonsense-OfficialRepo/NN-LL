"""Build the original glass SVGs. Run bake_glass_materials.py to refresh the runtime textures."""
from math import cos, sin, sqrt, log, pi, exp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "lantool/qt/assets"
PHI = (1 + sqrt(5)) / 2
FOCUS = (1920 / PHI, 1080 / PHI**2)
# A logarithmic golden spiral grows by phi with every quarter turn.
# Only a broad, soft sweep is painted: no guide lines or circular spotlights.
points = []
for step in range(241):
    angle = -pi / 2 + step / 240 * 4 * pi
    radius = 32 * exp(log(PHI) * (angle + pi / 2) / (pi / 2))
    points.append((FOCUS[0] + radius * cos(angle), FOCUS[1] + radius * sin(angle)))
curve = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points)

palettes = [
    (ROOT / "pearl-glass.svg", "#D2D7DC", "#F8FAFB", "#E4E9ED", "#FFFFFF", .035),
    (ROOT / "themes/dark/glass.svg", "#0F0F11", "#242429", "#141417", "#8E9096", .009),
    (ROOT / "themes/neon/glass.svg", "#0C0618", "#251142", "#120A23", "#B04DFF", .012),
]
for path, base, light, edge, sheen, strength in palettes:
    layers = []
    for index in range(18):
        width = 1500 * PHI ** (-index / 3)
        opacity = strength * exp(-((index - 5) / 8) ** 2)
        layers.append(f'<use href="#golden-sweep" stroke-width="{width:.2f}" stroke-opacity="{opacity:.5f}"/>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1920" height="1080" viewBox="0 0 1920 1080" preserveAspectRatio="none">
<!-- phi={PHI:.12f}; focal point=(61.8034%,38.1966%); quarter-turn growth=phi. -->
<defs>
 <linearGradient id="golden-field" x1="0" y1="1" x2="1" y2="0">
  <stop stop-color="{base}"/><stop offset="{1/PHI**2:.9f}" stop-color="{edge}"/>
  <stop offset="{1/PHI:.9f}" stop-color="{light}"/><stop offset="1" stop-color="{edge}"/>
 </linearGradient>
 <path id="golden-sweep" d="{curve}"/>
</defs>
<path fill="url(#golden-field)" d="M0 0h1920v1080H0z"/>
<g fill="none" stroke="{sheen}" stroke-linecap="round" stroke-linejoin="round">
{chr(10).join(layers).replace('href=', 'xlink:href=')}
</g>
</svg>
'''
    path.write_text(svg, encoding="utf-8")
    print(path.relative_to(ROOT))
