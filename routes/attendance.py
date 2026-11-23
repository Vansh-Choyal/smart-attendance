from datetime import date

from flask import Blueprint, current_app, jsonify, request

from services.attendance_service import AttendanceError
from services.auth import operator_required

bp = Blueprint("attendance_api", __name__)


def selected_day():
    raw = request.args.get("date")
    return date.fromisoformat(raw) if raw else None


@bp.post("/api/attendance/mark")
@operator_required
def mark():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error={"code":"invalid_body","message":"Provide a JSON object."}),400
    try:
        result = current_app.extensions["attendance"].mark(payload.get("session_id"))
        return jsonify(ok=True, data=result), 201
    except AttendanceError as error:
        return jsonify(ok=False, error={"code": error.code, "message": error.message}), error.status


@bp.get("/api/attendance/stats")
def stats():
    return jsonify(ok=True, data=current_app.extensions["database"].stats(selected_day()))


@bp.get("/api/attendance/events")
def events():
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    before = int(request.args["before"]) if request.args.get("before") else None
    return jsonify(ok=True, data={"events": current_app.extensions["database"].events(selected_day(), limit, before)})


@bp.get("/api/attendance/weekly")
def weekly():
    return jsonify(ok=True, data={"days": current_app.extensions["database"].weekly(selected_day())})


@bp.post("/api/attendance/reset")
@operator_required
def reset():
    service = current_app.extensions["attendance"]
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):
        return jsonify(ok=False,error={"code":"invalid_body","message":"Provide a JSON object."}),400
    if payload.get("confirm_date") != service.database.today().isoformat():
        return jsonify(ok=False, error={"code": "confirmation_required", "message": "Confirm today's date before resetting attendance."}), 400
    with service.lock:
        deleted = service.database.reset()
        service.invalidate()
    return jsonify(ok=True, data={"deleted": deleted, "stats": service.database.stats()})
