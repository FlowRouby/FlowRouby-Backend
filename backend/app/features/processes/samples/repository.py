"""Source of the demo BPMN diagrams.

``SampleProcessRepository`` is the port the routes depend on. Today the only adapter reads the
``samples/bpmn`` folder; a database-backed adapter can replace it without touching the routes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Union

from ..services.process_service import ProcessImportService

SAMPLES_DIR_ENV = "SAMPLES_DIR"
SAMPLE_EXTENSION = ".bpmn"


@dataclass(frozen=True)
class SampleProcess:
    """Catalog entry of one demo diagram."""

    id: str
    filename: str
    name: str
    process_id: str


class SampleProcessRepository(Protocol):
    def list(self) -> List[SampleProcess]:
        """Every available sample, sorted by id."""
        ...

    def get_xml(self, sample_id: str) -> Optional[str]:
        """The BPMN XML of a sample, or ``None`` when the id is unknown."""
        ...


def default_samples_directory() -> Path:
    """``SAMPLES_DIR`` when set, otherwise ``<repo root>/samples/bpmn``."""
    override = os.environ.get(SAMPLES_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[5] / "samples" / "bpmn"


class FileSystemSampleProcessRepository:
    """Serves the ``*.bpmn`` files of one directory.

    Ids are resolved only against the files found in the directory, never joined into a path
    from caller input, so traversal is impossible.
    """

    def __init__(self, directory: Union[str, Path], import_service: Optional[ProcessImportService] = None):
        self._directory = Path(directory)
        self._import_service = import_service or ProcessImportService()

    def list(self) -> List[SampleProcess]:
        return [sample for sample, _ in self._scan().values()]

    def get_xml(self, sample_id: str) -> Optional[str]:
        entry = self._scan().get(sample_id)
        if entry is None:
            return None
        return entry[1]

    def _scan(self) -> Dict[str, "tuple[SampleProcess, str]"]:
        """Maps id -> (catalog entry, xml) for every importable file, sorted by id."""
        if not self._directory.is_dir():
            return {}
        found: Dict[str, "tuple[SampleProcess, str]"] = {}
        for path in sorted(self._directory.glob(f"*{SAMPLE_EXTENSION}")):
            if not path.is_file():
                continue
            try:
                xml = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            graph = self._import_service.import_single_bpmn(xml, filename=path.name).process
            if graph is None:
                continue
            sample = SampleProcess(
                id=path.stem,
                filename=path.name,
                name=graph.name or graph.process_id,
                process_id=graph.process_id,
            )
            found[sample.id] = (sample, xml)
        return found
