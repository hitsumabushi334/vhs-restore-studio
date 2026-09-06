# Third-party licenses

This register records the projects used or optionally detected by VHS Restore
Studio. The exact license obligations can depend on the selected binary build;
keep the license files distributed with each downloaded tool alongside the
tool when packaging a release.

| Component | Use | License / notice |
| --- | --- | --- |
| Python | Runtime | Python Software Foundation License |
| PySide6 / Qt for Python | GUI toolkit | LGPLv3, GPLv3, or commercial Qt terms; follow the selected distribution |
| FFmpeg | Probe, filtering, and encoding | LGPL/GPL depending on the build and enabled components |
| VapourSynth | Optional video scripting runtime | Follow the license shipped by the selected VapourSynth distribution |
| QTGMC / supporting VapourSynth scripts | Optional deinterlacing | Follow the upstream script and plugin license notices |
| Video2X | Optional Vulkan-first AI upscaling | Follow the upstream Video2X license and bundled notices |
| Real-ESRGAN ncnn Vulkan | Optional Vulkan AI upscaling | Follow the upstream Real-ESRGAN, ncnn, and bundled model notices |

Upstream project pages:

- [Python](https://www.python.org/)
- [Qt for Python](https://doc.qt.io/qtforpython/)
- [FFmpeg](https://ffmpeg.org/)
- [VapourSynth](https://www.vapoursynth.com/)
- [Video2X](https://github.com/K4YT3X/Video2X)
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
- [ncnn](https://github.com/Tencent/ncnn)
