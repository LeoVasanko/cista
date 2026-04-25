import argparse
import mimetypes
from pathlib import Path

from cista.preview import process_image_with_timing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate image previews for all files in a folder, one at a time.",
    )
    parser.add_argument("folder", type=Path, help="Folder to scan recursively")
    parser.add_argument(
        "--px",
        type=int,
        default=1024,
        help="Maximum preview dimension in pixels (default: 1024)",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=60,
        help="AVIF quality passed to preview generation (default: 60)",
    )
    return parser.parse_args()


def is_image_file(path: Path) -> bool:
    mime_type, _ = mimetypes.guess_type(path.name)
    return bool(mime_type and mime_type.startswith("image/"))


def main() -> int:
    args = parse_args()
    folder = args.folder.resolve()
    if not folder.is_dir():
        raise SystemExit(f"Not a directory: {folder}")

    files = sorted(
        path for path in folder.rglob("*") if path.is_file() and is_image_file(path)
    )
    if not files:
        print(f"No image files found under {folder}")
        return 0

    total_files = 0
    total_bytes = 0
    total_timing_slots: list[float] = []
    total_preview_ms: float = 0.0
    failures = 0

    print(f"Scanning {folder}")
    print(f"Generating previews for {len(files)} image files")

    for path in files:
        total_files += 1
        rel = path.relative_to(folder)
        try:
            preview, timing = process_image_with_timing(
                path,
                maxsize=args.px,
                quality=args.quality,
            )
        except Exception as exc:
            failures += 1
            print(f"FAIL  {rel}  error={exc}")
            continue

        total_bytes += len(preview)
        timings = timing.timings or []
        if len(total_timing_slots) < len(timings):
            total_timing_slots.extend([0.0] * (len(timings) - len(total_timing_slots)))
        for i, value in enumerate(timings):
            total_timing_slots[i] += value
        total_ms = sum(timings)
        total_preview_ms += total_ms

        detail = " / ".join(f"{value:.1f}ms" for value in timings)
        if detail:
            detail = f"timings={detail}  total={total_ms:.1f}ms"
        else:
            detail = f"total={total_ms:.1f}ms"
        print(f"OK    {rel}  backend={timing.backend}  bytes={len(preview)}  {detail}")

    completed = total_files - failures
    print()
    print("Summary")
    print(f"  files={total_files}")
    print(f"  completed={completed}")
    print(f"  failed={failures}")
    print(f"  preview_bytes={total_bytes}")
    if completed:
        if total_timing_slots:
            for i, value in enumerate(total_timing_slots, start=1):
                print(f"  timing{i}_total_ms={value:.1f}")
        print(f"  preview_total_ms={total_preview_ms:.1f}")
        print(f"  preview_avg_ms={total_preview_ms / completed:.1f}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
