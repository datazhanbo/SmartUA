#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SmartUA - Google Ads 真实链路端到端验证脚本
============================================
运行环境要求:
  1. 已安装 SDK:   pip install google-ads
  2. 网络可达 Google (直连 或 经代理; 沙箱代理对 google 域名超时, 需在能连 google 的机器跑)
  3. backend/.env 已填 GOOGLE_CLIENT_ID/SECRET/DEVELOPER_TOKEN/REFRESH_TOKEN/CUSTOMER_ID 五项

用法:
  cd backend
  python3 scripts/verify_google_live.py            # 只读验证: 构建 client + pull 近 7 天数据
  python3 scripts/verify_google_live.py --apply     # 额外做一次真实写 (首个 campaign PAUSED->ENABLED 往返)

退出码: 0=链路通且拿到数据; 2=链路通但被权限/令牌挡 (凭证/网络 OK, 只差 Basic access); 3=网络或凭证错误
"""
import os
import sys
import argparse
from datetime import date, timedelta

# 脚本位于 backend/scripts/ -> 父目录即 backend 根, 加入 path 以便 import app
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

# gRPC 只认小写 http_proxy/https_proxy, 从环境同步 (若有)
for _k in ("HTTP_PROXY", "HTTPS_PROXY"):
    _v = os.environ.get(_k)
    if _v:
        os.environ.setdefault("http_proxy", _v)
        os.environ.setdefault("https_proxy", _v)


def report_api_error(e):
    """把 Google Ads / 网络异常翻译成可读诊断。

    注意: import 失败时 GoogleAdsException 置为 None, 避免 isinstance 误判所有异常。
    """
    try:
        from google.ads.googleads.exceptions import GoogleAdsException
    except Exception:
        GoogleAdsException = None

    name = type(e).__name__
    msg = str(e)

    if GoogleAdsException is not None and isinstance(e, GoogleAdsException) and hasattr(e, "failure"):
        print("  [GoogleAdsException] 收到 Google 结构化错误:")
        for err in e.failure.errors:
            code = err.error_code.name if hasattr(err, "error_code") else "?"
            print(f"    - code={code}")
            print(f"      msg ={err.message}")
        if "AuthorizationError" in msg or "CUSTOMER_NOT_FOUND" in msg or "USER_PERMISSION_DENIED" in msg:
            print("  => 诊断: 凭证链路已通, 但 developer_token 为 Test 级别 / 账户无权.")
            print("     解决: 在 Google Ads 后台 API Center 把访问权限升到 Basic access.")
            return 2
        if "QuotaError" in msg or "RATE_LIMIT" in msg:
            print("  => 诊断: 触发配额/限流, 稍后重试.")
            return 2
        print("  => 诊断: 见上方 Google 错误码.")
        return 2

    if "TransportError" in name or "ProxyError" in name or "Connection" in name or "timeout" in msg.lower():
        print(f"  [网络/代理错误] {name}")
        print("  => 诊断: 连不到 Google. 检查: 是否能直连 googleads.googleapis.com, 代理是否放行 Google 域名.")
        return 3

    print(f"  [其他错误] {name}: {msg[:400]}")
    return 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="额外做一次真实写动作 (首个 campaign PAUSED->ENABLED 往返)")
    ap.add_argument("--days", type=int, default=7, help="回看天数 (默认 7)")
    args = ap.parse_args()

    from app.config import settings
    from app.services.connectors import ConnectorFactory, resolve_credentials

    # 1) 凭证
    creds = resolve_credentials("google", db=None, app_id=1)
    need = ("client_id", "client_secret", "developer_token", "refresh_token", "customer_id")
    print("== 1. 凭证解析 (resolve_credentials) ==")
    print("  5 项齐全:", all(creds.get(k) for k in need), "| keys:", list(creds.keys()))
    if not all(creds.get(k) for k in need):
        print("  !! 凭证缺失, 请检查 backend/.env 的 GOOGLE_* 五项")
        return 3

    # 2) 连接器自动切换
    conn = ConnectorFactory.get_connector("google", db=None, app_id=1, credentials=creds, execution_mode="live")
    print("\n== 2. 连接器 ==")
    print("  类型:", type(conn).__name__, "| _is_mock:", conn._is_mock, "(False=真实路径)")

    # 3) auth(): 构建 client + 结构检查 (不触网)
    print("\n== 3. auth() 构建 client ==")
    try:
        print("  auth() ->", conn.auth())
    except Exception as e:
        print("  auth 构建异常:", type(e).__name__, str(e)[:200])

    # 4) 真实 pull(date_from, date_to)
    date_to = date.today()
    date_from = date_to - timedelta(days=args.days - 1)
    print(f"\n== 4. 真实 pull({date_from} .. {date_to}) ==")
    raw = []
    try:
        res = conn.pull(date_from, date_to)
        raw = res.get("raw_rows", [])
        mode = res.get("metadata", {}).get("mode")
        print("  pull 成功, mode:", mode, "| 行数:", len(raw))
        for r in raw[:3]:
            cost = int(r.get("metrics.cost_micros", 0)) / 1_000_000
            print("   -", r.get("campaign.id"), "|", r.get("campaign.name"),
                  "| spend=", round(cost, 2), "| conversions=", r.get("metrics.conversions"))
        print("\n  ✅✅ 真实链路打通, 已拿到 Google Ads 生产数据")
        rc = 0
    except Exception as e:
        rc = report_api_error(e)
        if rc == 2:
            print("\n  => 凭证/网络均 OK, 仅权限级别不够. 升 Basic access 后即可拿到数据.")

    # 5) 可选真实写 (PAUSED -> ENABLED 往返, 状态无残留变化)
    if args.apply and raw:
        cid = raw[0].get("campaign.id")
        print(f"\n== 5. 真实写动作 (--apply): campaign {cid} PAUSED -> ENABLED ==")
        r1 = conn.update_campaign_status(cid, "PAUSED")
        print("  PAUSED  :", r1)
        r2 = conn.update_campaign_status(cid, "ENABLED")
        print("  ENABLED :", r2)
        if not (r1.get("success") and r2.get("success")):
            err = r1.get("error") or r2.get("error") or ""
            print("  => 写动作返回失败, 诊断:", str(err)[:300])

    return rc


if __name__ == "__main__":
    sys.exit(main() or 0)
