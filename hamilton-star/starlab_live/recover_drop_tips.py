import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

async def main():
    print("Initializing STAR for tip recovery...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    print("Trying to discard tips currently on channels...")
    try:
        await lh.discard_tips()
        print("Tip discard command completed.")
    except Exception as e:
        print("discard_tips failed:")
        print(repr(e))
        print("Tip state may not be known in this fresh Python process.")

    print("Stopping...")
    await lh.stop()
    print("Done.")

asyncio.run(main())
