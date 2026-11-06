FROM python:3.15.2-slim-trixie AS ffmpeg-build

# Build only the protocols/codecs needed for HLS -> JPEG; avoid the large
# distribution FFmpeg dependency tree (including unused XML/SVG decoders).
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends build-essential pkg-config libssl-dev xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN python -c "import urllib.request, hashlib; data = urllib.request.urlopen('https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz', timeout=60).read(); assert hashlib.sha256(data).hexdigest() == '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e'; open('/tmp/ffmpeg.tar.xz', 'wb').write(data)" \
    && tar -xJf /tmp/ffmpeg.tar.xz --strip-components=1 \
    && ./configure --prefix=/opt/ffmpeg --disable-everything --disable-autodetect \
        --disable-doc --disable-debug --disable-ffplay --disable-ffprobe \
        --disable-avdevice --disable-swresample --disable-x86asm --enable-small \
        --enable-version3 --enable-openssl \
        --enable-protocol=https,tls,tcp,crypto,pipe --enable-demuxer=hls,mpegts,mov \
        --enable-decoder=h264,hevc,mjpeg --enable-parser=h264,hevc,aac \
        --enable-encoder=mjpeg --enable-muxer=image2pipe \
        --enable-filter=scale,buffer,buffersink,format,null \
    && make -j2 \
    && make install

FROM python:3.15.2-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Prague

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ffmpeg-build /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-build /build/COPYING.LGPLv3 /usr/local/share/licenses/ffmpeg/COPYING.LGPLv3

COPY requirements.txt .
# Installers are build-time tools, not part of the serving runtime.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --upgrade --only-binary=:all: -r requirements.txt \
    && pip check \
    && pip uninstall -y pip \
    && python -c "import ensurepip, shutil; shutil.rmtree(ensurepip.__path__[0])"

COPY . .
RUN mkdir -p images thumbnails data camera-data \
    && chown 1001:1001 camera-data

USER 1001:1001

EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003", "--log-level", "info"]
