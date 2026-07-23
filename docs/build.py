from pathlib import Path

import pdoc

source_dir = Path(__file__).parents[1] / "src"
dist_dir = Path(__file__).parents[1] / "dist" / "docs"

pdoc.render.configure(docformat="numpy")
pdoc.pdoc(
    source_dir / "datam8_model",
    source_dir / "datam8",
    output_directory=dist_dir,
)
