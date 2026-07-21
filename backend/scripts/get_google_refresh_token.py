#!/usr/bin/env python3
"""获取 Google Ads API 的 refresh_token（离线访问用，连接器靠它免浏览器调用）。

前置：
  1) pip install google-auth-oauthlib
  2) 把你的 OAuth 客户端 JSON 路径作为第 1 个参数传入（Desktop app 类型）。

运行（全自动，推荐在能开浏览器的本机执行）：
  python get_google_refresh_token.py /path/to/client_secret_xxx.json
  # 或把 JSON 放到本目录下的 client_secret.json 后直接：python get_google_refresh_token.py

运行（手动兜底，无浏览器/localhost 被拦时）：
  python get_google_refresh_token.py /path/to/client_secret_xxx.json --manual
  # 脚本打印授权 URL -> 你在浏览器登录授权 -> 地址栏出现 ?code=XXXX 复制 -> 粘回终端 -> 自动换 refresh_token

行为：
  - 授权后用 offline 模式拿到长效 refresh_token（运行时靠它离线调用，无需浏览器）。
  - 把 refresh_token 存入 backend/.env 的 GOOGLE_REFRESH_TOKEN= 即可。

注意：
  - 客户端类型须为「桌面应用」，redirect_uris 含 http://localhost（脚本用 http://localhost:8080 回调，
    Google 对 installed app 允许任意 localhost 端口）。
  - 若要 refresh_token 长期有效（不 7 天过期），请到 Google Cloud「OAuth 同意屏幕」把发布状态设为「生产」。
"""
import sys

SCOPES = ["https://www.googleapis.com/auth/adwords"]
DEFAULT_SECRET = "client_secret.json"


def build_flow(secret: str):
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(secret, scopes=SCOPES)
    flow.redirect_uri = "http://localhost:8080"
    return flow


def auto_mode(flow):
    print("正在打开浏览器进行 Google Ads 授权……（若未自动打开，请手动访问下方 URL）")
    print(f"\n授权 URL：\n{flow.authorization_url(prompt='consent', access_type='offline')[0]}\n")
    try:
        creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")
    except Exception as e:
        # 回退到手动模式
        print(f"[!] 自动回调失败（{e}），切换到手动模式……")
        return manual_mode(flow)
    return creds


def manual_mode(flow):
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    print("\n=== 请在浏览器打开下面的 URL 并登录授权 ===")
    print(auth_url)
    print("\n授权后浏览器会跳到 http://localhost:8080/... （页面可能打不开，没关系）")
    print("请把地址栏里 ?code= 后面的那串复制下来粘到这里：")
    code = input("code> ").strip()
    if not code:
        sys.exit("未输入 code，已退出。")
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        sys.exit(f"用 code 换 token 失败：{e}")
    return flow.credentials


def main():
    args = sys.argv[1:]
    secret = None
    manual = False
    for a in args:
        if a == "--manual":
            manual = True
        elif not a.startswith("-"):
            secret = a
    if secret is None:
        secret = DEFAULT_SECRET

    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        sys.exit("缺少依赖，请先安装：pip install google-auth-oauthlib")

    try:
        flow = build_flow(secret)
    except FileNotFoundError:
        sys.exit(f"找不到客户端 JSON：{secret}")
    except Exception as e:
        sys.exit(f"解析客户端 JSON 失败：{e}")

    creds = manual_mode(flow) if manual else auto_mode(flow)

    rt = getattr(creds, "refresh_token", None)
    if not rt:
        sys.exit("未获取到 refresh_token（请确认 OAuth 同意屏幕发布状态为「生产」，或授权时勾选了离线访问）。")

    print("\n=== 取得的 refresh_token ===")
    print(rt)
    print("\n请把上面这串值填入 backend/.env：")
    print(f"GOOGLE_REFRESH_TOKEN={rt}")


if __name__ == "__main__":
    main()
