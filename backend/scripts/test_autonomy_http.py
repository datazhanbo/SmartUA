"""Phase 4 主动自治 — 真实 HTTP 端到端验证。

启动说明：先 `uvicorn main:app --port 8000` 再运行本脚本（或让本脚本配合后台 uvicorn）。
本脚本只负责用 HTTP 打穿：登录 → 状态 → 手动巡检 → 审批一条待批提案 → 查看告警流 → 启停调度。
"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = "agenttest@demo.com"
PASSWORD = "test1234"


def _req(method, path, data=None, token=None, params=""):
    url = BASE + path + params
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "detail": e.read().decode()[:200]}


def ensure_user():
    """确保存在测试用户（幂等）。"""
    from app.db.base import SessionLocal
    from app.models.sys import User
    from passlib.context import CryptContext
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == EMAIL).first()
        if u is None:
            pwd = CryptContext(schemes=["bcrypt"]).hash(PASSWORD)
            u = User(email=EMAIL, username="agenttest", hashed_password=pwd,
                     role="admin", is_active=True)
            db.add(u)
            db.commit()
            print("  · 已创建测试用户", EMAIL)
        else:
            print("  · 测试用户已存在", EMAIL)
    finally:
        db.close()


def main():
    ensure_user()
    r = _req("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    if "__error__" in r:
        print("登录失败：", r); return
    token = r["access_token"]
    print("✅ 登录成功")

    print("\n[1] 主动自治状态：")
    print("   ", _req("GET", "/agent/autonomy/status", token=token))

    print("\n[2] 手动触发一次主动巡检：")
    res = _req("POST", "/agent/autonomy/scan", {}, token=token, params="?app_id=1")
    if "__error__" in res:
        print("   巡检失败：", res); return
    print("    扫描摘要：", res["summary"])
    print("    告警：")
    for a in res["alerts"]:
        an = a["anomaly"]
        print(f"      - [{a['status']}] {an['severity']:<8} {an['title']}")

    pend = [a for a in res["alerts"] if a["status"] == "pending_approval"]
    if pend:
        a = pend[0]
        print(f"\n[3] 审批一条待批提案（{a['anomaly']['title']}）：")
        ap = _req("POST", f"/agent/sessions/{a['session_id']}/approve",
                  {"step_id": a["step_id"], "approved": True}, token=token)
        print("    会话状态 →", ap.get("status"))

        print("\n[4] 审批后告警流：")
        al = _req("GET", "/agent/autonomy/alerts", token=token, params="?app_id=1")
        for x in al:
            print(f"      - {x['anomaly']['title']} → {x['status']}")

    print("\n[5] 启停调度：")
    print("    关闭：", _req("POST", "/agent/autonomy/toggle", {}, token=token, params="?enabled=false"))
    print("    开启：", _req("POST", "/agent/autonomy/toggle", {}, token=token, params="?enabled=true"))
    print("\n= Phase 4 HTTP 端到端验证完成 =")


if __name__ == "__main__":
    main()
