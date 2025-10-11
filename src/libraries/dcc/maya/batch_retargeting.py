"""Utilities for retargeting batches of mocap clips onto Maya character rigs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Sequence, Tuple
from uuid import uuid4

import pymel.core as pm
import structlog
from upath import UPath

log = structlog.get_logger(__name__)


class RetargetError(RuntimeError):
    """Raised when a batch retargeting job cannot be completed."""


@dataclass(slots=True)
class RetargetMapping:
    """Definition of how mocap joints map onto the target rig joints.

    The mapping uses the target rig joint name as the key and the mocap joint
    name as the value.  For example ``{"Hips": "root"}`` constrains the
    ``Hips`` joint on the rig to follow the ``root`` joint from the mocap clip.
    """

    joints: Mapping[str, str]


@dataclass(slots=True)
class RetargetResult:
    """Summary of a single clip retarget job."""

    source_clip: UPath
    output_scene: UPath
    constraints_applied: int
    baked_nodes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _create_namespace(prefix: str) -> str:
    """Create a unique Maya namespace and return its name."""

    namespace = f"{prefix}_{uuid4().hex[:8]}"
    pm.namespace(add=namespace)
    log.debug("maya_namespace_created", namespace=namespace)
    return namespace


def _import_clip(path: UPath, namespace: str) -> None:
    """Import a mocap clip into the current Maya scene."""

    if not path.exists():
        raise FileNotFoundError(path)

    pm.importFile(  # type: ignore[no-untyped-call]
        str(path),
        namespace=namespace,
        mergeNamespacesOnClash=False,
        preserveReferences=True,
    )
    log.info("maya_mocap_clip_imported", clip=str(path), namespace=namespace)


def _apply_constraints(
    mapping: Mapping[str, str],
    source_ns: str,
    target_ns: str | None,
) -> Tuple[List[Tuple[pm.nt.ParentConstraint, pm.nt.DependNode]], List[str]]:
    """Create parent constraints from mocap joints to rig joints."""

    constraints: List[Tuple[pm.nt.ParentConstraint, pm.nt.DependNode]] = []
    warnings: List[str] = []

    for target_joint, source_joint in mapping.items():
        source_name = f"{source_ns}:{source_joint}"
        target_name = (
            f"{target_joint}" if target_ns is None else f"{target_ns}:{target_joint}"
        )

        try:
            source_node = pm.PyNode(source_name)
            target_node = pm.PyNode(target_name)
        except pm.MayaNodeError:
            warning = f"Missing nodes for mapping {source_name} -> {target_name}"
            warnings.append(warning)
            log.warning(
                "maya_retarget_joint_missing",
                source=source_name,
                target=target_name,
            )
            continue

        constraint = pm.parentConstraint(
            source_node,
            target_node,
            maintainOffset=False,
            weight=1.0,
        )
        constraints.append((constraint, target_node))  # type: ignore[arg-type]
        log.debug(
            "maya_retarget_constraint_created",
            source=source_node.name(),  # type: ignore[attr-defined]
            target=target_node.name(),  # type: ignore[attr-defined]
            constraint=constraint.name(),
        )

    return constraints, warnings


def _clear_namespace(namespace: str) -> None:
    """Delete all nodes within the namespace and remove it."""

    nodes = pm.ls(f"{namespace}:*", long=True)
    if nodes:
        try:
            pm.delete(nodes)
        except pm.MayaCommandError as exc:  # type: ignore[attr-defined]
            log.warning(
                "maya_namespace_delete_failed",
                namespace=namespace,
                error=str(exc),
            )

    if pm.namespace(exists=namespace):
        try:
            pm.namespace(removeNamespace=namespace, mergeNamespaceWithRoot=False)
            log.debug("maya_namespace_removed", namespace=namespace)
        except pm.MayaCommandError as exc:  # type: ignore[attr-defined]
            log.warning(
                "maya_namespace_remove_failed",
                namespace=namespace,
                error=str(exc),
            )


def _bake_animation(
    nodes: Iterable[pm.nt.DependNode], frame_range: tuple[float, float] | None
) -> List[str]:
    """Bake animation from constraints onto the target nodes."""

    node_names = [node.name() for node in nodes]

    if not node_names:
        return []

    if frame_range is None:
        start = pm.playbackOptions(query=True, min=True)
        end = pm.playbackOptions(query=True, max=True)
    else:
        start, end = frame_range

    pm.bakeResults(
        node_names,
        t=(start, end),
        simulation=True,
        sampleBy=1,
        attribute=[
            "tx",
            "ty",
            "tz",
            "rx",
            "ry",
            "rz",
            "sx",
            "sy",
            "sz",
        ],
        preserveOutsideKeys=True,
        minimizeRotation=True,
        disableImplicitControl=True,
        controlPoints=False,
    )

    log.info(
        "maya_retarget_bake_complete",
        nodes=node_names,
        start=start,
        end=end,
    )
    return node_names


class BatchRetargetingTool:
    """Apply mocap data to one or more Maya rigs in sequence."""

    def __init__(
        self,
        rig_scene: UPath,
        mapping: RetargetMapping,
        output_directory: UPath,
        rig_namespace: str | None = None,
        frame_range: tuple[float, float] | None = None,
    ) -> None:
        self._rig_scene = rig_scene
        self._mapping = mapping
        self._output_directory = output_directory
        self._rig_namespace = rig_namespace
        self._frame_range = frame_range

        if not self._rig_scene.exists():
            raise FileNotFoundError(self._rig_scene)

        self._output_directory.mkdir(parents=True, exist_ok=True)

    def process(self, mocap_clips: Sequence[UPath]) -> List[RetargetResult]:
        """Retarget a sequence of mocap clips onto the configured rig."""

        results: List[RetargetResult] = []

        for clip in mocap_clips:
            result = self._process_clip(clip)
            results.append(result)

        return results

    def _process_clip(self, clip: UPath) -> RetargetResult:
        if not clip.exists():
            raise FileNotFoundError(clip)

        pm.newFile(force=True)  # type: ignore[no-untyped-call]
        pm.openFile(str(self._rig_scene), force=True)  # type: ignore[no-untyped-call]
        log.info("maya_rig_scene_loaded", path=str(self._rig_scene))

        mocap_namespace = _create_namespace("mocap")

        try:
            _import_clip(clip, mocap_namespace)
            constrained, warnings = _apply_constraints(
                self._mapping.joints,
                source_ns=mocap_namespace,
                target_ns=self._rig_namespace,
            )

            if not constrained:
                raise RetargetError(
                    f"No constraints were created for clip '{clip.name}'"
                )

            target_nodes = [target for _, target in constrained]
            baked_nodes = _bake_animation(target_nodes, self._frame_range)

            pm.delete([constraint for constraint, _ in constrained])
            log.debug("maya_retarget_constraints_deleted", count=len(constrained))

            _clear_namespace(mocap_namespace)

            output_path = self._output_directory / f"{clip.stem}_retargeted.ma"
            pm.saveAs(str(output_path))
            log.info("maya_retarget_scene_saved", path=str(output_path))

            return RetargetResult(
                source_clip=clip,
                output_scene=output_path,
                constraints_applied=len(constrained),
                baked_nodes=baked_nodes,
                warnings=warnings,
            )

        finally:
            if pm.namespace(exists=mocap_namespace):
                _clear_namespace(mocap_namespace)


__all__ = [
    "BatchRetargetingTool",
    "RetargetError",
    "RetargetMapping",
    "RetargetResult",
]
