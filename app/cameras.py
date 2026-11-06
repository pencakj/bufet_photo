"""Trusted camera registry. Capture endpoints are never supplied by API users."""
from dataclasses import dataclass, replace
import os


@dataclass(frozen=True)
class Camera:
    id: str
    name: str
    kind: str
    url: str
    source_page: str
    provider: str
    location: str
    read_only: bool = False


DEFAULT_CAMERA = "rozcesti"
CAMERAS = (
    Camera("rozcesti", "Chalupa na Rozcestí", "jpeg",
           "https://chalupanarozcesti.cz/webcam/latest.php",
           "https://chalupanarozcesti.cz/", "Chalupa na Rozcestí",
           "50.71° N · 15.67° E · 1 350 m",
           os.environ.get("LEGACY_READ_ONLY", "true").lower() == "true"),
    Camera("pec", "Pec pod Sněžkou", "jpeg",
           "https://kamery.humlnet.cz/images/webcams/pecpodsnezkou/2048x1536.jpg",
           "https://kamery.humlnet.cz/show_webcam.php?url=/images/webcams/pecpodsnezkou/2048x1536.jpg",
           "HUMlnet", "Pec pod Sněžkou"),
    Camera("lucni-bouda", "Luční bouda", "jpeg",
           "https://kamery.humlnet.cz/images/webcams/lucnibouda/2048x1536.jpg",
           "https://kamery.humlnet.cz/show_webcam.php?url=/images/webcams/lucnibouda/2048x1536.jpg",
           "HUMlnet", "Luční bouda"),
    Camera("snezka", "Sněžka", "jpeg",
           "https://kamery.humlnet.cz/images/webcams/snezka3/2048x1536.jpg",
           "https://kamery.humlnet.cz/show_webcam.php?url=/images/webcams/snezka3/2048x1536.jpg",
           "HUMlnet", "Sněžka"),
    Camera("klinove-boudy", "Klínové boudy", "hls",
           "https://wstream.comanet.cz:1943/live/Spindl-klinovky.stream_720p/playlist.m3u8",
           "https://webkamery-krkonose.cz/kamera/39-spindleruv-mlyn-klinove-boudy",
           "Webkamery Krkonoše / Comanet", "Špindlerův Mlýn · Klínové boudy"),
    Camera("svaty-petr", "Svatý Petr – Pláň", "hls",
           "https://wstream.comanet.cz:1943/live/Spindl-Plan.stream_720p/playlist.m3u8",
           "https://webkamery-krkonose.cz/kamera/17-spindleruv-mlyn-svaty-petr-plan",
           "Webkamery Krkonoše / Comanet", "Špindlerův Mlýn · Svatý Petr – Pláň"),
    Camera("bedrichov", "Bedřichov", "hls",
           "https://wstream.comanet.cz:1943/live/Spindl-Stoh.stream/playlist.m3u8",
           "https://webkamery-krkonose.cz/kamera/18-spindleruv-mlyn-bedrichov",
           "Webkamery Krkonoše / Comanet", "Špindlerův Mlýn · Bedřichov"),
    Camera("bedriska", "Hotel Bedřiška", "hls",
           "https://wstream.comanet.cz:1943/live/Spindl-Bedriska.stream_720p/playlist.m3u8",
           "https://webkamery-krkonose.cz/kamera/19-spindleruv-mlyn-horsky-hotel-bedriska",
           "Webkamery Krkonoše / Comanet", "Špindlerův Mlýn · Hotel Bedřiška"),
)
BY_ID = {camera.id: camera for camera in CAMERAS}


def read_only_mode() -> bool:
    return os.environ.get("READ_ONLY_MODE", "false").lower() == "true"


def get_camera(camera_id: str) -> Camera:
    camera = BY_ID[camera_id]
    return replace(camera, read_only=True) if read_only_mode() else camera
