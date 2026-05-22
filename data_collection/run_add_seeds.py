"""Add seed artists from diverse genres to expand graph coverage."""

import asyncio

from collection.seeds import SEED_GROUPS, add_seeds_to_queue


async def main() -> None:
    all_seeds = []
    for group_name, seeds in SEED_GROUPS.items():
        print(f"\n📂 {group_name}: {len(seeds)} artists")
        all_seeds.extend(seeds)

    print(f"\n🚀 Adding {len(all_seeds)} potential seeds...")
    await add_seeds_to_queue(all_seeds)


if __name__ == "__main__":
    asyncio.run(main())
