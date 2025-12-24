"""Utilities for orchestrating USD shot handoffs between DCCs.

The helpers in this module are designed for archviz studios working across
Cinema 4D, Nuke, Unreal, Anima, and other DCCs that speak USD.  They provide a
lightweight way to describe which application is responsible for each USD
layer, normalise frame ranges, and generate a Deadline-friendly payload for
automation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Literal

from .models import JSONValue, SupportedDCC
from .utils import FrameRange, normalize_frame_range, sanitize_token

LayerRole = Literal["layout", "lighting", "animation", "lookdev", "crowd", "comp"]


@dataclass(slots=True)
class USDLayerContribution:
    """Describe how a single DCC contributes to a USD stage.

    Attributes
    ----------
    dcc:
        The DCC responsible for authoring the layer (e.g. Cinema4D, Nuke,
        Unreal, Anima).
    role:
        The discipline covered by the layer such as ``"layout"`` or
        ``"lighting"``.  This is kept broad to work across DCCs.
    layer_path:
        Path to the USD layer produced by the DCC.
    prim_path:
        The prim path that the DCC authors within the composed stage.
    frame_range:
        Optional frame range for time-sampled layers.
    render_product:
        Optional render product identifier that downstream tools (e.g. Nuke or
        Deadline integration) can consume.
    description:
        Free-form human readable context for scheduling dashboards.
    """

    dcc: SupportedDCC
    role: LayerRole
    layer_path: Path
    prim_path: str
    frame_range: FrameRange | None = None
    render_product: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if self.frame_range is not None:
            self.frame_range = normalize_frame_range(self.frame_range)

        prim = self.prim_path.strip()
        if not prim:
            raise ValueError("prim_path cannot be empty")
        if not prim.startswith("/"):
            prim = f"/{prim}"
        self.prim_path = prim

    def as_dict(self, stage_root: Path) -> dict[str, JSONValue]:
        """Return a serialisable dictionary for manifests and queues."""

        try:
            relative_layer = str(self.layer_path.relative_to(stage_root))
        except ValueError:
            relative_layer = str(self.layer_path)

        payload: dict[str, JSONValue] = {
            "dcc": self.dcc.value,
            "role": self.role,
            "layer": relative_layer,
            "prim": self.prim_path,
        }

        if self.frame_range:
            payload["frame_range"] = list(self.frame_range)
        if self.render_product:
            payload["render_product"] = self.render_product
        if self.description:
            payload["description"] = self.description

        return payload


@dataclass(slots=True)
class USDShotPlan:
    """Structured plan describing how a USD shot is composed across DCCs."""

    show: str
    shot: str
    root_layer: Path
    contributions: list[USDLayerContribution] = field(default_factory=list)
    version: str = "v001"
    destination: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.contributions:
            raise ValueError("At least one USDLayerContribution is required")

        show_token = sanitize_token(self.show, fallback="SHOW")
        shot_token = sanitize_token(self.shot, fallback="SHOT")
        self.show = show_token
        self.shot = shot_token
        self.contributions = list(self.contributions)

    @property
    def stage_root(self) -> Path:
        """Return the directory containing ``root_layer``."""

        return self.root_layer.parent

    def manifest(self) -> dict[str, Any]:
        """Return a JSON-friendly manifest describing the USD shot."""

        layers = [
            contribution.as_dict(self.stage_root) for contribution in self.contributions
        ]

        manifest: dict[str, Any] = {
            "show": self.show,
            "shot": self.shot,
            "version": self.version,
            "root_layer": str(self.root_layer),
            "contributions": layers,
        }

        if self.destination:
            manifest["destination"] = self.destination
        if self.notes:
            manifest["notes"] = self.notes

        return manifest

    def deadline_payload(
        self,
        *,
        queue: str,
        pool: str,
        priority: int = 50,
        batch_name: str | None = None,
        group: str | None = "usd",
        props: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return a Deadline-ready payload for a USD publish or review job."""

        manifest = self.manifest()
        deadline_batch = batch_name or f"{self.show}_{self.shot}_usd"
        manifest_payload = json.dumps(manifest, indent=2)
        extra_info = [
            f"show={self.show}",
            f"shot={self.shot}",
            f"version={self.version}",
        ]

        if props:
            extra_info.extend(f"{key}={value}" for key, value in props.items())

        job_info = {
            "Name": f"USD {self.show}/{self.shot} {self.version}",
            "BatchName": deadline_batch,
            "Pool": pool,
            "SecondaryPool": queue,
            "Group": group or "usd",
            "Priority": priority,
            "Plugin": "CommandLine",
            "Comment": self.notes or "USD handoff orchestrated by OnePiece",
            "ExtraInfoKeyValue": extra_info,
        }

        plugin_info = {
            "Executable": "python",
            "Arguments": (
                '-c "import json,sys;\n'
                "data=json.load(sys.stdin);\n"
                'print(json.dumps(data, indent=2))"'
            ),
            "StdInData": manifest_payload,
            "StartupDirectory": str(self.stage_root),
        }

        return {"JobInfo": job_info, "PluginInfo": plugin_info, "AuxFiles": []}


def build_usd_plan(
    *,
    show: str,
    shot: str,
    root_layer: Path,
    contributions: Iterable[USDLayerContribution],
    version: str = "v001",
    destination: str | None = None,
    notes: str | None = None,
) -> USDShotPlan:
    """Convenience helper to assemble a :class:`USDShotPlan`.

    The helper accepts any iterable of contributions making it easy to collate
    Cinema 4D layout, Anima crowds, Unreal lighting, and Nuke slap comps into a
    single plan that downstream automation can consume.
    """

    return USDShotPlan(
        show=show,
        shot=shot,
        root_layer=root_layer,
        contributions=list(contributions),
        version=version,
        destination=destination,
        notes=notes,
    )


__all__ = ["USDLayerContribution", "USDShotPlan", "build_usd_plan", "LayerRole"]
