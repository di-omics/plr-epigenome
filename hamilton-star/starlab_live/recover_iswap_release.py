import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck


async def main():
    print("Initializing STAR for iSWAP release recovery...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Trying to open/release iSWAP gripper...")

        backend = lh.backend

        # Try likely low-level release/open methods if present.
        for method_name in [
            "iswap_open_gripper",
            "open_iswap_gripper",
            "iswap_release",
            "release_iswap",
        ]:
            if hasattr(backend, method_name):
                print(f"Calling {method_name}()...")
                method = getattr(backend, method_name)
                await method()
                print(f"{method_name}() completed.")
                break
        else:
            print("No direct iSWAP open/release method found on backend.")
            print("Available iSWAP-ish methods:")
            for name in dir(backend):
                if "iswap" in name.lower() or "grip" in name.lower():
                    print(" ", name)

        print("Trying to park iSWAP...")
        try:
            await backend.park_iswap()
            print("iSWAP parked.")
        except Exception as e:
            print(f"park_iswap warning: {e!r}")

    finally:
        print("Stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
