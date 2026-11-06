
from __future__ import annotations

import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.mcp_server import mcp

BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
RESET  = "\033[0m"


def pp(label: str, data: dict) -> None:
    status = GREEN + "[OK]" + RESET if data.get("success") else RED + "[HATA]" + RESET
    print(f"  {status} {label}")
    for k, v in data.items():
        if k != "success":
            print(f"       {YELLOW}{k}{RESET}: {v}")
    print()



async def run_calc_tests():

    print(f"\n{'='*60}")
    print(f"{BOLD}FinSight MCP Server — Arac Testi{RESET}")
    print(f"{'='*60}")

    print(f"\n{BOLD}[1] Kayitli Araclar{RESET}")
    tools = await mcp.list_tools()
    for t in tools:
        print(f"  {GREEN}+{RESET} {CYAN}{t.name}{RESET}")
        desc_line = (t.description or "").splitlines()[0]
        print(f"      {desc_line}")
    print()

    print(f"{BOLD}[2] F/K Orani — Gecerli Girdi{RESET}")
    result = await mcp.call_tool("calculate_pe_ratio", {
        "stock_price": 285.50,
        "eps": 42.30,
    })
    _show(result)

    print(f"{BOLD}[3] F/K Orani — Negatif EPS (Hata Senaryosu){RESET}")
    try:
        result = await mcp.call_tool("calculate_pe_ratio", {
            "stock_price": 285.50,
            "eps": -5.0,
        })
        _show(result)
    except Exception as exc:
        err_line = str(exc).splitlines()[0]
        print(f"  {GREEN}[Beklenen Hata Yakalandi]{RESET} {YELLOW}{err_line}{RESET}\n")

    print(f"{BOLD}[4] PD/DD Orani{RESET}")
    result = await mcp.call_tool("calculate_pb_ratio", {
        "stock_price": 285.50,
        "book_value_per_share": 180.75,
    })
    _show(result)

    print(f"{BOLD}[5] Borc / Ozkaynak Orani{RESET}")
    result = await mcp.call_tool("calculate_debt_to_equity", {
        "total_debt": 150_000_000_000.0,
        "total_equity": 100_000_000_000.0,
    })
    _show(result)

    print(f"{BOLD}[6] Kar Marji + Baz Puan Degisimi{RESET}")
    result = await mcp.call_tool("calculate_margin", {
        "revenue": 500_000_000.0,
        "profit": 120_000_000.0,
        "previous_margin_pct": 20.5,
    })
    _show(result)

    print(f"{'='*60}")
    print(f"{GREEN}{BOLD}Tum hesaplama testleri tamamlandi!{RESET}")
    print(f"{'='*60}\n")


async def run_market_test():
    print(f"\n{BOLD}[7] Piyasa Verisi Cekme — THYAO.IS (Gercek API){RESET}")
    print(f"  {YELLOW}Not: Bu test gercek Yahoo Finance API'ye baglanir...{RESET}")
    result = await mcp.call_tool("fetch_market_data", {"ticker_symbol": "THYAO.IS"})
    _show(result)

    print(f"{BOLD}[8] Tam Analiz — THYAO.IS{RESET}")
    result = await mcp.call_tool("analyze_stock", {"ticker_symbol": "THYAO.IS"})
    _show(result)


def _show(result) -> None:
    try:
        if isinstance(result, list) and result:
            text = result[0].text if hasattr(result[0], "text") else str(result[0])
        else:
            text = str(result)
        data = json.loads(text)
        print("  " + json.dumps(data, ensure_ascii=False, indent=4).replace("\n", "\n  "))
    except Exception:
        print(f"  {result}")
    print()



if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "calc"

    async def main():
        await run_calc_tests()
        if mode == "full":
            try:
                await run_market_test()
            except Exception as exc:
                print(f"{RED}Piyasa API hatasi: {exc}{RESET}")

    asyncio.run(main())
