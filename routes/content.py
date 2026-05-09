"""Content Management Blueprint — /api/content/list, /api/content/delete, /api/content/rename."""
import os
from pathlib import Path
from flask import Blueprint, jsonify, request
from core_app import ROOT, load_cfg

bp = Blueprint("content", __name__)

def get_download_dir():
    cfg = load_cfg()
    dpath = cfg.get("path", "./Downloaded/")
    p = Path(dpath)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()

@bp.route("/api/content/list", methods=["GET"])
def list_content():
    try:
        ddir = get_download_dir()
        if not ddir.exists():
            return jsonify({"ok": True, "files": []})
            
        files = []
        for entry in os.scandir(ddir):
            if entry.is_file():
                st = entry.stat()
                files.append({
                    "name": entry.name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "ext": Path(entry.name).suffix.lower(),
                    "path": str(Path(entry.path).relative_to(ROOT))
                })
        
        # Sort by mtime descending
        files.sort(key=lambda x: x["mtime"], reverse=True)
        return jsonify({"ok": True, "files": files})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.route("/api/content/delete", methods=["POST"])
def delete_content():
    try:
        data = request.json or {}
        filename = data.get("filename")
        if not filename:
            return jsonify({"ok": False, "error": "No filename provided"}), 400
            
        ddir = get_download_dir()
        fpath = ddir / filename
        
        if not fpath.exists() or not fpath.is_file():
            return jsonify({"ok": False, "error": "File not found"}), 404
            
        fpath.unlink()
        return jsonify({"ok": True, "message": f"Đã xóa {filename}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.route("/api/content/rename", methods=["POST"])
def rename_content():
    try:
        data = request.json or {}
        old_name = data.get("old_name")
        new_name = data.get("new_name")
        
        if not old_name or not new_name:
            return jsonify({"ok": False, "error": "Names missing"}), 400
            
        ddir = get_download_dir()
        old_path = ddir / old_name
        new_path = ddir / new_name
        
        if not old_path.exists():
            return jsonify({"ok": False, "error": "Original file not found"}), 404
        if new_path.exists():
            return jsonify({"ok": False, "error": "Destination file already exists"}), 400
            
        old_path.rename(new_path)
        return jsonify({"ok": True, "message": f"Đã đổi tên thành {new_name}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
