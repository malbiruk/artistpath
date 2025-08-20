import json
from pathlib import Path

from normalization import clean_str, normalize_str, to_slug
from rich.progress import track


def build_lookups(metadata_file: Path | str) -> dict:
    """Build lookup dictionaries from NDJSON metadata file."""
    metadata_path = Path(metadata_file)
    lookups = {"clean": {}, "normalized": {}, "slug": {}}

    with metadata_path.open() as f:
        # Get total for progress bar (quick count)
        total = sum(1 for _ in f)
        f.seek(0)  # Reset to beginning

        # Process with progress bar
        for line in track(f, description="[green]Building lookups...", total=total):
            if not line.strip():
                continue

            entry = json.loads(line)
            mbid = entry["id"]
            name = entry["name"]

            # Skip tag entries if present
            if mbid.startswith("tag:"):
                continue

            # Build different lookup variations
            clean_name = clean_str(name)
            lookups["clean"][clean_name] = mbid
            lookups["normalized"][normalize_str(clean_name)] = mbid
            lookups["slug"][to_slug(clean_name)] = mbid

    return lookups


def save_lookups(lookups: dict, output_file: Path | str) -> None:
    with Path(output_file).open("w") as f:
        json.dump(lookups, f, indent=4)


def main() -> None:
    metadata_file = Path("../data/metadata.ndjson")
    output_file = Path("../data/lookups.json")

    print(f"🎵 Building artist name lookups from {metadata_file}")

    lookups = build_lookups(metadata_file)

    print("\n✅ Created lookups:")
    artist_count = 0
    for lookup_type, lookup_dict in lookups.items():
        count = len(lookup_dict)
        artist_count = max(artist_count, count)
        print(f"   {lookup_type}: {count:,} entries")

    print(f"\n💾 Saving to {output_file}")
    save_lookups(lookups, output_file)

    print(f"🎉 Done! Processed {artist_count:,} artists")


if __name__ == "__main__":
    main()
