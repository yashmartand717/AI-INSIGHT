"""Package only integration source and tests. Never include credentials or data."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
destination = root / "dist" / "gyanbuddy-email-integration.zip"
destination.parent.mkdir(exist_ok=True)
files = [root / name for name in ("pyproject.toml", "requirements-integration.txt", "engine/__init__.py", "engine/analytics.py")]
for folder in ("gyanbuddy_insights", "flutter_example", "docs", "integration_tests"):
    files.extend(p for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".html", ".txt", ".md", ".dart"})
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for file in sorted(files):
        archive.write(file, file.relative_to(root).as_posix())
print(f"Built {destination.name}: {len(files)} files")
