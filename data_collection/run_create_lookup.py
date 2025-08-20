import json
from pathlib import Path

from normalization import clean_str
from rich.progress import track


def build_lookup(metadata_file: Path | str) -> dict:
    """Build clean name lookup dictionary from NDJSON metadata file."""
    metadata_path = Path(metadata_file)
    lookup = {}

    with metadata_path.open() as f:
        # Get total for progress bar (quick count)
        total = sum(1 for _ in f)
        f.seek(0)  # Reset to beginning

        # Process with progress bar
        for line in track(f, description="[green]Building lookup...", total=total):
            if not line.strip():
                continue

            entry = json.loads(line)
            mbid = entry["id"]
            name = entry["name"]

            # Build only clean lookup
            clean_name = clean_str(name)
            lookup[clean_name] = mbid

    return lookup


def save_lookups(lookups: dict, output_file: Path | str) -> None:
    with Path(output_file).open("w") as f:
        json.dump(lookups, f, indent=4)


def main() -> None:
    metadata_file = Path("../data/metadata.ndjson")
    output_file = Path("../data/lookup.json")

    print(f"🎵 Building artist name lookup from {metadata_file}")

    lookup = build_lookup(metadata_file)

    print(f"\n✅ Created lookup with {len(lookup):,} entries")

    print(f"\n💾 Saving to {output_file}")
    save_lookups(lookup, output_file)

    print(f"🎉 Done! Processed {len(lookup):,} artists")


if __name__ == "__main__":
    main()
