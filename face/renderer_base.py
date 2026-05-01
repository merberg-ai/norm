from __future__ import annotations

from abc import ABC, abstractmethod

from face.face_pack import FacePack


class FaceRenderer(ABC):
    """Base interface for beta2 face renderers.

    Pre3 intentionally implements server-rendered previews first. The fullscreen
    screen process can use the same pack/renderer APIs in a later release.
    """

    renderer_id = "base"

    @abstractmethod
    def render_svg(self, pack: FacePack, state: str, *, width: int, height: int) -> str:
        raise NotImplementedError
