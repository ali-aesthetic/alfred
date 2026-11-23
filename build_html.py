"""Собирает robot.html из robot_face.js и panels_ui.js."""
from pathlib import Path
H = Path(__file__).resolve().parent
head = '''<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden;width:100%;height:100%;user-select:none;-webkit-user-select:none;cursor:default}
#holo{position:fixed;right:0;bottom:0;width:280px;height:280px}
#panels{position:fixed;left:8px;top:8px;bottom:10px;right:290px;box-sizing:border-box}</style>
</head><body><div id="panels"></div><div id="holo"></div>
<script>'''
# The face is now the Alfred orb (orb_face.js). The old human face (robot_face.js + face_data.js) is kept but unused.
import base64 as _b64
import json as _json
try:
    _cfg = _json.loads((H / "config.json").read_text())
except Exception:
    _cfg = {}
_face = _cfg.get("face", "core")
if _face == "core":  # living amber core: Higgsfield film + three.js particles
    _film = H / ("core_loop_" + _cfg.get("core_film", "a") + ".mp4")
    _b = _b64.b64encode(_film.read_bytes()).decode() if _film.exists() else ""
    (H / "robot.html").write_text(head + (H / "panels_ui.js").read_text() + "</script>\n" +
                                  (H / "three.min.js").read_text().join(["<script>", "</script>\n"]) +
                                  f"<script>window.CORE_FILM_B64='{_b}';</script>\n<script>" +
                                  (H / "core_face.js").read_text() + "</script>\n</body></html>\n")
elif _face == "rings":  # look C in 3D: gyroscope of gold HUD rings
    (H / "robot.html").write_text(head + (H / "panels_ui.js").read_text() + "</script>\n" +
                                  (H / "three.min.js").read_text().join(["<script>", "</script>\n"]) + "<script>" +
                                  (H / "rings_face.js").read_text() + "</script>\n</body></html>\n")
else:  # the previous canvas orb
    (H / "robot.html").write_text(head + (H / "panels_ui.js").read_text() + "</script>\n<script>" +
                                  (H / "orb_face.js").read_text() + "</script>\n</body></html>\n")

(H / "stage.html").write_text((H / "stage_head.html").read_text() +
                              '<script src="three.min.js"></script>\n<script src="GLTFLoader.js"></script>\n<script src="DRACOLoader.js"></script>\n<script>' +
                              (H / "stage.js").read_text() + "</script>\n</body></html>\n")
