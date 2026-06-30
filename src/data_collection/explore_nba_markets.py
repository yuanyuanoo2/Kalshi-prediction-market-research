"""
Phase -1b 探索脚本：找 NBA 市场 ticker，不预设 schema，完整打印原始 response。
只调用 public GET 端点，不需要认证。
"""

import requests
import json
import time

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
# 备用: https://trading-api.kalshi.com/trade-api/v2
#       https://external-api.kalshi.com/trade-api/v2


def get(path, params=None):
    url = BASE_URL + path
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main():
    # Step 1: 看 /series 端点，找 NBA 相关 series_ticker
    print("=" * 60)
    print("STEP 1: GET /series (前20条)")
    print("=" * 60)
    data = get("/series", params={"limit": 20})
    print(json.dumps(data, indent=2))
    print()

    # Step 2: 搜索包含 "NBA" 或 "basketball" 关键字的 series
    print("=" * 60)
    print("STEP 2: GET /series?category= 或 title 关键字过滤")
    print("=" * 60)
    # 尝试 category 参数（文档未说明是否支持，先试）
    for kw in ["nba", "basketball", "NBA"]:
        try:
            data = get("/series", params={"limit": 100})
            series_list = data.get("series", [])
            matches = [s for s in series_list if kw.lower() in json.dumps(s).lower()]
            if matches:
                print(f"Keyword '{kw}' matches {len(matches)} series:")
                for s in matches[:5]:
                    print(json.dumps(s, indent=2))
        except Exception as e:
            print(f"Error with keyword {kw}: {e}")
    print()

    # Step 3: GET /events?category=sports 或类似过滤
    print("=" * 60)
    print("STEP 3: GET /events (前5条，看 schema)")
    print("=" * 60)
    try:
        data = get("/events", params={"limit": 5})
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}")
    print()

    # Step 4: GET /historical/cutoff 确认数据分界时间戳
    print("=" * 60)
    print("STEP 4: GET /historical/cutoff")
    print("=" * 60)
    try:
        data = get("/historical/cutoff")
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
