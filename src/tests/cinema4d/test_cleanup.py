from __future__ import annotations

import pytest

from libraries.creative.dcc.cinema4d.cleanup import cleanup_scene


class FakeTag:
    def __init__(self, material: "FakeMaterial") -> None:
        self._material = material

    def GetMaterial(self) -> "FakeMaterial":
        return self._material


class FakeMaterial:
    def __init__(self, name: str, *, layer: "FakeLayer" | None = None) -> None:
        self.name = name
        self.layer = layer
        self._doc: FakeDocument | None = None
        self.removed = False

    def attach(self, document: "FakeDocument") -> None:
        self._doc = document

    def GetLayerObject(self) -> "FakeLayer" | None:
        return self.layer

    def GetNext(self) -> "FakeMaterial" | None:
        if self._doc is None:
            return None
        active = [material for material in self._doc.materials if not material.removed]
        try:
            index = active.index(self)
        except ValueError:
            return None
        next_index = index + 1
        if next_index < len(active):
            return active[next_index]
        return None

    def Remove(self) -> None:
        self.removed = True
        if self._doc is not None:
            self._doc.materials = [
                material for material in self._doc.materials if material is not self
            ]


class FakeObject:
    def __init__(
        self,
        name: str,
        *,
        obj_type: int | None = None,
        hidden: bool = False,
        layer: "FakeLayer" | None = None,
        tags: list[FakeTag] | None = None,
        children: list["FakeObject"] | None = None,
    ) -> None:
        self.name = name
        self._type = obj_type
        self._hidden = hidden
        self.layer = layer
        self._tags = list(tags or [])
        self._children = list(children or [])
        self._doc: FakeDocument | None = None
        self._parent: FakeObject | None = None
        self._module: FakeCinemaModule | None = None
        self.removed = False

    def attach(self, document: "FakeDocument", parent: "FakeObject" | None) -> None:
        self._doc = document
        self._parent = parent
        for child in self._children:
            child.attach(document, self)

    def set_module(self, module: "FakeCinemaModule") -> None:
        self._module = module
        for child in self._children:
            child.set_module(module)

    def GetTags(self) -> list[FakeTag]:
        return list(self._tags)

    def GetLayerObject(self) -> "FakeLayer" | None:
        return self.layer

    def GetDown(self) -> "FakeObject" | None:
        if self._children:
            return self._children[0]
        return None

    def GetNext(self) -> "FakeObject" | None:
        if self._doc is None:
            return None
        siblings = (
            self._doc.root_objects if self._parent is None else self._parent._children
        )
        try:
            index = siblings.index(self)
        except ValueError:
            return None
        next_index = index + 1
        if next_index < len(siblings):
            return siblings[next_index]
        return None

    def CheckType(self, type_id: int) -> bool:
        return self._type == type_id

    def GetType(self) -> int | None:
        return self._type

    def GetEditorMode(self) -> int:
        mode_off = getattr(self._module, "MODE_OFF", 0)
        mode_on = getattr(self._module, "MODE_ON", 1)
        return mode_off if self._hidden else mode_on

    def GetRenderMode(self) -> int:
        mode_off = getattr(self._module, "MODE_OFF", 0)
        mode_on = getattr(self._module, "MODE_ON", 1)
        return mode_off if self._hidden else mode_on

    def Remove(self) -> None:
        self.removed = True
        if self._doc is None:
            return
        if self._parent is None:
            self._doc.root_objects = [
                obj for obj in self._doc.root_objects if obj is not self
            ]
        else:
            self._parent._children = [
                child for child in self._parent._children if child is not self
            ]

    @property
    def children(self) -> list["FakeObject"]:
        return list(self._children)


class FakeLayer:
    def __init__(
        self,
        name: str,
        *,
        children: list["FakeLayer"] | None = None,
        is_root: bool = False,
    ) -> None:
        self.name = name
        self._children = list(children or [])
        self._is_root = is_root
        self._doc: FakeDocument | None = None
        self._parent: FakeLayer | None = None
        self.removed = False

    def attach(self, document: "FakeDocument", parent: "FakeLayer" | None) -> None:
        self._doc = document
        self._parent = parent
        for child in self._children:
            child.attach(document, self)

    def GetDown(self) -> "FakeLayer" | None:
        if self._children:
            return self._children[0]
        return None

    def GetNext(self) -> "FakeLayer" | None:
        if self._doc is None:
            return None
        if self._parent is None:
            return None
        siblings = self._parent._children
        try:
            index = siblings.index(self)
        except ValueError:
            return None
        next_index = index + 1
        if next_index < len(siblings):
            return siblings[next_index]
        return None

    def Remove(self) -> None:
        self.removed = True
        if self._parent is not None:
            self._parent._children = [
                child for child in self._parent._children if child is not self
            ]

    def IsRootLayer(self) -> bool:
        return self._is_root

    @property
    def children(self) -> list["FakeLayer"]:
        return list(self._children)


class FakeDocument:
    def __init__(
        self,
        *,
        objects: list[FakeObject] | None = None,
        materials: list[FakeMaterial] | None = None,
        layers: list[FakeLayer] | None = None,
    ) -> None:
        self.root_objects = list(objects or [])
        self.materials = list(materials or [])
        self._layer_root = FakeLayer("Root", is_root=True, children=list(layers or []))
        self._module: FakeCinemaModule | None = None

        for obj in self.root_objects:
            obj.attach(self, None)
        for material in self.materials:
            material.attach(self)
        self._layer_root.attach(self, None)

    def set_module(self, module: "FakeCinemaModule") -> None:
        self._module = module
        for obj in self.root_objects:
            obj.set_module(module)

    def GetFirstObject(self) -> FakeObject | None:
        if self.root_objects:
            return self.root_objects[0]
        return None

    def GetFirstMaterial(self) -> FakeMaterial | None:
        for material in self.materials:
            if not material.removed:
                return material
        return None

    def GetLayerObjectRoot(self) -> FakeLayer:
        return self._layer_root


class FakeDocumentsModule:
    def __init__(self, document: FakeDocument) -> None:
        self._document = document

    def GetActiveDocument(self) -> FakeDocument:
        return self._document


class FakeCinemaModule:
    MODE_OFF = 0
    MODE_ON = 1
    Onull = 100000

    def __init__(self, document: FakeDocument) -> None:
        self.documents = FakeDocumentsModule(document)
        document.set_module(self)


def test_cleanup_scene_removes_unused_materials_and_layers() -> None:
    unused_layer = FakeLayer("Unused")
    used_layer = FakeLayer("Used")
    used_material = FakeMaterial("Used", layer=used_layer)
    unused_material = FakeMaterial("Unused", layer=unused_layer)
    mesh = FakeObject("Mesh", tags=[FakeTag(used_material)])

    document = FakeDocument(
        objects=[mesh],
        materials=[used_material, unused_material],
        layers=[used_layer, unused_layer],
    )
    module = FakeCinemaModule(document)

    stats = cleanup_scene(document=document, module=module)

    assert stats["removed_materials"] == 1
    assert unused_material.removed is True
    assert used_material.removed is False
    assert stats["removed_layers"] == 1
    assert unused_layer.removed is True
    assert used_layer.removed is False


def test_cleanup_scene_removes_empty_nulls_and_hidden_objects() -> None:
    null_object = FakeObject("Null", obj_type=FakeCinemaModule.Onull)
    hidden_object = FakeObject("Hidden", hidden=True)
    parent = FakeObject(
        "Parent",
        hidden=True,
        children=[FakeObject("Child")],
    )

    document = FakeDocument(objects=[null_object, hidden_object, parent])
    module = FakeCinemaModule(document)

    stats = cleanup_scene(document=document, module=module)

    assert stats["removed_empty_nulls"] == 1
    assert null_object.removed is True
    assert hidden_object.removed is True
    assert stats["removed_hidden_singletons"] == 1
    assert parent.removed is False


def test_cleanup_scene_respects_disabled_operations() -> None:
    unused_layer = FakeLayer("Layer")
    unused_material = FakeMaterial("Mat", layer=unused_layer)
    document = FakeDocument(materials=[unused_material], layers=[unused_layer])
    module = FakeCinemaModule(document)

    stats = cleanup_scene(
        document=document,
        module=module,
        remove_unused_materials=False,
        remove_unused_layers=False,
    )

    assert stats["removed_materials"] == 0
    assert stats["removed_layers"] == 0
    assert unused_material.removed is False
    assert unused_layer.removed is False


def test_cleanup_scene_requires_module() -> None:
    document = FakeDocument()
    with pytest.raises(RuntimeError):
        cleanup_scene(document=document, module=None)
